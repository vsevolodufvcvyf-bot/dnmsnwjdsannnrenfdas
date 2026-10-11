# -*- coding: utf-8 -*-
"""Команда Telegram: владелец и операторы. Доступ к пульту — только по числовому ID.

Ник (@username) сам по себе доступ не даёт: его можно сменить, а освободившийся займёт другой
человек. Приглашённый по нику, написав боту, только отправляет владельцу запрос с кнопкой «пустить».
"""
from __future__ import annotations

import configparser
import html
import logging
import os
import re
import threading
import time

from shop_core.fileio import write_config
from tg_bot import utils as tg_utils

logger = logging.getLogger("FPC.Team")
TEAM_FILE = os.path.join("configs", "team.cfg")
CB_PREFIX = "TEAM:"
_USER_RE = re.compile(r"^[A-Za-z0-9_]{4,32}$")
_REQUEST_COOLDOWN = 600

_LOCK = threading.RLock()
_LAST_REQUEST: dict[int, float] = {}
_PENDING_NAMES: dict[int, str] = {}


def _ensure_file() -> None:
    if os.path.exists(TEAM_FILE):
        return
    env_owner = os.getenv("TELEGRAM_OWNER_ID", "").strip()
    cfg = configparser.ConfigParser()
    cfg["Team"] = {
        "usernames": "",
        "ids": "",
        "owner_id": env_owner if env_owner.isdigit() else "",
    }
    save_team(cfg)


def load_team() -> configparser.ConfigParser:
    _ensure_file()
    cfg = configparser.ConfigParser()
    cfg.read(TEAM_FILE, encoding="utf-8")
    if not cfg.has_section("Team"):
        cfg["Team"] = {"usernames": "", "ids": "", "owner_id": ""}
    return cfg


def save_team(cfg: configparser.ConfigParser) -> None:
    with _LOCK:
        write_config(TEAM_FILE, cfg)


def _split(raw: str) -> list[str]:
    return [p.strip().lstrip("@") for p in (raw or "").replace(";", ",").split(",") if p.strip()]


def owner_id() -> int:
    """Владелец: TELEGRAM_OWNER_ID из .env, иначе owner_id из team.cfg. Нет — 0 (владельца нет)."""
    raw = os.getenv("TELEGRAM_OWNER_ID", "").strip()
    if raw.isdigit():
        return int(raw)
    try:
        raw = load_team().get("Team", "owner_id", fallback="").strip()
    except Exception:
        raw = ""
    return int(raw) if raw.isdigit() else 0


def is_owner(user_id) -> bool:
    oid = owner_id()
    try:
        return bool(oid) and int(user_id) == oid
    except (TypeError, ValueError):
        return False


def invited_usernames() -> set[str]:
    names = set()
    env = os.getenv("TELEGRAM_OPERATORS", "")
    names.update(x.lower() for x in _split(env) if not x.isdigit() and _USER_RE.match(x))
    cfg = load_team()
    names.update(x.lower() for x in _split(cfg.get("Team", "usernames", fallback="")) if _USER_RE.match(x))
    return names


allowed_usernames = invited_usernames


def username_invited(username: str | None) -> bool:
    if not username:
        return False
    return username.lstrip("@").lower() in invited_usernames()


username_allowed = username_invited


def extra_ids() -> set[int]:
    """Числовые ID, которым пульт открыт без пароля: операторы из .env и team.cfg плюс владелец."""
    ids: set[int] = set()
    for x in _split(os.getenv("TELEGRAM_OPERATORS", "")):
        if x.isdigit():
            ids.add(int(x))
    cfg = load_team()
    for x in _split(cfg.get("Team", "ids", fallback="")):
        if x.isdigit():
            ids.add(int(x))
    oid = owner_id()
    if oid:
        ids.add(oid)
    return ids


def invite_username(username: str) -> bool:
    name = (username or "").strip().lstrip("@")
    if not _USER_RE.match(name):
        return False
    cfg = load_team()
    names = _split(cfg.get("Team", "usernames", fallback=""))
    if name.lower() not in {n.lower() for n in names}:
        names.append(name)
        cfg.set("Team", "usernames", ", ".join(names))
        save_team(cfg)
    return True


def remember_id(user_id: int, username: str | None = None) -> None:
    """Сохраняет ID оператора; его ник убирается из списка ожидающих приглашений."""
    with _LOCK:
        cfg = load_team()
        ids = _split(cfg.get("Team", "ids", fallback=""))
        sid = str(int(user_id))
        if sid not in ids:
            ids.append(sid)
            cfg.set("Team", "ids", ", ".join(ids))
        if username:
            low = username.lstrip("@").lower()
            names = [n for n in _split(cfg.get("Team", "usernames", fallback="")) if n.lower() != low]
            cfg.set("Team", "usernames", ", ".join(names))
        save_team(cfg)


def operator_notifications() -> dict:
    n = tg_utils.NotificationTypes
    return {
        n.bot_start: True,
        n.new_message: True,
        n.new_order: True,
        n.order_confirmed: True,
        n.delivery: True,
        n.other: True,
        n.ad: 1,
        n.announcement: 1,
        n.critical: True,
    }


def ensure_operator_notifications(tg, chat_id) -> None:
    """Дописывает недостающие типы. Уже выключенные оператором не включает обратно."""
    if tg is None or chat_id is None:
        return
    chat = str(chat_id)
    cur = dict(tg.notification_settings.get(chat) or {})
    for key, value in operator_notifications().items():
        cur.setdefault(key, value)
    tg.notification_settings[chat] = cur
    tg_utils.save_notification_settings(tg.notification_settings)


