# -*- coding: utf-8 -*-
"""Команда Telegram: владелец + операторы по @username. Пароль им не нужен."""
from __future__ import annotations

import configparser
import logging
import os
import re

from tg_bot import utils as tg_utils

logger = logging.getLogger("FPC.Team")
TEAM_FILE = os.path.join("configs", "team.cfg")
_USER_RE = re.compile(r"^[A-Za-z0-9_]{4,32}$")


def _ensure_file() -> None:
    if os.path.exists(TEAM_FILE):
        return
    os.makedirs("configs", exist_ok=True)
    cfg = configparser.ConfigParser()
    cfg["Team"] = {
        "usernames": "",
        "ids": "",
        "owner_id": os.getenv("TELEGRAM_OWNER_ID", "").strip() or "",
    }
    with open(TEAM_FILE, "w", encoding="utf-8") as f:
        cfg.write(f)


def load_team() -> configparser.ConfigParser:
    _ensure_file()
    cfg = configparser.ConfigParser()
    cfg.read(TEAM_FILE, encoding="utf-8")
    if not cfg.has_section("Team"):
        cfg["Team"] = {"usernames": "", "ids": ""}
    return cfg


def save_team(cfg: configparser.ConfigParser) -> None:
    os.makedirs("configs", exist_ok=True)
    with open(TEAM_FILE, "w", encoding="utf-8") as f:
        cfg.write(f)


def _split(raw: str) -> list[str]:
    return [p.strip().lstrip("@") for p in (raw or "").replace(";", ",").split(",") if p.strip()]


def allowed_usernames() -> set[str]:
    names = set()
    env = os.getenv("TELEGRAM_OPERATORS", "")
    names.update(x.lower() for x in _split(env) if not x.isdigit() and _USER_RE.match(x))
    cfg = load_team()
    names.update(x.lower() for x in _split(cfg.get("Team", "usernames", fallback="")) if _USER_RE.match(x))
    return names


def extra_ids() -> set[int]:
    ids: set[int] = set()
    env = os.getenv("TELEGRAM_OPERATORS", "")
    for x in _split(env):
        if x.isdigit():
            ids.add(int(x))
    cfg = load_team()
    for x in _split(cfg.get("Team", "ids", fallback="")):
        if x.isdigit():
            ids.add(int(x))
    owner = os.getenv("TELEGRAM_OWNER_ID", "").strip()
    if owner.isdigit():
        ids.add(int(owner))
    oid = cfg.get("Team", "owner_id", fallback="").strip()
    if oid.isdigit():
        ids.add(int(oid))
    return ids


def remember_id(user_id: int, username: str | None = None) -> None:
    cfg = load_team()
    ids = _split(cfg.get("Team", "ids", fallback=""))
    sid = str(int(user_id))
    if sid not in ids:
        ids.append(sid)
        cfg.set("Team", "ids", ", ".join(ids))
    if username:
        names = _split(cfg.get("Team", "usernames", fallback=""))
        low = username.lstrip("@")
        if low and low.lower() not in {n.lower() for n in names}:
            names.append(low)
            cfg.set("Team", "usernames", ", ".join(names))
    save_team(cfg)


def operator_notifications() -> dict:
    from tg_bot import utils as tg_utils
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
    """Пускает в пульт и включает уведомления. True если человека только что добавили."""
    if tg is None or not user_id:
        return False
    added = user_id not in tg.authorized_users
    if added:
        tg.authorized_users[user_id] = {"username": (username or "").lstrip("@")}
        tg_utils.save_authorized_users(tg.authorized_users)
    elif username and not (tg.authorized_users.get(user_id) or {}).get("username"):
        tg.authorized_users[user_id]["username"] = username.lstrip("@")
        tg_utils.save_authorized_users(tg.authorized_users)
    chat = str(user_id)
    if chat not in tg.notification_settings:
        ensure_operator_notifications(tg, user_id)
    remember_id(user_id, username)
    if added:
        logger.info("[Team] оператор %s (@%s) добавлен", user_id, username or "—")
    return added


def username_allowed(username: str | None) -> bool:
    if not username:
        return False
    return username.lstrip("@").lower() in allowed_usernames()


def try_authorize_message(tg, m) -> bool:
    """Если пишет человек из списка @username / id — пускаем без пароля."""
    if tg is None or m is None or getattr(m.chat, "type", "") != "private":
        return False
    uid = m.from_user.id
    if uid in getattr(tg, "authorized_users", {}):
        return False
    uname = getattr(m.from_user, "username", None)
    if uid in extra_ids() or username_allowed(uname):
        grant_operator(tg, uid, uname)
        return True
    return False


def resolve_usernames(bot, already: set[str] | None = None) -> list[tuple[str, int]]:
    found = []
    have = {x.lower() for x in (already or set())}
    for name in sorted(allowed_usernames()):
        if name in have:
            continue
        try:
            chat = bot.get_chat(f"@{name}")
            uid = int(getattr(chat, "id", 0) or 0)
            if uid:
                found.append((name, uid))
        except Exception:
            logger.info("[Team] @%s ещё не писал боту — жду /menu", name)
    return found


def bootstrap(tg) -> None:
    if not tg or not getattr(tg, "bot", None):
        return
    for uid in extra_ids():
        grant_operator(tg, uid, None)
    have = set()
    for meta in (tg.authorized_users or {}).values():
        if isinstance(meta, dict) and meta.get("username"):
            have.add(str(meta["username"]).lstrip("@").lower())
    for name, uid in resolve_usernames(tg.bot, have):
        grant_operator(tg, uid, name)


def team_text(tg) -> str:
    users = getattr(tg, "authorized_users", {}) or {}
    lines = ["👥 <b>Команда пульта</b>\n"]
    if not users:
        lines.append("Пока никого. Владелец подхватится сам.")
    for uid, meta in users.items():
        nick = ""
        if isinstance(meta, dict):
            nick = meta.get("username") or ""
        tag = f"@{nick}" if nick else "без юза"
        lines.append(f"• {tag}  <code>{uid}</code>")
    pending = sorted(allowed_usernames())
    have = set()
    for meta in users.values():
        if isinstance(meta, dict) and meta.get("username"):
            have.add(str(meta["username"]).lstrip("@").lower())
    waiting = [n for n in pending if n not in have]
    if waiting:
        lines.append("\nЖдём в боте (напиши /menu): " + ", ".join(f"@{n}" for n in waiting))
    else:
        lines.append("\nНикого сверх списка не ждём. Добавь человека — он напишет /menu и войдёт без пароля.")
    lines.append("Добавить: <code>/op @username</code> или <code>/op 123456789</code> (только владелец).")
    return "\n".join(lines)
