# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import random
import re
import time
import logging
import requests
from threading import Thread, Timer
from dotenv import load_dotenv
from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B

from shop_core.bus import (
    STATE_AI, STATE_WAITING_INPUT, bot_send, get_chat_state, is_chat_muted, is_frozen,
    is_human, mark_human, notify, remember_chat_alias, set_chat_mute, set_chat_state,
)
from shop_core.confirm import get_pending
from shop_core.db import get_db
from shop_core.sanitizer import is_clean, sanitize_reason
from shop_core.settings import ini_bool, load_ai, load_ops, save_ai
from shop_core.plugin_settings import SettingsPage

load_dotenv()

logger = logging.getLogger("FPC.AIAssistant")

NAME = "AI FunPay Ultimate (Pro Edition)"
VERSION = "14.0.0"
DESCRIPTION = "ИИ-консультант: debounce, санитайзер, circuit breaker, приоритет человека"
CREDITS = "Cardinal Community"
UUID = "8a3d4f10-7b2c-4e89-9a1d-5c6e7f8a9b0c"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}
AI_FILE = "configs/ai.cfg"

DEBOUNCE_BUFFERS = {}
GUARD_WORDS = {"код", "гвард", "guard", "2fa", "пароль", "логин", "code"}
_WORD_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)

SYSTEM_PROMPT = (
    "Ты продавец на FunPay, общаешься как живой человек, коротко (1-3 предложения), "
    "геймерский сленг допустим, без канцелярита. Не говори, что ты бот. "
    "Запрещено: ссылки, домены, @юзернеймы, телефоны, номера карт, слова про отзыв/оценку/звёзды, "
    "подтверждение заказа, закрыть заказ, карта, телеграм, шаблонные фразы про автовыдачу круглосуточно, "
    "эмодзи птички, слово Cardinal и любые контакты вне FunPay. Пиши как живой человек, без шаблонов ботов. "
    "Даты и сроки аренды не вычисляй — если в контексте есть готовые переменные, используй их как есть. "
    "Если не уверен — скажи, что проверишь заказ и напишешь сюда. Не обещай, что сейчас придёт человек, и не проси отзыв."
)


def _cfg():
    return load_ai()["AI"] if load_ai().has_section("AI") else {}


def _store_history(chat_id: int, role: str, message: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO chat_history (chat_id, role, message, created_at) VALUES (?, ?, ?, ?)",
            (chat_id, role, message, time.time()),
        )
        conn.execute(
            """DELETE FROM chat_history WHERE id NOT IN (
                 SELECT id FROM chat_history WHERE chat_id = ? ORDER BY id DESC LIMIT 16
               ) AND chat_id = ?""",
            (chat_id, chat_id),
        )


