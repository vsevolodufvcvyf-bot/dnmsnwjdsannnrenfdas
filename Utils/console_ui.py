# -*- coding: utf-8 -*-
"""Рамки и цвета консоли nnanserShop (Windows CMD / PowerShell)."""
from __future__ import annotations

import os
import re
import sys

from colorama import Fore, Style

INNER = 66
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")
TOKEN_RE = re.compile(r"\$(?:CYAN|YELLOW|MAGENTA|RESET|GREEN|BLUE|WHITE|BLACK|B_[A-Z]+)")


def enable_windows_console() -> None:
    if sys.platform != "win32":
        return
    os.environ.setdefault("PYTHONUTF8", "1")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        for handle_id in (-11, -12):
            handle = kernel32.GetStdHandle(handle_id)
            mode = ctypes.c_uint()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def vis_len(text: str) -> int:
    return len(ANSI_RE.sub("", TOKEN_RE.sub("", text or "")))


def pad(text: str, width: int) -> str:
    extra = width - vis_len(text)
    if extra > 0:
        return text + (" " * extra)
    return text


def _edge(left: str, mid: str, right: str, color: str) -> str:
    r = Style.RESET_ALL
    return f"  {color}{left}{mid * INNER}{right}{r}"


def card_top(color: str | None = None) -> str:
    c = color or (Fore.CYAN + Style.BRIGHT)
    return _edge("╔", "═", "╗", c)


def card_sep(color: str | None = None) -> str:
    c = color or (Fore.CYAN + Style.BRIGHT)
    return _edge("╠", "═", "╣", c)


def card_bot(color: str | None = None) -> str:
    c = color or (Fore.CYAN + Style.BRIGHT)
    return _edge("╚", "═", "╝", c)


def card_row(text: str, color: str | None = None) -> str:
    c = color or (Fore.CYAN + Style.BRIGHT)
    r = Style.RESET_ALL
    return f"  {c}║{r} {pad(text, INNER - 2)} {c}║{r}"


def thin_top(color: str | None = None) -> str:
    c = color or Fore.CYAN
    return _edge("╭", "─", "╮", c)


def thin_bot(color: str | None = None) -> str:
    c = color or Fore.CYAN
    return _edge("╰", "─", "╯", c)


def thin_row(text: str, color: str | None = None) -> str:
    c = color or Fore.CYAN
    r = Style.RESET_ALL
    return f"  {c}│{r} {pad(text, INNER - 2)} {c}│{r}"


def colorize_tokens(text: str) -> str:
    mapping = {
        "$YELLOW": Fore.YELLOW + Style.BRIGHT,
        "$CYAN": Fore.CYAN + Style.BRIGHT,
        "$MAGENTA": Fore.MAGENTA + Style.BRIGHT,
        "$GREEN": Fore.GREEN + Style.BRIGHT,
        "$BLUE": Fore.BLUE + Style.BRIGHT,
        "$WHITE": Fore.WHITE,
        "$BLACK": Fore.BLACK + Style.BRIGHT,
        "$RESET": Style.RESET_ALL,
    }
    for token, code in mapping.items():
        if token in text:
            text = text.replace(token, code)
    return text


def print_block(text: str) -> None:
    print()
    print(colorize_tokens(text) + Style.RESET_ALL)
    print(flush=True)


def print_splash(stage: str = "boot", extra: str = "") -> None:
    try:
        import colorama
        colorama.init(autoreset=False, convert=True)
    except Exception:
        pass
    enable_windows_console()
    from Utils.brand import APP_NAME, TAGLINE, VERSION
    c = Fore.CYAN + Style.BRIGHT
    m = Fore.MAGENTA + Style.BRIGHT
    y = Fore.YELLOW + Style.BRIGHT
    g = Fore.GREEN + Style.BRIGHT
    dim = Fore.WHITE + Style.DIM
    r = Style.RESET_ALL
    letters = "  ".join(list(APP_NAME))
    print(flush=True)
    print(card_top(m))
    print(card_row("", m))
    print(card_row(m + letters + r, m))
    print(card_row("", m))
    print(card_row(y + APP_NAME + r + dim + "   " + TAGLINE + r, m))
    print(card_row(dim + "v" + VERSION + "    FunPay · Telegram · автоцена" + r, m))
    print(card_row(dim + "на базе FunPay Cardinal · @sidor0912" + r, m))
    print(card_row("", m))
    print(card_sep(c))
    if stage in ("boot", "1"):
        print(card_row(c + "  1/2  " + r + "пакеты Python"))
        print(card_row(dim + "      тихо, лог → logs\\pip_install.txt" + r))
    elif stage in ("go", "2"):
        print(card_row(g + "  2/2  " + r + "магазин поднимается"))
        print(card_row(y + "      /menu" + r + "     пульт"))
        print(card_row(y + "      автоцена" + r + "  лоты под рынок, в плюсе"))
        print(card_row(y + "      /check" + r + "    напишет, только если нужно"))
        print(card_row(dim + "      стоп: Ctrl+C" + r))
    elif stage in ("down", "stop"):
        code = extra or "?"
        if str(code) in ("0", "3221225786"):
            print(card_row(y + "  пауза  " + r + "перезапуск через 5 сек"))
        else:
            print(card_row(y + "  остановка  " + r + f"код {code}"))
            print(card_row(dim + "      смотри logs\\error.txt" + r))
        print(card_row(dim + "      перезапуск через 5 сек" + r))
    else:
        print(card_row(g + "  ●  " + r + "/menu   кошелёк · автоцена · проверка"))
        print(card_row(g + "  ●  " + r + "микролоты 5–10 ₽ автоцена не двигает"))
        print(card_row(g + "  ●  " + r + "логи     logs\\error.txt"))
        print(card_row(dim + "      Ctrl+C — стоп" + r))
    print(card_row(""))
    print(card_bot(m))
    print(flush=True)
