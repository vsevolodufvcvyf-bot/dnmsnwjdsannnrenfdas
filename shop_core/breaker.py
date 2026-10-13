# -*- coding: utf-8 -*-
"""Временный уход с панели поставщика после серии 402/502/503 и таймаутов.

Выдачу не останавливает: открытая панель уходит в конец списка, запасная пробуется первой.
"""
from __future__ import annotations

import threading
import time
from typing import Any

FAIL_STREAK = 3
OPEN_FOR = 15 * 60
_LOCK = threading.Lock()
_FAILS: dict[str, int] = {}
_OPEN_UNTIL: dict[str, float] = {}


def reset() -> None:
    with _LOCK:
        _FAILS.clear()
        _OPEN_UNTIL.clear()


def panel_key(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def is_open(url: str, now: float | None = None) -> bool:
    now = time.time() if now is None else float(now)
    key = panel_key(url)
    if not key:
        return False
    with _LOCK:
        return float(_OPEN_UNTIL.get(key, 0) or 0) > now


def note_success(url: str) -> None:
    key = panel_key(url)
    if not key:
        return
    with _LOCK:
        _FAILS.pop(key, None)
        _OPEN_UNTIL.pop(key, None)


def note_failure(url: str, now: float | None = None) -> bool:
    """True — серия только что открыла паузу."""
    key = panel_key(url)
    if not key:
        return False
    now = time.time() if now is None else float(now)
    with _LOCK:
        if float(_OPEN_UNTIL.get(key, 0) or 0) > now:
            return False
        fails = int(_FAILS.get(key, 0)) + 1
        if fails >= FAIL_STREAK:
            _FAILS[key] = 0
            _OPEN_UNTIL[key] = now + OPEN_FOR
            return True
        _FAILS[key] = fails
        return False


def counts_as_outage(status_code: int | None = None, exc: BaseException | None = None) -> bool:
    if status_code in (402, 502, 503):
        return True
    if exc is None:
        return False
    blob = f"{type(exc).__name__} {exc}".lower()
    return "timeout" in blob or "timed out" in blob


def prefer_healthy(panels: list[dict[str, Any]], now: float | None = None) -> list[dict[str, Any]]:
    """Живые панели в прежнем порядке, открытые — в конце. Если живых нет, список не режется."""
    healthy, paused = [], []
    for panel in panels or []:
        if is_open(str(panel.get("api_url") or ""), now):
            paused.append(panel)
        else:
            healthy.append(panel)
    if not healthy:
        return list(panels or [])
    return healthy + paused
