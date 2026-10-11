# -*- coding: utf-8 -*-
"""Regex egress filter for FunPay chat. Does not bypass FunPay moderation."""
from __future__ import annotations

import re
import unicodedata

HOMO = str.maketrans({
    "а": "а", "a": "а", "@": "а",
    "е": "е", "e": "е",
    "о": "о", "o": "о", "0": "о",
    "р": "р", "p": "р",
    "с": "с", "c": "с",
    "у": "у", "y": "у",
    "х": "х", "x": "х",
    "к": "к", "k": "к",
})

STOP_ROOTS = (
    r"отзыв", r"оценк", r"подтверд", r"закрыть заказ",
    r"(?:постав\w*|остав\w*|пять|5)\s*(?:\d\s*)?зв[её]зд",
    r"телеграм", r"telegram", r"whatsapp", r"ватсап", r"viber",
    r"discord", r"vk\.com", r"инстаграм",
    r"кардинал", r"полностью автоматическ", r"выдача полностью",
    r"автоматическая 24", r"выдача моментальн",
)

LINK_RE = re.compile(r"(https?://|www\.|t\.me/|vk\.com/|discord\.gg/)", re.I)
AT_RE = re.compile(r"(?<!\w)@[a-zA-Z0-9_]{3,}")
PHONE_RE = re.compile(r"(?:\+?\d[\d\-\s()]{6,}\d)")
DIGITS_RUN = re.compile(r"\d{7,}")


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = t.translate(HOMO)
    t = re.sub(r"[.\-_*]+", "", t)
    return t


def sanitize_reason(text: str) -> str | None:
    raw = text or ""
    if "🐦" in raw or "cardinal" in raw.lower() or "\u2061" in raw or "\u2064" in raw:
        return "watermark"
    if LINK_RE.search(raw):
        return "link"
    if AT_RE.search(raw):
        return "mention"
    if PHONE_RE.search(raw) or DIGITS_RUN.search(raw):
        return "digits"
    folded = _fold(raw)
    for root in STOP_ROOTS:
        if re.search(root, folded, re.I):
            return f"stop:{root}"
    return None


def is_clean(text: str) -> bool:
    return sanitize_reason(text) is None
