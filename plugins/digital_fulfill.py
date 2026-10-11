# -*- coding: utf-8 -*-
from __future__ import annotations

import configparser
import logging
import os
import re
from threading import Thread

from plugins._common.bus import bot_send, notify
from plugins._common.confirm import (
    ask_confirm, ask_target, handle_pending_message, put_pending,
)
from plugins._common.panels import pick_cheapest, candidates_from_suppliers
from plugins._common.settings import ini_bool, flip_ini
from plugins._common.plugin_settings import SettingsPage

logger = logging.getLogger("FPC.DigitalFulfill")

NAME = "Digital Fulfill (Stars / Steam / Robux panels)"
VERSION = "1.0.0"
DESCRIPTION = "Закупка у API-панелей по ключам из configs/suppliers.cfg (без реверса чужих сайтов)"
CREDITS = "Cardinal Community"
UUID = "c0ffee01-55aa-4d11-9e01-000000000001"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}

CONFIG_FILE = "configs/suppliers.cfg"


def load_cfg():
    cfg = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        cfg.read(CONFIG_FILE, encoding="utf-8")
    return cfg


def extract_link(text: str) -> str | None:
    m = re.search(r"(https?://[^\s]+|@[a-zA-Z0-9_]{4,}|t\.me/[^\s]+)", text or "")
    return m.group(0) if m else None


def _arm_order(cardinal, event):
    order = getattr(event, "order", None)
    if not order:
        return None
    desc = (getattr(order, "description", "") or getattr(order, "title", "") or "")
    low = desc.lower()
    if any(k in low for k in ("аренд", "rent", "почасов")):
        return None
    if any(k in low for k in ("звезд", "stars", "телеграм стар", "подарок", "подарк", "gift", "teddy")):
        return None
    if any(k in low for k in ("накрут", "подписчик", "лайк", "просмотр", " smm")):
        return None
    order_id = str(order.id)
    amount = max(1, int(getattr(order, "amount", 1) or 1))
    sale = float(getattr(order, "price", 0) or 0)
    cands = [
        c for c in candidates_from_suppliers(low)
        if "smm" not in c["section"].lower() and c.get("plugin_name") != "autosmm"
    ]
    if not cands:
        return None
    best, why = pick_cheapest(cands, sale, amount)
    if not best:
        notify(cardinal, f"📉 Price Guard #{order_id}: {why}", True)
        return None
    chat_id = getattr(order, "chat_id", None)
    if not chat_id:
        notify(cardinal, f"⚠️ digital #{order_id}: нет чата, закупку не шлём.", True)
        return None
    link = extract_link(desc) or extract_link(getattr(order, "description", "") or "")
    extra = {
        "query": desc or low,
        "plugin_name": best.get("plugin_name") or "digital",
        "target_section": str(best.get("section") or "").split("/")[0],
    }
    buyer = getattr(order, "buyer_id", None)
    name = getattr(order, "buyer_username", None)
    if link:
        status = put_pending(chat_id, order_id, "digital", "confirm", link, amount, sale, extra,
                             cardinal=cardinal, peer_id=buyer)
        if status == "fail":
            return None
        if status == "queued":
            return {"chat_id": chat_id, "name": name, "link": link, "mode": "queued"}
        return {"chat_id": chat_id, "name": name, "link": link, "mode": "confirm"}
    status = put_pending(chat_id, order_id, "digital", "need_target", "", amount, sale, extra,
                         cardinal=cardinal, peer_id=buyer)
    if status == "fail":
        return None
    if status == "queued":
        return {"chat_id": chat_id, "name": name, "link": None, "mode": "queued"}
    return {"chat_id": chat_id, "name": name, "link": None, "mode": "need"}


def _ask_after_arm(cardinal, armed):
    try:
        if armed["mode"] == "queued":
            from plugins._common.confirm import ask_queued
            ask_queued(cardinal, armed["chat_id"], armed["name"])
            return
        if armed["mode"] == "confirm":
            ask_confirm(cardinal, armed["chat_id"], "digital", armed["link"], armed["name"])
        else:
            bot_send(cardinal, armed["chat_id"], "Заказ принят. Нужны данные для выдачи.", armed["name"])
            ask_target(cardinal, armed["chat_id"], "digital", armed["name"])
    except Exception as ex:
        logger.error("[DigitalFulfill] ask: %s", ex)


def on_order(cardinal, event):
    try:
        armed = _arm_order(cardinal, event)
    except Exception as ex:
        logger.error("[DigitalFulfill] %s", ex)
        return
    if armed:
        Thread(target=_ask_after_arm, args=(cardinal, armed), daemon=True).start()


def on_message(cardinal, event):
    try:
        handle_pending_message(cardinal, event, {"digital"})
    except Exception as ex:
        logger.debug("[DigitalFulfill] msg: %s", ex)


def init_settings(cardinal):
    page = SettingsPage(UUID, NAME, "Панели Stars/Steam/Robux. Ключи — configs/suppliers.cfg.")
    cfg = load_cfg()
    for section in cfg.sections():
        if section == "smm":
            continue
        sec = section

        def getter(s=sec):
            return ini_bool(CONFIG_FILE, s, "enabled", False)

        def setter(_v, s=sec):
            flip_ini(CONFIG_FILE, s, "enabled", False)

        page.add_toggle(sec[:16], f"{sec}", getter, setter)

    def status():
        cfg2 = load_cfg()
        bits = []
        for s in cfg2.sections():
            if s == "smm":
                continue
            on = cfg2[s].getboolean("enabled", fallback=False)
            bits.append(f"{'✅' if on else '❌'} {s}")
        return "\n".join(bits) or "Секций нет"

    page.set_status(status).attach(cardinal)


BIND_TO_PRE_INIT = [init_settings]
BIND_TO_NEW_ORDER = [on_order]
BIND_TO_NEW_MESSAGE = [on_message]
