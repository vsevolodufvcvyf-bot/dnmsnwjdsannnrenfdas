# -*- coding: utf-8 -*-
"""Первый запуск: недостающие пакеты, .env, конфиги из configs.example."""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import time

REQUIRED_MODULES = {
    "requests": "requests",
    "urllib3": "urllib3",
    "telebot": "pyTelegramBotAPI",
    "bs4": "beautifulsoup4",
    "lxml": "lxml",
    "bcrypt": "bcrypt",
    "colorama": "colorama",
    "psutil": "psutil",
    "requests_toolbelt": "requests-toolbelt",
    "dotenv": "python-dotenv",
    "socks": "pysocks",
}

EXAMPLE_DIR = "configs.example"
CONFIG_DIR = "configs"
NEVER_COPY = {"_main.cfg", "team.cfg"}


def missing_modules() -> list[str]:
    missing = []
    for module, package in REQUIRED_MODULES.items():
        try:
            importlib.import_module(module)
        except Exception:
            missing.append(package)
    return missing


def ensure_deps(log_path: str = os.path.join("logs", "pip_install.txt")) -> None:
    """Ставит пакеты, если хоть одного нет. Сначала requirements.txt, потом по одному."""
    missing = missing_modules()
    if not missing:
        return
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"\n{time.strftime('%Y-%m-%d %H:%M:%S')} auto-install, нет: {', '.join(missing)}\n")
        log.flush()
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            stdout=log, stderr=subprocess.STDOUT,
        )
        if proc.returncode != 0:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", *sorted(set(REQUIRED_MODULES.values()))],
                stdout=log, stderr=subprocess.STDOUT, check=True,
            )
    importlib.invalidate_caches()
    still = missing_modules()
    if still:
        raise RuntimeError("Не поставились пакеты: " + ", ".join(still) + ". Смотри logs/pip_install.txt")


def load_env(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(path)
    except Exception:
        pass


def ensure_example_configs(example_dir: str = EXAMPLE_DIR, config_dir: str = CONFIG_DIR) -> list[str]:
    """Копирует недостающие конфиги из configs.example. Существующие файлы не трогает."""
    copied = []
    if not os.path.isdir(example_dir):
        return copied
    os.makedirs(config_dir, exist_ok=True)
    for name in sorted(os.listdir(example_dir)):
        if not name.endswith(".cfg") or name in NEVER_COPY:
            continue
        dst = os.path.join(config_dir, name)
        if os.path.exists(dst):
            continue
        shutil.copyfile(os.path.join(example_dir, name), dst)
        copied.append(name)
    return copied
