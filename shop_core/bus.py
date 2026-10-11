# -*- coding: utf-8 -*-
from __future__ import annotations

import contextlib
import contextvars
import logging
import re
import threading
import time
from typing import Any

from shop_core.db import get_db
from shop_core.settings import is_dry_run, is_panic, load_ops

logger = logging.getLogger("FPC.Bus")
_USERS_RE = re.compile(r"^users-(\d+)-(\d+)$", re.I)

STATE_IDLE = "STATE_IDLE"
STATE_AI = "STATE_AI"
STATE_WAITING_INPUT = "STATE_WAITING_INPUT"
STATE_HUMAN_OPERATOR = "STATE_HUMAN_OPERATOR"
HUMAN_STALE_SEC = 86400

MSG_ORIGIN = contextvars.ContextVar("fp_msg_origin", default="human")

_LOCK = threading.RLock()
_CARDINAL = None
_BYPASS = threading.local()


@contextlib.contextmanager
def bypass_freeze():
    """Разовые запросы к FunPay в обход заморозки: проверка нового golden_key, проба сессии."""
    prev = getattr(_BYPASS, "on", False)
    _BYPASS.on = True
    try:
        yield
    finally:
        _BYPASS.on = prev


def freeze_bypassed() -> bool:
    return bool(getattr(_BYPASS, "on", False))


def bind_cardinal(cardinal) -> None:
    global _CARDINAL
    _CARDINAL = cardinal


def hydrate() -> None:
    with get_db() as conn:
        conn.execute("SELECT COUNT(*) FROM bus_chats")
        conn.execute("SELECT COUNT(*) FROM bus_flags")


def set_flag(key: str, value: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO bus_flags (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, time.time()),
        )


def get_flag(key: str, default: str | None = None) -> str | None:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM bus_flags WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def is_frozen() -> bool:
    if is_panic():
        return True
    return get_flag("freeze", "0") == "1"


def freeze(reason: str, cardinal=None) -> None:
    with _LOCK:
        if is_frozen() and get_flag("freeze") == "1":
            return
        set_flag("freeze", "1")
        set_flag("freeze_reason", reason)
    c = cardinal or _CARDINAL
    if c and getattr(c, "telegram", None):
        try:
            c.telegram.send_notification(
                f"🛑 <b>FREEZE MODE</b>\nПричина: <code>{reason}</code>\n"
                f"Опрос FunPay и автозакупки остановлены. /unfreeze после проверки сессии."
            )
        except Exception:
            pass


def unfreeze() -> None:
    set_flag("freeze", "0")
    set_flag("freeze_reason", "")
    if _CARDINAL is None or is_frozen():
        return

    def _resume():
        try:
            from shop_core.confirm import resume_pending
            resume_pending(_CARDINAL)
        except Exception as ex:
            logger.warning("[Bus] resume_pending: %s", ex)
        from shop_core import hooks
        hooks.emit("on_unfreeze", _CARDINAL)

    threading.Thread(target=_resume, daemon=True).start()


def deliveries_blocked() -> bool:
    return is_frozen() or is_panic() or is_dry_run() is None


def can_spend_money() -> tuple[bool, str]:
    if is_panic():
        return False, "panic"
    if is_frozen():
        return False, "freeze"
    if is_dry_run():
        return False, "dry_run"
    return True, "ok"


def as_chat_id(chat_id, account_id=None, peer_id=None) -> int | None:
    """Числовой ключ чата. FunPay в заказах даёт users-X-Y, в сообщениях — int."""
    if peer_id is not None:
        ps = str(peer_id).strip()
        if ps.lstrip("-").isdigit():
            return int(ps)
    if chat_id is None or isinstance(chat_id, bool):
        return None
    if isinstance(chat_id, int):
        return chat_id
    raw = str(chat_id).strip()
    if raw.lstrip("-").isdigit():
        return int(raw)
    m = _USERS_RE.fullmatch(raw)
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if account_id is not None:
        try:
            aid = int(account_id)
        except (TypeError, ValueError):
            aid = None
        if aid == a:
            return b
        if aid == b:
            return a
    return b if a != b else a


