# -*- coding: utf-8 -*-
"""Поднимает лоты в часы, когда их реально покупают, а не круглосуточно."""
from __future__ import annotations

import html
import logging
import time
from datetime import datetime, timedelta

from shop_core.db import get_db
from shop_core.plugin_settings import SettingsPage
from shop_core.settings import ini_bool, set_ini

logger = logging.getLogger("FPC.RaiseClock")

NAME = "Часы поднятия"
VERSION = "1.0.0"
DESCRIPTION = "Запоминает час заказа и поднимает лоты только в живые часы"
CREDITS = "nnanserShop"
UUID = "f3a91c20-6d4e-4b71-8c55-2e7a9b1d4f60"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}

CONFIG_FILE = "configs/raise_clock.cfg"
MIN_ORDERS = 12
MIN_DAY_ORDERS = 8
LOOKBACK_SEC = 30 * 86400
BOOTSTRAP = set(range(11, 24))
DAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_WEEKDAY_SQL = "COALESCE(weekday, (CAST(strftime('%w', created_at, 'unixepoch', 'localtime') AS INTEGER) + 6) % 7)"


def _enabled() -> bool:
    return ini_bool(CONFIG_FILE, "RaiseClock", "enabled", True)


def hours_from_counts(counts: dict[int, int], min_orders: int = MIN_ORDERS) -> tuple[set[int], str]:
    """Часы, в которые имеет смысл поднимать. Мало данных — день 11:00–23:59, не ночь."""
    total = sum(int(n) for n in counts.values())
    if total < min_orders:
        return set(BOOTSTRAP), f"заказов пока {total}, поднимаю 11:00–23:59"
    avg = total / 24.0
    hot = {h for h in range(24) if counts.get(h, 0) > 0 and counts.get(h, 0) >= avg}
    if not hot:
        ranked = sorted(range(24), key=lambda h: counts.get(h, 0), reverse=True)
        hot = {h for h in ranked[:4] if counts.get(h, 0) > 0}
    if len(hot) <= 10:
        use = set()
        for h in hot:
            use.update({(h - 1) % 24, h, (h + 1) % 24})
    else:
        use = set(hot)
    return use, f"по {total} заказам: {format_hours(use)}"


def format_hours(hours: set[int]) -> str:
    if not hours:
        return "нет окна"
    seq = sorted(hours)
    ranges = []
    start = prev = seq[0]
    for h in seq[1:]:
        if h == prev + 1:
            prev = h
            continue
        ranges.append((start, prev))
        start = prev = h
    ranges.append((start, prev))
    parts = []
    for a, b in ranges:
        if a == b:
            parts.append(f"{a:02d}:00")
        else:
            parts.append(f"{a:02d}:00–{b:02d}:59")
    return ", ".join(parts)


def seconds_until(hours: set[int], now: datetime | None = None) -> int:
    now = now or datetime.now()
    if now.hour in hours:
        return 0
    for add in range(1, 25):
        if (now.hour + add) % 24 in hours:
            target = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=add)
            return max(60, int((target - now).total_seconds()))
    return 600


def _counts(weekday: int | None = None) -> dict[int, int]:
    since = time.time() - LOOKBACK_SEC
    sql = "SELECT hour, COUNT(*) AS n FROM sale_clock WHERE created_at >= ?"
    args: tuple = (since,)
    if weekday is not None:
        sql += f" AND {_WEEKDAY_SQL} = ?"
        args = (since, int(weekday))
    with get_db() as conn:
        rows = conn.execute(sql + " GROUP BY hour", args).fetchall()
    return {int(r["hour"]): int(r["n"]) for r in rows}


def plan(now: datetime | None = None) -> tuple[set[int], str]:
    if not _enabled():
        return set(range(24)), "часы выключены — поднимаю когда FunPay разрешит"
    day = (now or datetime.now()).weekday()
    by_day = _counts(day)
    if sum(by_day.values()) >= MIN_DAY_ORDERS:
        hours, why = hours_from_counts(by_day, MIN_DAY_ORDERS)
        return hours, f"{DAYS[day]}: {why}"
    return hours_from_counts(_counts())


def raise_decision(now: datetime | None = None) -> tuple[bool, str, int]:
    """Можно поднимать сейчас, пояснение, сколько секунд спать если нельзя."""
    hours, why = plan(now)
    moment = now or datetime.now()
    if moment.hour in hours:
        return True, why, 0
    return False, f"сейчас не час покупок ({why})", min(600, seconds_until(hours, moment))


_DECISION_CACHE: dict[str, tuple[float, tuple[bool, str, int]]] = {}
_DECISION_TTL = 60.0


