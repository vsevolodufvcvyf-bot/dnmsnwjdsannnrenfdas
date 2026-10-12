# -*- coding: utf-8 -*-
"""Цель по чистой прибыли за календарный день. Учебные сделки в неё не входят."""
from __future__ import annotations

import time
from datetime import datetime

from shop_core.db import get_db
from shop_core.settings import OPS_FILE, load_ops, set_ini

_MAX_GOAL = 10_000_000.0


def day_start(now: float | None = None) -> float:
    moment = datetime.fromtimestamp(now if now is not None else time.time())
    return datetime(moment.year, moment.month, moment.day).timestamp()


def daily_target() -> float:
    try:
        value = float(load_ops().get("Goal", "daily_profit", fallback="0") or 0)
    except (TypeError, ValueError):
        return 0.0
    if value < 0 or value > _MAX_GOAL:
        return 0.0
    return value


def set_daily_target(amount: float) -> None:
    value = float(amount)
    if value < 0 or value > _MAX_GOAL:
        raise ValueError("goal out of range")
    set_ini(OPS_FILE, "Goal", "daily_profit", f"{value:.2f}")


def today_totals(now: float | None = None) -> tuple[float, float, float, int]:
    """Оборот, закупка, чистыми, число сделок с полуночи. dry_run не считается."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(sale_price),0), COALESCE(SUM(cost),0),
                      COALESCE(SUM(profit),0), COUNT(*)
               FROM finance_log WHERE created_at >= ? AND dry_run = 0""",
            (day_start(now),),
        ).fetchone()
    sales, cost, profit, n = row
    return float(sales), float(cost), float(profit), int(n)


def bar(current: float, target: float, width: int = 10) -> str:
    if target <= 0:
        return "░" * width
    ratio = max(0.0, min(1.0, float(current) / float(target)))
    filled = int(round(ratio * width))
    return "█" * filled + "░" * (width - filled)


def goal_line(profit: float | None = None) -> str:
    target = daily_target()
    if profit is None:
        profit = today_totals()[2]
    if target <= 0:
        return "🎯  цель не задана · <code>/goal 3000</code>"
    pct = int(round(max(0.0, float(profit)) / target * 100))
    return f"🎯  {float(profit):.0f} / {target:.0f} ₽   {bar(profit, target)}  {pct}%"


def goal_help() -> str:
    target = daily_target()
    if target > 0:
        state = f"Цель на сегодня: <b>{target:.0f}</b> ₽ чистыми."
    else:
        state = "Цель не задана — шкала на главной появится, как только укажешь сумму."
    return (
        "🎯 <b>Цель на день</b>\n"
        f"{goal_line()}\n\n"
        f"{state}\n"
        "Считаются только настоящие сделки с полуночи. Учебный режим в цифру не входит.\n\n"
        "Поставить: <code>/goal 3000</code>\n"
        "Убрать: <code>/goal 0</code>"
    )


def parse_goal(text: str) -> tuple[str, float | None]:
    """('show', None) — без суммы, ('set', число), ('bad', None) — не разобрали."""
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return "show", None
    raw = parts[1].strip().lower().replace(" ", "").replace("₽", "").replace("руб.", "").replace("руб", "")
    raw = raw.replace(",", ".")
    if raw in ("0", "off", "нет", "сброс"):
        return "set", 0.0
    try:
        value = float(raw)
    except ValueError:
        return "bad", None
    if value < 0 or value > _MAX_GOAL:
        return "bad", None
    return "set", value