def remember_chat_alias(alias, peer_id: int) -> None:
    if alias is None or peer_id is None:
        return
    try:
        pid = int(peer_id)
    except (TypeError, ValueError):
        return
    if pid == 0:
        return
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO chat_aliases (alias, peer_id) VALUES (?, ?)",
            (str(alias), pid),
        )


def peer_ids(*cands, account_id=None) -> list[int]:
    """Числовые id чата и связанные покупатели из chat_aliases."""
    keys: list[int] = []
    aliases: list[str] = []
    for cand in cands:
        if cand is None or isinstance(cand, bool):
            continue
        n = resolve_peer(cand, account_id=account_id)
        if n is not None and n not in keys:
            keys.append(n)
        aliases.append(str(cand))
    if not aliases:
        return keys
    try:
        with get_db() as conn:
            q = ",".join("?" * len(aliases))
            rows = conn.execute(
                f"SELECT peer_id FROM chat_aliases WHERE alias IN ({q})",
                tuple(aliases),
            ).fetchall()
            for row in rows:
                pid = int(row["peer_id"])
                if pid not in keys:
                    keys.append(pid)
            back = []
            if keys:
                q = ",".join("?" * len(keys))
                back = conn.execute(
                    f"SELECT alias FROM chat_aliases WHERE peer_id IN ({q})",
                    tuple(keys),
                ).fetchall()
        sides: set[str] = set()
        nodes: list[int] = []
        for row in back:
            alias = str(row["alias"])
            pair = _USERS_RE.fullmatch(alias)
            if pair:
                sides.add(pair.group(1))
                sides.add(pair.group(2))
                continue
            if alias.lstrip("-").isdigit():
                nodes.append(int(alias))
        for node in nodes:
            if str(node) in sides or node in keys:
                continue
            keys.append(node)
    except Exception:
        pass
    return keys


def resolve_peer(chat_id, account_id=None, peer_id=None) -> int | None:
    n = as_chat_id(chat_id, account_id=account_id, peer_id=peer_id)
    if n is not None:
        return n
    if chat_id is None:
        return None
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT peer_id FROM chat_aliases WHERE alias = ?", (str(chat_id),)
            ).fetchone()
        return int(row["peer_id"]) if row else None
    except Exception:
        return None


def bind_order_chat(chat_id, account_id=None, peer_id=None) -> int | None:
    """Сохраняет users-X-Y ↔ buyer_id и возвращает ключ для SQLite."""
    cid = as_chat_id(chat_id, account_id=account_id, peer_id=peer_id)
    if cid is None:
        return None
    remember_chat_alias(chat_id, cid)
    remember_chat_alias(cid, cid)
    if peer_id is not None:
        remember_chat_alias(peer_id, cid)
    m = _USERS_RE.fullmatch(str(chat_id).strip()) if chat_id is not None else None
    if m:
        remember_chat_alias(m.group(1), cid)
        remember_chat_alias(m.group(2), cid)
        remember_chat_alias(f"users-{m.group(1)}-{m.group(2)}", cid)
    return cid


def get_chat_state(chat_id) -> str:
    ids = peer_ids(chat_id)
    if not ids:
        return STATE_IDLE
    with get_db() as conn:
        q = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT state, updated_at FROM bus_chats WHERE chat_id IN ({q})", tuple(ids)
        ).fetchall()
    now = time.time()
    states = set()
    for row in rows:
        state = row["state"]
        if state == STATE_HUMAN_OPERATOR and now - float(row["updated_at"] or 0) > HUMAN_STALE_SEC:
            continue
        states.add(state)
    if STATE_HUMAN_OPERATOR in states:
        return STATE_HUMAN_OPERATOR
    if STATE_WAITING_INPUT in states:
        return STATE_WAITING_INPUT
    if STATE_AI in states:
        return STATE_AI
    return STATE_IDLE


