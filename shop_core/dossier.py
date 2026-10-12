# -*- coding: utf-8 -*-
"""Память о покупателе: сколько уже брал и были ли возвраты. Секретов сюда не пишем."""
from __future__ import annotations

import html
import time

from shop_core.db import get_db


def _cur(value) -> str:
    if value is None or value == "":
        return "₽"
    name = getattr(value, "name", None)
    text = str(name or value).strip()
    upper = text.upper()
    if upper in ("RUB", "RUR", "₽"):
        return "₽"
    if upper == "USD":
        return "$"
    if upper == "EUR":
        return "€"
    return text[:8] or "₽"


def _ago(ts: float, now: float | None = None) -> str:
    delta = max(0, int((now if now is not None else time.time()) - float(ts)))
    if delta < 3600:
        return f"{max(1, delta // 60)} мин назад"
    if delta < 86400:
        return f"{delta // 3600} ч назад"
    return f"{delta // 86400} дн назад"


def note_seen(
    order_id: str,
    buyer: str,
    price: float = 0,
    description: str = "",
    when: float | None = None,
    currency: str = "",
) -> None:
    oid = str(order_id or "").lstrip("#").strip()
    name = " ".join(str(buyer or "").split())
    if not oid or not name or oid.upper() == "ADTEST":
        return
    try:
        amount = float(price or 0)
    except (TypeError, ValueError):
        amount = 0.0
    ts = float(time.time() if when is None else when)
    desc = " ".join(str(description or "").split())[:180]
    with get_db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO buyer_seen
               (order_id, buyer, price, currency, description, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (oid, name, amount, _cur(currency), desc, ts),
        )


def summary(buyer: str) -> dict:
    name = " ".join(str(buyer or "").split())
    empty = {"orders": 0, "spent": None, "currency": "", "prev_ago": "", "refunds": 0}
    if not name:
        return empty
    with get_db() as conn:
        rows = conn.execute(
            """SELECT price, currency, created_at FROM buyer_seen
               WHERE lower(buyer) = lower(?) ORDER BY created_at""",
            (name,),
        ).fetchall()
        refunds = conn.execute(
            "SELECT COUNT(*) FROM autoback_log WHERE lower(buyer_name) = lower(?)",
            (name,),
        ).fetchone()[0]
    if not rows and not refunds:
        return empty
    curs = {(r["currency"] or "₽") for r in rows}
    spent = sum(float(r["price"] or 0) for r in rows) if len(curs) == 1 and rows else None
    prev_ago = _ago(float(rows[-2]["created_at"])) if len(rows) >= 2 else ""
    return {
        "orders": len(rows),
        "spent": spent,
        "currency": next(iter(curs)) if len(curs) == 1 else "",
        "prev_ago": prev_ago,
        "refunds": int(refunds or 0),
    }


def dossier_block(buyer: str) -> str:
    """Короткий блок к уведомлению о заказе. Текущий заказ уже должен быть записан."""
    info = summary(buyer)
    n = info["orders"]
    refunds = info["refunds"]
    if n <= 0 and not refunds:
        return "👤 В журнале бота этого покупателя ещё не было."
    if n <= 1 and not refunds:
        return "👤 Первый заказ этого покупателя в журнале бота."
    line = f"👤 В журнале бота: <b>{n}</b> зак."
    if info["spent"] is not None:
        line += f" на <b>{info['spent']:.0f}</b> {html.escape(info['currency'] or '₽')}"
    if info["prev_ago"]:
        line += f" · прошлый {html.escape(info['prev_ago'])}"
    if refunds:
        line += f"\n⚠️ Возвратов этому покупателю: <b>{refunds}</b>"
    return line
