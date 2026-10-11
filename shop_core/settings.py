# -*- coding: utf-8 -*-
"""Чтение и запись .cfg плагинов.

Файл перечитывается с диска только если изменился (mtime + размер): флаги вроде panic и
dry_run проверяются на каждом запросе к FunPay. Запись атомарная, а «прочитал — поменял —
записал» идёт под одним замком, чтобы два потока не теряли изменения друг друга.
"""
from __future__ import annotations

import configparser
import os
import threading

from shop_core.fileio import write_config

_LOCK = threading.RLock()
_CACHE: dict[str, tuple[tuple[int, int], str]] = {}
OPS_FILE = os.path.join("configs", "ops.cfg")
AI_FILE = os.path.join("configs", "ai.cfg")


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def _read(path: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    try:
        st = os.stat(path)
    except OSError:
        return cfg
    key = (st.st_mtime_ns, st.st_size)
    with _LOCK:
        hit = _CACHE.get(os.path.abspath(path))
        if hit and hit[0] == key:
            text = hit[1]
        else:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            _CACHE[os.path.abspath(path)] = (key, text)
    cfg.read_string(text)
    return cfg


def _write(path: str, cfg: configparser.ConfigParser) -> None:
    with _LOCK:
        write_config(path, cfg)
        _CACHE.pop(os.path.abspath(path), None)


def load_ops() -> configparser.ConfigParser:
    return _read(OPS_FILE)


def save_ops(cfg: configparser.ConfigParser) -> None:
    _write(OPS_FILE, cfg)


def load_ai() -> configparser.ConfigParser:
    return _read(AI_FILE)


def save_ai(cfg: configparser.ConfigParser) -> None:
    _write(AI_FILE, cfg)


def load_ini(path: str) -> configparser.ConfigParser:
    return _read(path)


def save_ini(path: str, cfg: configparser.ConfigParser) -> None:
    _write(path, cfg)


def ini_bool(path: str, section: str, key: str, default: bool = False) -> bool:
    cfg = load_ini(path)
    if not cfg.has_section(section):
        return default
    return cfg.getboolean(section, key, fallback=default)


def _as_text(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if value in (1, "1", "true", "True"):
        return "1"
    return str(value)


def set_ini(path: str, section: str, key: str, value) -> None:
    with _LOCK:
        cfg = load_ini(path)
        if not cfg.has_section(section):
            cfg.add_section(section)
        cfg.set(section, key, _as_text(value))
        save_ini(path, cfg)


def flip_ini(path: str, section: str, key: str, default: bool = False) -> bool:
    with _LOCK:
        new = not ini_bool(path, section, key, default)
        set_ini(path, section, key, "1" if new else "0")
        return new


def is_dry_run() -> bool:
    return load_ops().getboolean("Ops", "dry_run", fallback=False)


def is_panic() -> bool:
    return load_ops().getboolean("Ops", "panic", fallback=False)


def set_flag(section: str, key: str, value: str) -> None:
    set_ini(OPS_FILE, section, key, str(value))


def commission() -> float:
    return load_ops().getfloat("Ops", "funpay_commission", fallback=0.03)


def min_margin_mult() -> float:
    """Минимальный запас: сколько раз «чистыми с FunPay» должно быть больше закупки. 2 = удвоение."""
    try:
        v = load_ops().getfloat("Ops", "min_margin_mult", fallback=2.0)
    except Exception:
        v = 2.0
    return min(10.0, max(1.0, float(v or 2.0)))


def withdraw_fee_pct() -> float:
    try:
        v = load_ops().getfloat("Ops", "withdraw_fee_pct", fallback=0.03)
    except Exception:
        v = 0.03
    return min(0.15, max(0.0, float(v or 0.03)))


def withdraw_min_rub() -> float:
    try:
        v = load_ops().getfloat("Ops", "withdraw_min_rub", fallback=1000.0)
    except Exception:
        v = 1000.0
    return max(1.0, float(v or 1000.0))


def usd_rub() -> float:
    try:
        v = load_ops().getfloat("Ops", "usd_rub", fallback=90.0)
    except Exception:
        v = 90.0
    return max(1.0, float(v or 90.0))