def set_chat_state(chat_id, state: str, order_id: str | None = None, waiting: bool = False) -> None:
    cid = resolve_peer(chat_id)
    if cid is None:
        logger.warning("[Bus] set_chat_state: не разобрал chat_id=%r", chat_id)
        return
    with get_db() as conn:
        prev = conn.execute(
            "SELECT state, updated_at FROM bus_chats WHERE chat_id = ?", (cid,)
        ).fetchone()
        fresh_human = (
            prev
            and prev["state"] == STATE_HUMAN_OPERATOR
            and time.time() - float(prev["updated_at"] or 0) <= HUMAN_STALE_SEC
        )
        if fresh_human and state != STATE_IDLE:
            return
        conn.execute(
            """INSERT OR REPLACE INTO bus_chats (chat_id, state, waiting_input, order_id, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (cid, state, 1 if waiting else 0, order_id, time.time()),
        )


def mark_human(chat_id, order_id: str | None = None) -> None:
    cid = resolve_peer(chat_id)
    if cid is None:
        return
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO bus_chats (chat_id, state, waiting_input, order_id, updated_at)
               VALUES (?, ?, 0, ?, ?)""",
            (cid, STATE_HUMAN_OPERATOR, order_id, time.time()),
        )


def is_human(chat_id) -> bool:
    return get_chat_state(chat_id) == STATE_HUMAN_OPERATOR


def release_chat(chat_id) -> None:
    cid = resolve_peer(chat_id)
    if cid is None:
        return
    with get_db() as conn:
        conn.execute(
            "UPDATE bus_chats SET state = ?, waiting_input = 0, updated_at = ? WHERE chat_id = ?",
            (STATE_IDLE, time.time(), cid),
        )


def is_chat_muted(chat_id) -> bool:
    ids = peer_ids(chat_id)
    if not ids:
        return False
    now = time.time()
    with get_db() as conn:
        q = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT expire_time FROM muted_chats WHERE chat_id IN ({q})", tuple(ids)
        ).fetchall()
    return any(row["expire_time"] > now for row in rows)


def set_chat_mute(chat_id, duration_sec: int = 90) -> None:
    cid = resolve_peer(chat_id)
    if cid is None:
        return
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO muted_chats (chat_id, expire_time) VALUES (?, ?)",
            (cid, time.time() + int(duration_sec)),
        )


def bot_send(cardinal, chat_id, text: str, chat_name: str | None = None) -> Any:
    token = MSG_ORIGIN.set("bot")
    try:
        return cardinal.send_message(chat_id, text, chat_name, watermark=False)
    finally:
        MSG_ORIGIN.reset(token)


def quiet_hours_now() -> bool:
    cfg = load_ops()
    if not cfg.getboolean("Ops", "quiet_enabled", fallback=True):
        return False
    frm = cfg.get("Ops", "quiet_from", fallback="01:00")
    to = cfg.get("Ops", "quiet_to", fallback="09:00")
    now = time.strftime("%H:%M")
    if frm <= to:
        return frm <= now < to
    return now >= frm or now < to


def notify(cardinal, text: str, critical: bool = False, keyboard=None) -> None:
    tg = getattr(cardinal, "telegram", None)
    if not tg:
        return
    if quiet_hours_now() and not critical:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO notify_digest (text, created_at) VALUES (?, ?)",
                (text, time.time()),
            )
        return
    ntype = "13" if critical else "10"  # NotificationTypes.critical / other
    try:
        tg.send_notification(text, keyboard=keyboard, notification_type=ntype)
    except TypeError:
        try:
            tg.send_notification(text, notification_type=ntype)
        except TypeError:
            tg.send_notification(text)


def drain_digest(cardinal) -> None:
    with get_db() as conn:
        rows = conn.execute("SELECT id, text FROM notify_digest ORDER BY id ASC").fetchall()
        conn.execute("DELETE FROM notify_digest")
    if not rows:
        return
    blob = "🌅 <b>Утренний дайджест</b>\n\n" + "\n\n".join(r["text"] for r in rows[-30:])
    notify(cardinal, blob, critical=True)
