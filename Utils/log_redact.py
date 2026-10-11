# -*- coding: utf-8 -*-
"""Маскировка секретов в логах.

Фильтр вешается на хендлер, а не на логгер: фильтр логгера не видит записи дочерних
логгеров (FPC.*, FunPayAPI.*), а через хендлер проходит всё, включая трейсбеки.
"""
from __future__ import annotations

import logging
import re

MASK = "***"

_KV_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|golden_key|"
    r"authorization|bearer|shared_secret|identity_secret|revocation_code|secretkeyhash|phpsessid|key)\b"
    r"([\"'\s:=]+)([^\s\"',;&]{6,})"
)
_TG_TOKEN_RE = re.compile(r"(\d{6,12}):([A-Za-z0-9_-]{30,})")
_PREFIXED_RE = re.compile(r"\b(sk-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,}|AQ[A-Za-z0-9._-]{20,})")
_GOLDEN_RE = re.compile(r"\b(?=[a-z0-9]{32}\b)(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])[a-z0-9]{32}\b")
_CARD_RE = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}(?:[ -]?\d{1,3})?\b")


def _mask_card(m: re.Match) -> str:
    digits = re.sub(r"\D", "", m.group(0))
    return f"****{digits[-4:]}"


def redact(text: str) -> str:
    if not text:
        return text
    text = _TG_TOKEN_RE.sub(lambda m: f"{m.group(1)}:{MASK}", text)
    text = _KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)
    text = _PREFIXED_RE.sub(MASK, text)
    text = _GOLDEN_RE.sub(MASK, text)
    text = _CARD_RE.sub(_mask_card, text)
    return text


class RedactFilter(logging.Filter):
    _formatter = logging.Formatter()

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            safe = redact(msg)
            if safe != msg or record.args:
                record.msg = safe
                record.args = None
            if record.exc_info and not record.exc_text:
                record.exc_text = self._formatter.formatException(record.exc_info)
            if record.exc_text:
                record.exc_text = redact(record.exc_text)
        except Exception:
            pass
        return True


_FILTER = RedactFilter()


def install(*handlers: logging.Handler) -> None:
    for handler in handlers:
        if _FILTER not in handler.filters:
            handler.addFilter(_FILTER)


def install_on_loggers(names=("main", "FunPayAPI", "FPC", "TGBot", "TeleBot")) -> None:
    """Вешает фильтр на все хендлеры перечисленных логгеров (повторный вызов безопасен)."""
    for name in names:
        install(*logging.getLogger(name).handlers)
