# -*- coding: utf-8 -*-
"""Цена для покупателя и цена в форме лота.

FunPay показывает покупателю цену формы × коэффициент комиссии раздела. Сравнивать нужно
с витриной (цены покупателя), а вписывать в форму — цену без комиссии.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("FPC.Pricing")

_COEF_CACHE: dict[int, tuple[float, float | None]] = {}
_COEF_TTL = 6 * 3600


def coef_from(calc) -> float | None:
    """Коэффициент «цена покупателя / цена в форме лота». Вне 1.0–3.0 считаем неизвестным."""
    if calc is None:
        return None
    try:
        coef = float(calc.commission_coefficient)
    except Exception:
        return None
    return coef if 1.0 <= coef <= 3.0 else None


def seller_price_for(buyer_price: float, coef: float) -> float:
    """Сколько вписать в форму лота, чтобы покупатель видел buyer_price."""
    return round(float(buyer_price) / float(coef), 2)


def buyer_price_for(form_price: float, coef: float) -> float:
    return round(float(form_price) * float(coef), 2)


def section_coef(cardinal, subcategory_id: int) -> float | None:
    """Коэффициент комиссии раздела через calc(), кэш на 6 часов."""
    try:
        sid = int(subcategory_id)
    except (TypeError, ValueError):
        return None
    hit = _COEF_CACHE.get(sid)
    if hit and time.time() - hit[0] < _COEF_TTL:
        return hit[1]
    coef = None
    try:
        from FunPayAPI.common.enums import SubCategoryTypes
        coef = coef_from(cardinal.account.calc(SubCategoryTypes.COMMON, sid))
    except Exception as ex:
        logger.debug("[Pricing] calc %s: %s", sid, ex)
    _COEF_CACHE[sid] = (time.time(), coef)
    return coef
