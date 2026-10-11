# -*- coding: utf-8 -*-
"""Проверка новых релизов оригинального FunPay Cardinal. Только уведомление, без автообновления."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("FPC.Upstream")

RELEASES_API = "https://api.github.com/repos/sidor0912/FunPayCardinal/releases/latest"
RELEASES_URL = "https://github.com/sidor0912/FunPayCardinal/releases"
SEEN_FLAG = "upstream_seen_tag"


def version_tuple(tag: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", tag or ""))


def is_newer(tag: str, base: str) -> bool:
    return bool(version_tuple(tag)) and version_tuple(tag) > version_tuple(base)


def latest_tag(timeout: float = 10.0) -> str | None:
    try:
        import requests
        res = requests.get(RELEASES_API, timeout=timeout, headers={"Accept": "application/vnd.github+json"})
        if res.status_code == 200:
            return str(res.json().get("tag_name") or "") or None
    except Exception as ex:
        logger.debug("[Upstream] %s", ex)
    return None


def check_and_notify(cardinal, tag: str | None = None) -> str | None:
    """Сообщает один раз на каждый новый релиз. Возвращает тег, если он новее базы сборки."""
    from Utils.brand import UPSTREAM_BASE_VERSION
    from shop_core.bus import get_flag, notify, set_flag
    tag = tag if tag is not None else latest_tag()
    if not tag or not is_newer(tag, UPSTREAM_BASE_VERSION):
        return None
    if get_flag(SEEN_FLAG) == tag:
        return tag
    set_flag(SEEN_FLAG, tag)
    notify(
        cardinal,
        f"🆕 Вышел FunPay Cardinal {tag} (эта сборка основана на v{UPSTREAM_BASE_VERSION}).\n"
        f"В новых версиях бывают правки под изменения FunPay — их нужно перенести в сборку вручную, "
        f"автообновление выключено, чтобы не затереть плагины.\n{RELEASES_URL}",
        False,
    )
    return tag


def status_line() -> str:
    from Utils.brand import UPSTREAM_BASE_VERSION
    from shop_core.bus import get_flag
    seen = get_flag(SEEN_FLAG)
    if seen and is_newer(seen, UPSTREAM_BASE_VERSION):
        return f"Ядро: FunPay Cardinal v{UPSTREAM_BASE_VERSION}, есть новее — {seen}. Правки переносятся вручную."
    return f"Ядро: FunPay Cardinal v{UPSTREAM_BASE_VERSION}."
