# -*- coding: utf-8 -*-
from __future__ import annotations

import configparser
import os
import threading

_LOCK = threading.RLock()
OPS_FILE = os.path.join("configs", "ops.cfg")
AI_FILE = os.path.join("configs", "ai.cfg")


def _read(path: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if os.path.exists(path):
        cfg.read(path, encoding="utf-8")
    return cfg


def load_ops() -> configparser.ConfigParser:
    with _LOCK:
        return _read(OPS_FILE)


def save_ops(cfg: configparser.ConfigParser) -> None:
    with _LOCK:
        os.makedirs(os.path.dirname(OPS_FILE), exist_ok=True)
        with open(OPS_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)


def load_ai() -> configparser.ConfigParser:
    return _read(AI_FILE)


def save_ai(cfg: configparser.ConfigParser) -> None:
    os.makedirs(os.path.dirname(AI_FILE), exist_ok=True)
    with open(AI_FILE, "w", encoding="utf-8") as f:
        cfg.write(f)


def load_ini(path: str) -> configparser.ConfigParser:
    return _read(path)


def save_ini(path: str, cfg: configparser.ConfigParser) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        cfg.write(f)


def ini_bool(path: str, section: str, key: str, default: bool = False) -> bool:
    cfg = load_ini(path)
    if not cfg.has_section(section):
        return default
    return cfg.getboolean(section, key, fallback=default)


def set_ini(path: str, section: str, key: str, value) -> None:
    cfg = load_ini(path)
    if not cfg.has_section(section):
        cfg.add_section(section)
    cfg.set(section, key, "1" if value in (True, 1, "1", "true", "True") else str(value) if not isinstance(value, bool) else ("1" if value else "0"))
    save_ini(path, cfg)


def flip_ini(path: str, section: str, key: str, default: bool = False) -> bool:
    new = not ini_bool(path, section, key, default)
    set_ini(path, section, key, "1" if new else "0")
    return new


def is_dry_run() -> bool:
    cfg = load_ops()
    return cfg.getboolean("Ops", "dry_run", fallback=False)


def is_panic() -> bool:
    cfg = load_ops()
    return cfg.getboolean("Ops", "panic", fallback=False)


def set_flag(section: str, key: str, value: str) -> None:
    cfg = load_ops()
    if not cfg.has_section(section):
        cfg.add_section(section)
    cfg.set(section, key, str(value))
    save_ops(cfg)


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
