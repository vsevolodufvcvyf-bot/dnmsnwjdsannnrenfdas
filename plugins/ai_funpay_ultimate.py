# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import os
import random
import re
import threading
import time
import logging
import requests
from threading import Timer
from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B

from shop_core.bus import (
    STATE_AI, STATE_WAITING_INPUT, bot_send, get_chat_state, is_chat_muted, is_frozen,
    is_human, mark_human, notify, remember_chat_alias, set_chat_mute, set_chat_state,
)
from shop_core.confirm import get_pending
from shop_core.db import get_db
from shop_core.sanitizer import is_clean, promise_reason, sanitize_reason
from shop_core.settings import ini_bool, load_ai, load_ops, save_ai
from shop_core.plugin_settings import SettingsPage

logger = logging.getLogger("FPC.AIAssistant")

NAME = "AI FunPay Ultimate (Pro Edition)"
VERSION = "15.0.0"
DESCRIPTION = "ИИ-помощник продавца: честно представляется, не обещает денег, зовёт человека"
CREDITS = "Cardinal Community"
UUID = "8a3d4f10-7b2c-4e89-9a1d-5c6e7f8a9b0c"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}
AI_FILE = "configs/ai.cfg"

DEBOUNCE_BUFFERS = {}
_DEBOUNCE_LOCK = threading.Lock()
GUARD_WORDS = {"код", "гвард", "guard", "2fa", "пароль", "логин", "code"}
LOGIN_PROBLEM_RE = re.compile(
    r"не\s+подход|не\s+работа|неверн|ошибк|не\s+могу\s+(?:войти|зайти)|не\s+пуска|смен\w*\s+парол|заблок|бан\b",
    re.IGNORECASE,
)
MONEY_ASK_RE = re.compile(
    r"верн\w*\s+(?:мне\s+)?(?:деньги|средства|оплату)|возврат|бесплатн|даром|скидк|промокод|дешевле|компенсац",
    re.IGNORECASE,
)
CALL_SELLER = ("позови продавца", "позовите продавца", "позови человека", "живого человека", "!admin")
_WORD_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)

GREETING_WORDS = {"привет", "здравствуйте", "здравствуй", "ку", "хай", "здарова", "добрый", "салам", "hello", "hi", "йо"}
HERE_WORDS = {"тут", "актуально", "актуален", "актуальна"}
HERE_PHRASES = ("на месте", "в наличии", "есть в наличии")
HOW_PHRASES = ("как купить", "как оплатить")
GREETING_REPLIES = (
    "Привет! Подскажу по товару — что интересует?",
    "Здравствуйте! Чем помочь?",
    "Привет! Спрашивай, отвечу по лоту.",
)
HERE_REPLIES = (
    "На связи. Если лот открыт на витрине — его можно оформлять.",
    "Да, на связи. Пока лот виден в списке, его можно купить.",
)
HOW_REPLY = "На странице лота кнопка «Купить», дальше любой удобный способ оплаты. Всё по заказу — в этом чате."
HOLD_REPLY = "Этот вопрос решает продавец — он ответит здесь."

SYSTEM_PROMPT = (
    "Ты — автоматический помощник продавца на FunPay. Отвечай коротко (1–3 предложения), дружелюбно, "
    "без канцелярита. Если спрашивают, бот ли ты, честно скажи, что ты автоматический помощник, "
    "а продавец подключится при необходимости. "
    "Никогда не обещай возврат денег, скидки, бонусы, подарки, бесплатный товар, компенсации и сроки, "
    "которых нет в описании лота — скажи, что это решает продавец. "
    "Не выдумывай наличие, цены и характеристики товара: не знаешь — скажи, что уточнишь у продавца. "
    "Запрещено: ссылки, домены, @юзернеймы, телефоны, номера карт, контакты вне FunPay, "
    "слова про отзыв, оценку и звёзды-оценки, просьбы подтвердить или закрыть заказ, слово Cardinal. "
    "Даты и сроки аренды не вычисляй — если в контексте есть готовые значения, используй их как есть."
)


def pick_template(text: str) -> str | None:
    """Шаблон только для коротких сообщений и только по целым словам: «куплю» — не «ку»."""
    low = (text or "").lower().replace("ё", "е")
    tokens = set(_WORD_RE.findall(low))
    if not tokens:
        return None
    if len(tokens) <= 3 and tokens & GREETING_WORDS:
        return random.choice(GREETING_REPLIES)
    if len(tokens) <= 5 and (tokens & HERE_WORDS or any(p in low for p in HERE_PHRASES)):
        return random.choice(HERE_REPLIES)
    if any(p in low for p in HOW_PHRASES):
        return HOW_REPLY
    return None


def _cfg():
    cfg = load_ai()
    return cfg["AI"] if cfg.has_section("AI") else {}


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