def grant_operator(tg, user_id: int, username: str | None = None) -> bool:
    """Пускает в пульт и включает уведомления. True, если человека только что добавили."""
    if tg is None or not user_id:
        return False
    user_id = int(user_id)
    added = user_id not in tg.authorized_users
    if added:
        tg.authorized_users[user_id] = {"username": (username or "").lstrip("@")}
        tg_utils.save_authorized_users(tg.authorized_users)
    elif username and not (tg.authorized_users.get(user_id) or {}).get("username"):
        tg.authorized_users[user_id]["username"] = username.lstrip("@")
        tg_utils.save_authorized_users(tg.authorized_users)
    if str(user_id) not in tg.notification_settings:
        ensure_operator_notifications(tg, user_id)
    remember_id(user_id, username)
    if added:
        logger.info("[Team] оператор %s (@%s) добавлен", user_id, username or "—")
    return added


def request_approval(tg, user_id: int, username: str | None) -> bool:
    """Отправляет владельцу запрос с кнопками. Не чаще раза в 10 минут на человека."""
    oid = owner_id()
    bot = getattr(tg, "bot", None)
    if not oid or bot is None or not user_id:
        return False
    now = time.time()
    with _LOCK:
        if now - _LAST_REQUEST.get(int(user_id), 0) < _REQUEST_COOLDOWN:
            return False
        _LAST_REQUEST[int(user_id)] = now
        _PENDING_NAMES[int(user_id)] = (username or "").lstrip("@")
    from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
    kb = K()
    kb.row(
        B("✅ Пустить", callback_data=f"{CB_PREFIX}ok:{int(user_id)}"),
        B("❌ Отказать", callback_data=f"{CB_PREFIX}no:{int(user_id)}"),
    )
    nick = html.escape((username or "").lstrip("@")) or "без ника"
    try:
        bot.send_message(
            oid,
            f"👥 <b>Запрос доступа к пульту</b>\n@{nick} · ID <code>{int(user_id)}</code>\n"
            f"Ник есть в списке приглашённых. Пустить этого человека?",
            reply_markup=kb, parse_mode="HTML",
        )
    except Exception:
        logger.warning("[Team] не смог отправить запрос владельцу", exc_info=True)
        return False
    try:
        bot.send_message(int(user_id), "Запрос отправлен владельцу. Когда он подтвердит, нажми /menu.")
    except Exception:
        logger.debug("TRACEBACK", exc_info=True)
    logger.info("[Team] запрос доступа от %s (@%s) отправлен владельцу", user_id, username or "—")
    return True


def handle_decision(tg, c) -> None:
    """Кнопки «Пустить / Отказать» из запроса доступа. Решает только владелец."""
    bot = tg.bot
    parts = (c.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        bot.answer_callback_query(c.id)
        return
    if not is_owner(c.from_user.id):
        bot.answer_callback_query(c.id, "Решает только владелец.", show_alert=True)
        return
    action, uid = parts[1], int(parts[2])
    with _LOCK:
        nick = _PENDING_NAMES.pop(uid, "")
    if action == "ok":
        grant_operator(tg, uid, nick or None)
        result = f"✅ Пустил @{html.escape(nick) or uid} (ID <code>{uid}</code>)."
        try:
            bot.send_message(uid, "✅ Доступ к пульту открыт. Нажми /menu.")
        except Exception:
            logger.debug("TRACEBACK", exc_info=True)
    else:
        result = f"❌ Отказано: @{html.escape(nick) or uid} (ID <code>{uid}</code>)."
    bot.answer_callback_query(c.id)
    try:
        bot.edit_message_text(result, c.message.chat.id, c.message.id, parse_mode="HTML")
    except Exception:
        bot.send_message(c.message.chat.id, result, parse_mode="HTML")


def try_authorize_message(tg, m) -> bool:
    """Пускает без пароля только по ID из списка. Приглашённый ник — запрос владельцу."""
    if tg is None or m is None or getattr(m.chat, "type", "") != "private":
        return False
    uid = m.from_user.id
    if uid in getattr(tg, "authorized_users", {}):
        return False
    uname = getattr(m.from_user, "username", None)
    if uid in extra_ids():
        grant_operator(tg, uid, uname)
        return True
    if username_invited(uname):
        request_approval(tg, uid, uname)
    return False


def bootstrap(tg) -> None:
    if not tg or not getattr(tg, "bot", None):
        return
    for uid in extra_ids():
        grant_operator(tg, uid, None)


def team_text(tg) -> str:
    users = getattr(tg, "authorized_users", {}) or {}
    oid = owner_id()
    lines = ["👥 <b>Команда пульта</b>\n"]
    if not oid:
        lines.append("⚠️ Владелец не задан: впиши свой ID в .env → TELEGRAM_OWNER_ID.")
    if not users:
        lines.append("Пока никого.")
    for uid, meta in users.items():
        nick = meta.get("username") if isinstance(meta, dict) else ""
        tag = f"@{html.escape(nick)}" if nick else "без ника"
        role = " · владелец" if oid and int(uid) == oid else ""
        lines.append(f"• {tag}  <code>{uid}</code>{role}")
    waiting = sorted(invited_usernames())
    if waiting:
        lines.append("\nПриглашены, ждут подтверждения: " + ", ".join(f"@{html.escape(n)}" for n in waiting))
        lines.append("Когда человек напишет боту, тебе придёт кнопка «Пустить».")
    lines.append(
        "\nДобавить: <code>/op 123456789</code> — сразу по ID, "
        "<code>/op @username</code> — приглашение с подтверждением. Только владелец."
    )
    return "\n".join(lines)
