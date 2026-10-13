# -*- coding: utf-8 -*-
"""Очередь оператора: покупатель зовёт человека, сработал фильтр ответа или ошибка поставщика."""
from __future__ import annotations

import html
import re
import time

from shop_core.db import get_db

REASONS = {
    "human": "человек",
    "sanitizer": "фильтр",
    "supplier": "поставщик",
}
_SECRET = re.compile(
    r"(?i)\b(api_key|apikey|key|token|golden_key|password|shared_secret)\b\s*[:=]\s*\S+"
)


def clip_detail(detail: str) -> str:
    text = _SECRET.sub(lambda m: f"{m.group(1)}=•••", (detail or "").replace("\n", " "))
    return text.strip()[:300]


def enqueue(chat_id, order_id, reason: str, detail: str = "", account_id=None) -> int:
    """Кладёт или обновляет открытую запись. Один чат + заказ + причина — одна строка."""
    code = reason if reason in REASONS else "human"
    cid = _peer(chat_id, account_id)
    oid = str(order_id or "").lstrip("#") or None
    text = clip_detail(detail)
    now = time.time()
    with get_db() as conn:
        row = conn.execute(
            """SELECT id FROM needs_human
               WHERE status = 'open' AND reason = ?
                 AND IFNULL(order_id, '') = IFNULL(?, '')
                 AND IFNULL(chat_id, -1) = IFNULL(?, -1)""",
            (code, oid, cid),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE needs_human SET detail = ?, created_at = ? WHERE id = ?",
                (text, now, int(row["id"])),
            )
            return int(row["id"])
        cur = conn.execute(
            """INSERT INTO needs_human (chat_id, order_id, reason, detail, status, created_at)
               VALUES (?, ?, ?, ?, 'open', ?)""",
            (cid, oid, code, text, now),
        )
        return int(cur.lastrowid)


def resolve_item(item_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            """UPDATE needs_human SET status = 'done', resolved_at = ?
               WHERE id = ? AND status = 'open'""",
            (time.time(), int(item_id)),
        )
        return cur.rowcount > 0


def open_count() -> int:
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM needs_human WHERE status = 'open'"
        ).fetchone()
    return int(row["c"] or 0)


def open_items(limit: int = 20):
    with get_db() as conn:
        return conn.execute(
            """SELECT id, chat_id, order_id, reason, detail, created_at
               FROM needs_human WHERE status = 'open'
               ORDER BY created_at ASC LIMIT ?""",
            (max(1, int(limit)),),
        ).fetchall()


def queue_text(rows) -> str:
    if not rows:
        return (
            "🚨 <b>Очередь оператора</b>\n"
            "Пусто. Сюда попадают вызов человека, срабатывание фильтра ответа и ошибка поставщика."
        )
    lines = [
        "🚨 <b>Очередь оператора</b>",
        "Покупатель зовёт человека, фильтр режет ответ или панель вернула ошибку.",
        "",
    ]
    for row in rows:
        label = REASONS.get(str(row["reason"]), str(row["reason"]))
        bits = [f"#{int(row['id'])} · {label}"]
        if row["order_id"]:
            oid = html.escape(str(row["order_id"]))
            bits.append(f"<a href=\"https://funpay.com/orders/{oid}/\">заказ #{oid}</a>")
        if row["chat_id"] is not None:
            bits.append(f"чат <code>{int(row['chat_id'])}</code>")
        age = _age(row["created_at"])
        if age:
            bits.append(age)
        lines.append("• " + " · ".join(bits))
        if row["detail"]:
            lines.append(f"  {html.escape(str(row['detail'])[:180])}")
    return "\n".join(lines)


def _age(created_at) -> str:
    try:
        mins = int((time.time() - float(created_at or 0)) // 60)
    except (TypeError, ValueError):
        return ""
    if mins < 1:
        return "только что"
    if mins < 60:
        return f"{mins} мин"
    return f"{mins // 60} ч {mins % 60} мин"


def _peer(chat_id, account_id):
    if chat_id is None:
        return None
    try:
        from shop_core.bus import resolve_peer
        return resolve_peer(chat_id, account_id=account_id)
    except Exception:
        try:
            return int(chat_id)
        except (TypeError, ValueError):
            return None