def escalate(cardinal, chat_id, chat_name, text, reason: str, holding_reply: str | None = None):
    """Отдаёт чат продавцу: ИИ в нём молчит, продавцу — уведомление с кнопкой."""
    set_chat_mute(chat_id, 900)
    mark_human(chat_id)
    if holding_reply:
        bot_send(cardinal, chat_id, holding_reply, chat_name)
    elif str(_cfg().get("escalate_funpay", "0")).lower() in ("1", "true", "yes"):
        bot_send(cardinal, chat_id, "Сейчас продавец зайдёт в диалог и ответит лично.", chat_name)
    notify(
        cardinal,
        f"🚨 <b>Эскалация ИИ</b> ({html.escape(reason)})\nПокупатель: <b>{html.escape(str(chat_name))}</b>\n"
        f"<code>{html.escape(text[:400])}</code>",
        True,
        keyboard=_escalation_kb(chat_id),
    )


def process_message(cardinal, chat_id: int, chat_name: str, text: str):
    try:
        cfg = _cfg()
        enabled = str(cfg.get("enabled", "0")).lower() in ("1", "true", "yes")
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
            logger.debug("TRACEBACK", exc_info=True)
        if str(cfg.get("require_lots", "1")).lower() in ("1", "true", "yes"):
            lots = getattr(cardinal, "lots_ids", None) or []
            try:
                if cardinal.profile:
                    lots = cardinal.profile.get_lots() or lots
            except Exception:
                logger.debug("TRACEBACK", exc_info=True)
            if not lots:
                return

        t_lower = text.lower()
        tokens = set(_WORD_RE.findall(t_lower))
        if tokens & GUARD_WORDS or any(p in t_lower for p in ("где код", "дай код", "код стим", "steam guard")):
            if LOGIN_PROBLEM_RE.search(t_lower):
                escalate(cardinal, chat_id, chat_name, text, "проблема со входом",
                         holding_reply="Передал продавцу, он проверит аккаунт и ответит здесь.")
            return

        if any(w in t_lower for w in CALL_SELLER):
            escalate(cardinal, chat_id, chat_name, text, "вызов продавца")
            return
        if MONEY_ASK_RE.search(t_lower):
            escalate(cardinal, chat_id, chat_name, text, "вопрос про деньги / возврат / скидку", holding_reply=HOLD_REPLY)
            return

        ops = load_ops()
        delay_min = ops.getfloat("Ops", "human_typing_min", fallback=1.5)
        delay_max = ops.getfloat("Ops", "human_typing_max", fallback=3.5)
        time.sleep(random.uniform(delay_min, delay_max))

        reply = pick_template(text)
        if reply is None:
            hist_n = int(cfg.get("history_limit", 8))
            timeout = ops.getfloat("Ops", "llm_timeout", fallback=9)
            msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
            msgs.extend(_history(chat_id, hist_n))
            msgs.append({"role": "user", "content": text})
            reply = call_llm(msgs, timeout)
            if not reply:
                escalate(cardinal, chat_id, chat_name, text, "нейросеть не ответила",
                         holding_reply="Уточню у продавца и отвечу здесь.")
                return
            if not is_clean(reply):
                reason = sanitize_reason(reply)
                if str(cfg.get("retry_on_sanitizer", "1")) in ("1", "true", "True"):
                    retry_msgs = msgs + [
                        {"role": "assistant", "content": reply},
                        {"role": "user", "content": f"Перепиши без ссылок, контактов и запретных слов. Причина фильтра: {reason}"},
                    ]
                    reply = call_llm(retry_msgs, timeout) or ""
                if not reply or not is_clean(reply):
                    reply = "Уточню у продавца и отвечу здесь."
            promised = promise_reason(reply)
            if promised:
                escalate(cardinal, chat_id, chat_name, text, f"ИИ хотел пообещать: {promised} — не отправил",
                         holding_reply=HOLD_REPLY)
                return

        if not is_clean(reply):
            reply = "Уточню у продавца и отвечу здесь."

        _store_history(chat_id, "user", text)
        _store_history(chat_id, "assistant", reply)
        set_chat_state(chat_id, STATE_AI)
        bot_send(cardinal, chat_id, reply, chat_name)
    except Exception as ex:
        logger.error("[AIAssistant] %s", ex, exc_info=True)


def debounce_handler(cardinal, chat_id, chat_name):
    with _DEBOUNCE_LOCK:
        buf = DEBOUNCE_BUFFERS.pop(chat_id, None)
    text = " ".join(buf["texts"]).strip() if buf else ""
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
        logger.debug("TRACEBACK", exc_info=True)
    try:
        if is_chat_muted(chat_id) or get_pending(chat_id, cardinal=cardinal, msg=msg):
            return
    except Exception:
        logger.debug("TRACEBACK", exc_info=True)
    delay = float(_cfg().get("debounce", 2.2))
    with _DEBOUNCE_LOCK:
        buf = DEBOUNCE_BUFFERS.setdefault(chat_id, {"texts": [], "timer": None})
        if buf["timer"]:
            buf["timer"].cancel()
        buf["texts"].append(text)
        t = Timer(delay, debounce_handler, args=(cardinal, chat_id, chat_name))
        t.daemon = True
        buf["timer"] = t
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
