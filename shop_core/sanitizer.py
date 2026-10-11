# -*- coding: utf-8 -*-
"""Фильтр исходящих ответов ИИ в чат FunPay. Модерацию FunPay не обходит, а не даёт её нарушить."""
from __future__ import annotations

import re
import unicodedata

HOMO = str.maketrans({
    "a": "а", "@": "а",
    "e": "е",
    "o": "о", "0": "о",
    "p": "р",
    "c": "с",
    "y": "у",
    "x": "х",
    "k": "к",
})

STOP_ROOTS = (
    r"отзыв", r"оценк", r"подтверд", r"закрыть заказ",
    r"(?:постав\w*|остав\w*|пять|5)\s*(?:\d\s*)?зв[её]зд",
    r"(?:пиши|напиши|пишите|напишите|мой|моя|мне\s+в|в\s+личк\w*\s+в?)\s*(?:телеграм\w*|тг|tg)\b",
    r"(?:телеграм\w*|тг|tg)\s*[:@]",
    r"whatsapp", r"ватсап", r"viber", r"вайбер",
    r"discord", r"дискорд", r"vk\.com", r"инстаграм", r"instagram",
    r"кардинал", r"полностью автоматическ", r"выдача полностью",
    r"автоматическая 24", r"выдача моментальн",
)

PROMISE_ROOTS = (
    r"бесплатн", r"даром", r"скидк", r"промокод", r"бонус", r"компенсац",
    r"верн[уёе]\w*\s+(?:вам\s+|тебе\s+)?(?:деньги|средства|оплату)", r"возврат\w*\s+(?:денег|средств)",
    r"сделаю\s+возврат", r"оформлю\s+возврат", r"подарю", r"в\s+подарок",
)

LINK_RE = re.compile(r"(https?://|www\.|t\.me/|vk\.com/|discord\.gg/)", re.I)
AT_RE = re.compile(r"(?<!\w)@[a-zA-Z0-9_]{3,}")
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)"
    r"|(?<!\d)\+\d{10,14}(?!\d)"
)
DIGITS_RUN = re.compile(r"\d{9,}")


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
        if re.search(root, folded, re.I) or re.search(root, raw.lower(), re.I):
            return f"stop:{root}"
    return None


def is_clean(text: str) -> bool:
    return sanitize_reason(text) is None


def promise_reason(text: str) -> str | None:
    """Обещания денег и подарков решает только продавец: такой ответ ИИ не отправляем."""
    low = (text or "").lower().replace("ё", "е")
    for root in PROMISE_ROOTS:
        if re.search(root.replace("ё", "е"), low):
            return root
    return None