def _history(chat_id: int, limit: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT role, message FROM chat_history WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
    rows = list(reversed(rows))
    return [{"role": r["role"], "content": r["message"]} for r in rows]


def call_llm(messages: list[dict], timeout: float) -> str | None:
    model = _cfg().get("model", "google/gemini-2.0-flash-exp:free")
    max_tokens = int(_cfg().get("max_tokens", 160))
    or_key = os.getenv("OPENROUTER_KEY", "").strip()
    ya_key = os.getenv("YANDEX_API_KEY", "").strip()

    if or_key:
        try:
            res = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {or_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": max_tokens},
                timeout=timeout,
            )
            if res.status_code == 200:
                return (res.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception as ex:
            logger.debug("[AIAssistant] OpenRouter: %s", ex)

    if ya_key:
        text = _call_yandex(ya_key, messages, max_tokens, timeout)
        if text:
            return text
    return None


def _yandex_models() -> list[str]:
    folder = os.getenv("YANDEX_FOLDER_ID", "").strip()
    env_model = os.getenv("YANDEX_MODEL", "").strip()
    out = []
    if env_model:
        out.append(env_model)
    if folder:
        out.append(f"gpt://{folder}/yandexgpt-lite/latest")
        out.append(f"gpt://{folder}/yandexgpt-lite")
    out.extend(["yandexgpt-lite/latest", "yandexgpt-lite"])
    seen = set()
    uniq = []
    for m in out:
        if m not in seen:
            seen.add(m)
            uniq.append(m)
    return uniq


def _call_yandex(ya_key: str, messages: list[dict], max_tokens: int, timeout: float) -> str | None:
    ya_msgs = []
    for m in messages:
        role = m.get("role", "user")
        if role not in ("system", "user", "assistant"):
            role = "user"
        ya_msgs.append({"role": role, "content": m.get("content") or m.get("text") or ""})
    headers = {"Authorization": f"Api-Key {ya_key}", "Content-Type": "application/json"}
    last_err = ""
    for model in _yandex_models():
        try:
            res = requests.post(
                "https://llm.api.cloud.yandex.net/v1/chat/completions",
                headers=headers,
                json={"model": model, "messages": ya_msgs, "max_tokens": max_tokens},
                timeout=timeout,
            )
            if res.status_code == 200:
                return (res.json()["choices"][0]["message"]["content"] or "").strip()
            last_err = f"{res.status_code} {res.text[:180]}"
        except Exception as ex:
            last_err = str(ex)
    logger.debug("[AIAssistant] Yandex: %s", last_err)
    return None


def _escalation_kb(chat_id) -> K:
    kb = K()
    kb.add(B("💬 Чат человеку", callback_data=f"OPS:human:{chat_id}"))
    return kb


def escalate(cardinal, chat_id, chat_name, text, reason: str):
    set_chat_mute(chat_id, 900)
    mark_human(chat_id)
    if str(_cfg().get("escalate_funpay", "0")).lower() in ("1", "true", "yes"):
        bot_send(cardinal, chat_id, "Сейчас продавец зайдёт в диалог и ответит лично.", chat_name)
    notify(
        cardinal,
        f"🚨 <b>Эскалация ИИ</b> ({reason})\nПокупатель: <b>{chat_name}</b>\n<code>{text[:400]}</code>",
        True,
        keyboard=_escalation_kb(chat_id),
    )


def process_message(cardinal, chat_id: int, chat_name: str, text: str):
    try:
        enabled = str(_cfg().get("enabled", "0")).lower() in ("1", "true", "yes")
        if is_frozen() or not enabled:
            return
        if is_human(chat_id) or is_chat_muted(chat_id):
            return
        if get_chat_state(chat_id) == STATE_WAITING_INPUT:
            return
        try:
            if get_pending(chat_id, cardinal=cardinal):
                return
        except Exception:
            pass
        if str(_cfg().get("require_lots", "1")).lower() in ("1", "true", "yes"):
            lots = getattr(cardinal, "lots_ids", None) or []
            try:
                if cardinal.profile:
                    lots = cardinal.profile.get_lots() or lots
            except Exception:
                pass
            if not lots:
                return

        t_lower = text.lower()
        tokens = set(_WORD_RE.findall(t_lower))
        if tokens & GUARD_WORDS or any(p in t_lower for p in ("где код", "дай код", "код стим", "steam guard")):
            return

        if any(w in t_lower for w in ("позови продавца", "позовите продавца", "позови человека", "!admin")):
            escalate(cardinal, chat_id, chat_name, text, "вызов оператора")
            return

        ops = load_ops()
        delay_min = ops.getfloat("Ops", "human_typing_min", fallback=1.5)
        delay_max = ops.getfloat("Ops", "human_typing_max", fallback=3.5)
        time.sleep(random.uniform(delay_min, delay_max))

        if any(w in t_lower for w in ["привет", "здравствуйте", "ку", "хай", "здарова", "добрый"]):
            reply = random.choice((
                "Привет. Да, всё в силе, можно оформлять.",
                "Хай. Слот живой, после оплаты напишу сюда.",
                "Йо. В наличии, бери спокойно.",
            ))
        elif any(w in t_lower for w in ["тут", "на месте", "актуально", "в наличии"]):
            reply = random.choice((
                "Да, на месте. Можешь брать.",
                "Актуально. После оплаты всё придёт в этот чат.",
                "Живой лот, оформляй.",
            ))
        elif any(w in t_lower for w in ["как купить", "как оплатить"]):
            reply = "На странице лота кнопка «Купить», дальше любой удобный способ. После оплаты данные придут сюда."
        else:
            hist_n = int(_cfg().get("history_limit", 8))
            timeout = load_ops().getfloat("Ops", "llm_timeout", fallback=9)
            msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
            msgs.extend(_history(chat_id, hist_n))
            msgs.append({"role": "user", "content": text})
            reply = call_llm(msgs, timeout)
            if not reply:
                reply = random.choice((
                    "Сейчас гляну заказ и отвечу тут.",
                    "Секунду, проверяю.",
                    "На месте, сейчас уточню и напишу.",
                ))
            if not is_clean(reply):
                reason = sanitize_reason(reply)
                if str(_cfg().get("retry_on_sanitizer", "1")) in ("1", "true", "True"):
                    retry_msgs = msgs + [
                        {"role": "assistant", "content": reply},
                        {"role": "user", "content": f"Перепиши без ссылок, контактов и запретных слов. Причина фильтра: {reason}"},
                    ]
                    reply = call_llm(retry_msgs, timeout) or ""
                if not reply or not is_clean(reply):
                    reply = "Ок, товар по описанию, после оплаты всё придёт в этот чат."

        if not is_clean(reply):
            reply = "Ок, после оплаты напишу сюда."

        _store_history(chat_id, "user", text)
        _store_history(chat_id, "assistant", reply)
        set_chat_state(chat_id, STATE_AI)
        bot_send(cardinal, chat_id, reply, chat_name)
    except Exception as ex:
        logger.error("[AIAssistant] %s", ex)


def debounce_handler(cardinal, chat_id, chat_name):
    if chat_id in DEBOUNCE_BUFFERS:
        text = " ".join(DEBOUNCE_BUFFERS[chat_id]["texts"]).strip()
        del DEBOUNCE_BUFFERS[chat_id]
        if text:
            process_message(cardinal, chat_id, chat_name, text)


def on_new_message(cardinal, event):
    msg = getattr(event, "message", None)
    if not msg or getattr(msg, "by_bot", False):
        return
    try:
        from shop_core.confirm import is_system_message
        if is_system_message(msg):
            return
    except Exception:
        if getattr(msg, "author_id", None) == 0:
            return
    if msg.author_id == cardinal.account.id:
        return
    chat_id = msg.chat_id
    chat_name = msg.chat_name
    text = (msg.text or "").strip()
    if not text:
        return
    try:
        remember_chat_alias(chat_id, msg.author_id)
    except Exception:
        pass
    try:
        if is_chat_muted(chat_id) or get_pending(chat_id, cardinal=cardinal, msg=msg):
            return
    except Exception:
        pass
    if chat_id not in DEBOUNCE_BUFFERS:
        DEBOUNCE_BUFFERS[chat_id] = {"texts": [], "timer": None}
    if DEBOUNCE_BUFFERS[chat_id]["timer"]:
        DEBOUNCE_BUFFERS[chat_id]["timer"].cancel()
    DEBOUNCE_BUFFERS[chat_id]["texts"].append(text)
    delay = float(_cfg().get("debounce", 2.2))
    t = Timer(delay, debounce_handler, args=(cardinal, chat_id, chat_name))
    DEBOUNCE_BUFFERS[chat_id]["timer"] = t
    t.daemon = True
    t.start()


def _ai_on() -> bool:
    return ini_bool(AI_FILE, "AI", "enabled", False)


def init_settings(cardinal):
    def _flip(key, default=False):
        def setter(_new):
            cfg = load_ai()
            if not cfg.has_section("AI"):
                cfg.add_section("AI")
            cur = cfg.get("AI", key, fallback="1" if default else "0")
            cfg.set("AI", key, "0" if str(cur).lower() in ("1", "true", "yes") else "1")
            save_ai(cfg)
        return setter

    def status():
        on = _ai_on()
        lots_n = len(getattr(cardinal, "lots_ids", []) or [])
        ya = "есть" if os.getenv("YANDEX_API_KEY", "").strip() else "нет"
        folder = "есть" if os.getenv("YANDEX_FOLDER_ID", "").strip() else "нет (нужен в .env)"
        return (
            f"Сейчас: {'работает' if on else 'выключен (FunPay не получит автоответы)'}\n"
            f"Лотов на аккаунте: <b>{lots_n}</b>\n"
            f"Yandex ключ: {ya} | folder id: {folder}\n"
            f"<i>Если FunPay пишет «сообщение скрыто» — не включай автоответы, пока поддержка не снимет mute.</i>"
        )

    SettingsPage(UUID, NAME, "Автоответы в FunPay-чате. По умолчанию выключены.") \
        .add_toggle("enabled", "Автоответы ИИ", _ai_on, _flip("enabled")) \
        .add_toggle("require_lots", "Только если есть лоты",
                    lambda: ini_bool(AI_FILE, "AI", "require_lots", True), _flip("require_lots", True)) \
        .add_toggle("escalate_funpay", "Писать в FunPay, если зовут человека",
                    lambda: ini_bool(AI_FILE, "AI", "escalate_funpay", False), _flip("escalate_funpay")) \
        .set_status(status) \
        .attach(cardinal)


BIND_TO_PRE_INIT = [init_settings]
BIND_TO_NEW_MESSAGE = [on_new_message]
