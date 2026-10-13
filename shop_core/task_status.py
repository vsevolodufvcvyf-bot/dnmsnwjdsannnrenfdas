# -*- coding: utf-8 -*-
"""Карточка задачи поставщика: что показать в Telegram и кнопка action=status."""
from __future__ import annotations

import html
import time

from shop_core.db import get_db

_FIELDS = (
    ("status", "Статус"),
    ("remains", "Осталось"),
    ("start_count", "Стартовый счётчик"),
    ("charge", "Списано"),
    ("currency", "Валюта"),
    ("refund", "Возврат на баланс"),
    ("refunded", "Возврат на баланс"),
    ("balance", "Баланс панели"),
    ("error", "Ошибка"),
)


def remember_task(order_id: str, plugin_name: str, provider: str, task_id: str,
                  status: str = "success") -> int:
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO supplier_orders
               (order_id, plugin_name, provider, task_id, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(order_id), plugin_name, provider or "", str(task_id), status, time.time()),
        )
        row = conn.execute(
            "SELECT rowid AS rid FROM supplier_orders WHERE order_id = ? AND plugin_name = ?",
            (str(order_id), plugin_name),
        ).fetchone()
    return int(row["rid"]) if row else 0


def recent_task_count(hours: float = 24) -> int:
    since = time.time() - float(hours) * 3600
    with get_db() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS c FROM supplier_orders
               WHERE plugin_name != 'restock' AND created_at >= ?""",
            (since,),
        ).fetchone()
    return int(row["c"] or 0)


def status_keyboard(rowid: int):
    from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
    kb = K()
    if int(rowid or 0) > 0:
        kb.row(B("🔎 Статус задачи", callback_data=f"SHOP:st:{int(rowid)}"))
    return kb


def format_task_status(task_id: str, section: str, data) -> str:
    """Текст по ответу action=status. Неизвестные поля не выдумываются."""
    parts = [f"🔎 Задача <code>{html.escape(str(task_id))}</code> [{html.escape(section or '—')}]"]
    if not isinstance(data, dict):
        parts.append(f"Ответ панели: <code>{html.escape(str(data)[:300])}</code>")
        return "\n".join(parts)
    progress = _progress(data)
    if progress:
        parts.append(progress)
    shown = set()
    for key, label in _FIELDS:
        if key in shown or data.get(key) in (None, ""):
            continue
        shown.add(key)
        parts.append(f"{label}: <code>{html.escape(str(data.get(key)))}</code>")
    status = str(data.get("status") or "").lower()
    if any(word in status for word in ("cancel", "partial", "refund")) and "refund" not in data and "refunded" not in data:
        parts.append("Статус с частичным или отменённым заказом: остаток панель обычно возвращает на свой баланс. Точной суммы в ответе нет.")
    if len(parts) == 1:
        parts.append(f"Ответ: <code>{html.escape(str(data)[:300])}</code>")
    return "\n".join(parts)


def _progress(data: dict) -> str:
    remains = data.get("remains")
    if remains in (None, ""):
        return ""
    start = data.get("start_count")
    if start in (None, ""):
        return f"Прогресс: осталось <code>{html.escape(str(remains))}</code>"
    return (
        f"Прогресс: стартовый счётчик <code>{html.escape(str(start))}</code>, "
        f"осталось добить <code>{html.escape(str(remains))}</code>"
    )
