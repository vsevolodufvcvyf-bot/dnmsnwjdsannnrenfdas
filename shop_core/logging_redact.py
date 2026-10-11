# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import re

SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|token|password|golden_key|authorization|bearer|shared_secret|identity_secret)"
    r"([\"'\s:=]+)([^\s\"']{6,})"
)
KEYISH_RE = re.compile(r"(?i)\b(sk-[a-z0-9\-_]{10,}|ghp_[a-z0-9]{20,}|AIza[0-9A-Za-z\-_]{20,})\b")
GOLDEN_RE = re.compile(r"\b[a-z0-9]{32,40}\b")
CARD_RE = re.compile(r"\b\d{4}(?:[ -]?\d{4}){3,4}\b")


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            msg = SECRET_RE.sub(r"\1\2***REDACTED***", msg)
            msg = KEYISH_RE.sub("***REDACTED***", msg)
            msg = CARD_RE.sub("****CARD****", msg)
            record.msg = msg
            record.args = None
        except Exception:
            pass
        return True


def install() -> None:
    filt = RedactFilter()
    for name in ("main", "FunPayAPI", "FPC", "TGBot", "TeleBot"):
        logging.getLogger(name).addFilter(filt)
    logging.getLogger().addFilter(filt)
