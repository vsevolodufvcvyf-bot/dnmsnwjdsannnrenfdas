# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import time

from FunPayAPI.common.enums import OrderStatuses
from shop_core.bus import can_spend_money, notify
from shop_core.db import get_db
from shop_core.rate_limit import SUPPLIER_BUCKET
from shop_core.settings import commission, is_dry_run

logger = logging.getLogger("FPC.Finance")


DELIVERY_LOCK = "__delivery__"


def claim_order(order_id: str, plugin_name: str) -> bool:
    """True if this process won the first claim for this plugin (autoback etc.)."""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO processed_orders (order_id, plugin_name, processed_at) VALUES (?, ?, ?)",
            (str(order_id), plugin_name, time.time()),
        )
        return cur.rowcount > 0


def claim_delivery(order_id: str, plugin_name: str) -> bool:
    """Один заказ — одна закупка. Автовозврат этот замок не использует."""
    now = time.time()
    oid = str(order_id)
    with get_db() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO processed_orders (order_id, plugin_name, processed_at) VALUES (?, ?, ?)",
            (oid, DELIVERY_LOCK, now),
        )
        if cur.rowcount <= 0:
            return False
        conn.execute(
            "INSERT OR REPLACE INTO processed_orders (order_id, plugin_name, processed_at) VALUES (?, ?, ?)",
            (oid, plugin_name, now),
        )
        return True


def release_claim(order_id: str, plugin_name: str) -> None:
    with get_db() as conn:
        conn.execute(
            "DELETE FROM processed_orders WHERE order_id = ? AND plugin_name = ?",
            (str(order_id), plugin_name),
        )


def release_delivery(order_id: str, plugin_name: str | None = None) -> None:
    oid = str(order_id)
    with get_db() as conn:
        conn.execute(
            "DELETE FROM processed_orders WHERE order_id = ? AND plugin_name = ?",
            (oid, DELIVERY_LOCK),
        )
        if plugin_name:
            conn.execute(
                "DELETE FROM processed_orders WHERE order_id = ? AND plugin_name = ?",
                (oid, plugin_name),
            )


def already_processed(order_id: str, plugin_name: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_orders WHERE order_id = ? AND plugin_name = ?",
            (str(order_id), plugin_name),
        ).fetchone()
        return bool(row)


def log_finance(order_id: str, plugin_name: str, sale_price: float, cost: float, currency: str = "RUB"):
    profit = float(sale_price or 0) - float(cost or 0)
    with get_db() as conn:
        conn.execute(
            """INSERT INTO finance_log (order_id, plugin_name, sale_price, cost, profit, currency, dry_run, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(order_id), plugin_name, sale_price, cost, profit, currency, 1 if is_dry_run() else 0, time.time()),
        )


def order_is_paid(cardinal, order_id: str) -> bool:
    return order_pay_state(cardinal, order_id)[0] == "paid"


def order_pay_state(cardinal, order_id: str) -> tuple[str, str]:
    oid = str(order_id).lstrip("#")
    try:
        order = cardinal.account.get_order(oid)
    except Exception as ex:
        logger.warning("[Finance] preflight get_order failed: %s", ex)
        err = str(ex).lower()
        if any(x in err for x in (
            "502", "503", "timeout", "timed out", "connection", "429",
            "401", "403", "unauthorized", "frozen", "captcha",
        )):
            return "network", str(ex)[:160]
        from FunPayAPI.common.exceptions import RequestFailedError
        if isinstance(ex, RequestFailedError):
            return "network", str(ex)[:160]
        return "unknown", str(ex)[:160]
    status = getattr(order, "status", None)
    if status == OrderStatuses.PAID:
        return "paid", "paid"
    return "not_paid", str(getattr(status, "name", status) or "not_paid")


def preflight_or_abort(cardinal, order_id: str, plugin_name: str) -> tuple[bool, str]:
    ok, why = can_spend_money()
    if not ok:
        return False, why
    from shop_core.settings import load_ops
    if not load_ops().getboolean("Ops", "preflight_enabled", fallback=True):
        return True, "skip"
    state, detail = order_pay_state(cardinal, order_id)
    if state == "paid":
        return True, "paid"
    if state == "network":
        notify(cardinal, f"⚠️ Pre-flight #{order_id}: FunPay не ответил ({detail}). {plugin_name} подождёт повтор.", True)
        return False, "network"
    notify(cardinal, f"⛔ Pre-flight: заказ #{order_id} больше не PAID ({detail}). {plugin_name} закупку отменил.", True)
    return False, "not_paid"


def margin_ok(sale_price: float, cost: float) -> bool:
    from shop_core.settings import min_margin_mult
    net = float(sale_price or 0) * (1.0 - commission())
    need = float(cost or 0) * min_margin_mult()
    return net + 1e-9 >= need


def deactivate_lot_safe(cardinal, lot_id: int, reason: str) -> None:
    try:
        fields = cardinal.account.get_lot_fields(lot_id)
        if fields.active:
            fields.active = False
            cardinal.account.save_lot(fields)
        notify(cardinal, f"📉 Price Guard: лот {lot_id} выключен.\n{reason}", True)
    except Exception as ex:
        logger.error("[Finance] lot deactivate failed: %s", ex)


def supplier_post(session_post, url: str, data: dict, timeout: float = 12.0):
    if not SUPPLIER_BUCKET.acquire():
        raise TimeoutError("supplier rate-limit")
    return session_post(url, data=data, timeout=timeout)
