# -*- coding: utf-8 -*-
"""Совместимость: общий код переехал в пакет shop_core.

Старые импорты `plugins._common.<модуль>` получают те же объекты модулей,
поэтому состояние (заморозка, кэш, подключение к Cardinal) общее.
"""
import importlib
import sys

for _name in ("bus", "confirm", "db", "finance", "hooks", "howto", "logging_redact", "panels",
              "plugin_settings", "rate_limit", "sanitizer", "settings", "team"):
    try:
        sys.modules[f"{__name__}.{_name}"] = importlib.import_module(f"shop_core.{_name}")
    except Exception:  # noqa: BLE001 - один сломанный модуль не должен ронять остальные
        pass