def raise_decision_cached() -> tuple[bool, str, int]:
    """Цикл поднятия спрашивает каждые 5 секунд; план по базе пересчитываем раз в минуту."""
    now = time.time()
    hit = _DECISION_CACHE.get("plan")
    if hit and now - hit[0] < _DECISION_TTL:
        return hit[1]
    res = raise_decision()
    _DECISION_CACHE["plan"] = (now, res)
    return res


def note_order(order_id: str, when: float | None = None) -> None:
    oid = str(order_id or "").lstrip("#")
    if not oid or oid.upper() == "ADTEST":
        return
    ts = float(when if when is not None else time.time())
    moment = datetime.fromtimestamp(ts)
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sale_clock (order_id, hour, created_at, weekday) VALUES (?, ?, ?, ?)",
            (oid, moment.hour, ts, moment.weekday()),
        )
        conn.execute("DELETE FROM sale_clock WHERE created_at < ?", (time.time() - LOOKBACK_SEC,))


def status_line() -> str:
    hours, why = plan()
    return "Поднятие лотов: " + why


def chart_lines(counts: dict[int, int], active: set[int] | None = None, width: int = 10) -> list[str]:
    peak = max((int(n) for n in counts.values()), default=0)
    lines = []
    for hour in range(24):
        n = int(counts.get(hour, 0))
        filled = int(round(width * n / peak)) if peak and n else 0
        mark = "●" if active and hour in active else "·"
        lines.append(f"{mark}{hour:02d} {'█' * filled}{'░' * (width - filled)} {n}")
    return lines


def demand_text() -> str:
    counts = _counts()
    hours, why = plan()
    lines = ["🕐 <b>Когда покупают</b>", html.escape(why), ""]
    total = sum(int(n) for n in counts.values())
    if not total:
        lines.append("Заказов за 30 дней ещё нет. Пока лоты поднимаются с 11:00 до 23:59, не ночью.")
        return "\n".join(lines)
    chart = "\n".join(chart_lines(counts, hours))
    lines.append("<pre>" + html.escape(chart) + "</pre>")
    top = sorted(((h, int(n)) for h, n in counts.items() if n), key=lambda item: item[1], reverse=True)[:3]
    if top:
        tops = ", ".join(f"{h:02d}:00 — {n}" for h, n in top)
        lines.append("Чаще всего: " + html.escape(tops))
    lines.append("Точка слева — час, когда лоты поднимаются. Ночью подъёма нет, если ночью не покупают.")
    return "\n".join(lines)


def seed_history(cardinal) -> None:
    """Один раз, если часов ещё нет: первая страница закрытых продаж, не больше 50."""
    try:
        from shop_core.bus import is_frozen
        if is_frozen():
            return
        with get_db() as conn:
            n = conn.execute("SELECT COUNT(*) AS c FROM sale_clock").fetchone()["c"]
        if n:
            return
        acc = getattr(cardinal, "account", None)
        if not acc or not getattr(acc, "is_initiated", False):
            return
        _next, orders, *_rest = acc.get_sales(
            include_paid=True, include_closed=True, include_refunded=False,
        )
        saved = 0
        for order in (orders or [])[:50]:
            oid = getattr(order, "id", None)
            when = getattr(order, "date", None)
            ts = when.timestamp() if hasattr(when, "timestamp") else None
            if not oid or ts is None:
                continue
            note_order(str(oid), ts)
            saved += 1
        if saved:
            logger.info("[RaiseClock] из истории FunPay взято заказов: %s", saved)
    except Exception as ex:
        logger.debug("[RaiseClock] seed: %s", ex)


def on_order(cardinal, event):
    try:
        order = getattr(event, "order", None)
        oid = getattr(order, "id", None) if order else None
        if oid:
            when = getattr(order, "date", None)
            ts = when.timestamp() if hasattr(when, "timestamp") else None
            note_order(str(oid), ts)
            from shop_core.dossier import note_seen
            note_seen(
                str(oid),
                getattr(order, "buyer_username", "") or "",
                getattr(order, "price", 0) or 0,
                getattr(order, "description", "") or "",
                ts,
                getattr(order, "currency", "") or "",
            )
    except Exception as ex:
        logger.debug("[RaiseClock] order: %s", ex)


def init_settings(cardinal):
    from shop_core import hooks
    hooks.provide("raise_gate", raise_decision_cached)
    SettingsPage(UUID, NAME, "Лоты поднимаются в часы, когда их покупали за 30 дней. Ночью — нет.") \
        .add_toggle(
            "enabled", "Часы поднятия", _enabled,
            lambda _v: set_ini(CONFIG_FILE, "RaiseClock", "enabled", "0" if _enabled() else "1"),
        ) \
        .set_status(status_line) \
        .attach(cardinal)


BIND_TO_PRE_INIT = [init_settings]
BIND_TO_POST_INIT = [seed_history]
BIND_TO_NEW_ORDER = [on_order]
