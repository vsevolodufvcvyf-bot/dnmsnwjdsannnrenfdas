# -*- coding: utf-8 -*-
"""Переносит ключи, конфиги, maFile и базу из старой папки бота в эту.

Старую папку не меняет и ничего в ней не удаляет. Код и плагины не копирует.
Запуск: Migrate.bat (можно перетащить старую папку на файл) или
python tools/migrate.py "C:\\путь\\к\\старой\\папке"
"""
from __future__ import annotations

import os
import shutil
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = [".env", "rental_accounts.json"]
DIRS = ["configs", "mafiles", "storage"]


def looks_like_bot(path: str) -> bool:
    return os.path.isfile(os.path.join(path, "configs", "_main.cfg"))


def find_candidates() -> list[str]:
    parent = os.path.dirname(HERE)
    out = []
    try:
        for name in sorted(os.listdir(parent)):
            path = os.path.join(parent, name)
            if os.path.abspath(path) == HERE or not os.path.isdir(path):
                continue
            if looks_like_bot(path):
                out.append(path)
            else:
                nested = os.path.join(path, "nnanserShop")
                if looks_like_bot(nested):
                    out.append(nested)
    except OSError:
        pass
    return out


def copy_tree(src: str, dst: str) -> int:
    n = 0
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(target, exist_ok=True)
        for name in files:
            shutil.copy2(os.path.join(root, name), os.path.join(target, name))
            n += 1
    return n


def migrate(old: str, new: str = HERE) -> list[str]:
    report = []
    for name in FILES:
        src = os.path.join(old, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(new, name))
            report.append(f"файл {name}")
    for name in DIRS:
        src = os.path.join(old, name)
        if os.path.isdir(src):
            n = copy_tree(src, os.path.join(new, name))
            report.append(f"папка {name}/ ({n} файлов)")
    return report


def main() -> int:
    old = sys.argv[1].strip().strip('"') if len(sys.argv) > 1 else ""
    if not old:
        cands = find_candidates()
        if len(cands) == 1:
            old = cands[0]
            print(f"Нашёл старую папку: {old}")
        else:
            if cands:
                print("Нашёл несколько папок с ботом:")
                for i, c in enumerate(cands, 1):
                    print(f"  {i}. {c}")
            old = input("Вставь путь к СТАРОЙ папке бота (где лежит configs\\_main.cfg) и нажми Enter: ").strip().strip('"')
            if old.isdigit() and cands and 1 <= int(old) <= len(cands):
                old = cands[int(old) - 1]
    old = os.path.abspath(old)
    if old == HERE:
        print("Это и есть новая папка. Нужна старая.")
        return 1
    if not looks_like_bot(old):
        print(f"В {old} нет configs\\_main.cfg — это не папка бота.")
        return 1
    report = migrate(old)
    if not report:
        print("Переносить нечего.")
        return 1
    print("Перенёс:")
    for line in report:
        print("  • " + line)
    print()
    print("Дальше:")
    print("  1. Если ещё не менял ключи — смени golden_key (команда /golden_key в боте),")
    print("     токен бота (@BotFather → /revoke, новый вписать в configs\\_main.cfg) и ключи в .env.")
    print("  2. Запусти Start.bat.")
    return 0


if __name__ == "__main__":
    code = main()
    if os.name == "nt":
        input("\nНажми Enter, чтобы закрыть окно...")
    sys.exit(code)
