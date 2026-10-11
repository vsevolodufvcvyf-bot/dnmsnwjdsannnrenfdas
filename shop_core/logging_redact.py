# -*- coding: utf-8 -*-
"""Совместимость: маскировка логов живёт в Utils.log_redact и ставится в Utils.logger."""
from __future__ import annotations

from Utils.log_redact import RedactFilter, redact  # noqa: F401
from Utils.log_redact import install_on_loggers as install  # noqa: F401
