# -*- coding: utf-8 -*-
"""Черновик названия и описания лота.

Сам лот на FunPay не публикует. Нейросеть — по желанию; если её ответ просит отзыв,
обещает скидку или тащит контакт, остаётся шаблон.
"""
from __future__ import annotations

import html
import re

from shop_core.sanitizer import promise_reason, sanitize_reason

_LINK = re.compile(r"https?://\S+|www\.\S+", re.I)
_AT = re.compile(r"(?<!\w)@[a-zA-Z0-9_]{3,}")
_LONG_DIGITS = re.compile(r"\d{9,}")


class LotDraftError(ValueError):
    pass


def _clean_product(text: str) -> str:
    raw = _LINK.sub(" ", text or "")
    raw = _AT.sub(" ", raw)
    raw = _LONG_DIGITS.sub(" ", raw)
    return " ".join(raw.split())


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]).strip()


def template_lot(product: str, hint: str = "") -> dict:
    name = _clean_product(product)
    if len(name) < 2:
        raise LotDraftError("empty")
    title = _clip(name, 70)
    lines = [
        f"{name}.",
        "После оплаты напишите в чат этого заказа — продавец выдаст товар здесь.",
        "Если заказ не совпал с описанием, напишите в тот же чат.",
    ]
    extra = _clean_product(hint)
    if extra:
        lines.append(extra + ".")
    lines.append("Черновик для витрины. Перед публикацией сверься с правилами раздела FunPay.")
    body = "\n".join(lines)
    blob = title + "\n" + body
    if sanitize_reason(blob) or promise_reason(blob):
        raise LotDraftError("dirty")
    return {"title": title, "body": body, "source": "template"}


def parse_llm_lot(text: str) -> dict | None:
    raw = (text or "").strip()
    title_m = re.search(r"НАЗВАНИЕ\s*:\s*(.+)", raw, re.I)
    body_m = re.search(r"ОПИСАНИЕ\s*:\s*(.+)", raw, re.I | re.S)
    if not title_m or not body_m:
        return None
    title = _clip(title_m.group(1).strip().splitlines()[0], 70)
    body = body_m.group(1).strip()[:1200]
    if len(title) < 2 or len(body) < 10:
        return None
    return {"title": title, "body": body, "source": "llm"}


def llm_messages(product: str, hint: str) -> list[dict]:
    extra = f"\nУточнение продавца: {hint}" if hint else ""
    return [
        {
            "role": "system",
            "content": (
                "Ты помогаешь продавцу FunPay написать лот. "
                "Не проси отзыв и подтверждение заказа. Не обещай скидку, возврат, подарок, бесплатно. "
                "Не пиши, что выдача моментальная или полностью автоматическая. "
                "Не давай ссылки, телефоны и ники. Коротко, по-русски."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Товар: {product}{extra}\n"
                "Ответ строго в формате:\n"
                "НАЗВАНИЕ: до 70 символов\n"
                "ОПИСАНИЕ:\n"
                "3-5 коротких строк: что получит покупатель и что написать в чат после оплаты."
            ),
        },
    ]


def lot_text(product: str, hint: str = "", llm=None) -> dict:
    base = template_lot(product, hint)
    if llm is None:
        return base
    try:
        raw = llm(product, hint)
    except Exception:
        return base
    parsed = parse_llm_lot(raw or "")
    if not parsed:
        return base
    blob = parsed["title"] + "\n" + parsed["body"]
    if sanitize_reason(blob) or promise_reason(blob):
        return base
    return parsed


def format_lot_message(draft: dict) -> str:
    src = "нейросеть" if draft.get("source") == "llm" else "шаблон, без нейросети"
    return (
        f"📝 <b>Черновик лота</b> · {src}\n\n"
        f"<b>Название</b>\n<code>{html.escape(draft.get('title') or '')}</code>\n\n"
        f"<b>Описание</b>\n<code>{html.escape(draft.get('body') or '')}</code>\n\n"
        "<i>Скопируй и поправь под правила раздела. Бот лот сам не публикует.</i>"
    )


def parse_lot_args(text: str) -> tuple[str, str]:
    raw = re.sub(r"^/lottext(?:@\S+)?\s*", "", (text or "").strip(), flags=re.I)
    if "|" in raw:
        product, hint = raw.split("|", 1)
        return product.strip(), hint.strip()
    return raw.strip(), ""
