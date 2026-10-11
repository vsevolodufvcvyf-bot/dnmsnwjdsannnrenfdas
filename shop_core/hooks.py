# -*- coding: utf-8 -*-
"""Реестр точек расширения: плагины регистрируют функции, ядро вызывает их, если они есть.

Так ядро не импортирует плагины напрямую и не ломается, если плагин удалён.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

logger = logging.getLogger("FPC.Hooks")

_LOCK = threading.RLock()
_SINGLE: dict[str, Callable] = {}
_MULTI: dict[str, list[Callable]] = {}


def provide(name: str, fn: Callable) -> None:
    """Одна реализация на имя (последняя регистрация побеждает)."""
    with _LOCK:
        _SINGLE[name] = fn


def get(name: str) -> Callable | None:
    with _LOCK:
        return _SINGLE.get(name)


def subscribe(name: str, fn: Callable) -> None:
    """Несколько подписчиков на одно событие; повторная подписка той же функции игнорируется."""
    with _LOCK:
        subs = _MULTI.setdefault(name, [])
        if fn not in subs:
            subs.append(fn)


def emit(name: str, *args: Any, **kwargs: Any) -> None:
    with _LOCK:
        subs = list(_MULTI.get(name, []))
    for fn in subs:
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.warning("[Hooks] %s: подписчик %s упал", name, getattr(fn, "__name__", fn), exc_info=True)


def collect(name: str, *args: Any, **kwargs: Any) -> list:
    """Вызывает всех подписчиков и склеивает их списки-результаты."""
    out: list = []
    with _LOCK:
        subs = list(_MULTI.get(name, []))
    for fn in subs:
        try:
            res = fn(*args, **kwargs)
        except Exception:
            logger.warning("[Hooks] %s: подписчик %s упал", name, getattr(fn, "__name__", fn), exc_info=True)
            continue
        if res:
            out.extend(res)
    return out
