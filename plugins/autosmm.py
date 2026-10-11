# -*- coding: utf-8 -*-
from __future__ import annotations

import configparser
import logging
import os
import re
import time
from threading import Thread

import requests

from plugins._common.bus import bot_send, notify
from plugins._common.confirm import ask_target, handle_pending_message, put_pending
from plugins._common.db import get_db
from plugins._common.finance import claim_delivery, log_finance, preflight_or_abort, release_delivery, supplier_post
from plugins._common.panels import candidates_from_suppliers, pick_cheapest
from plugins._common.settings import is_dry_run, ini_bool, flip_ini
from plugins._common.plugin_settings import SettingsPage

logger = logging.getLogger("FPC.AutoSMM")

NAME = "AutoSMM Reseller"
VERSION = "2.0.0"
DESCRIPTION = "Перепродажа SMM: pre-flight PAID, идемпотентность, учебный режим"
CREDITS = "Cardinal Community"
UUID = "4a9d7e21-8b3c-4f15-9c2d-7e1a3b5c6f89"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}

CONFIG_FILE = "configs/autosmm.cfg"
FALLBACK_FILE = "configs/suppliers.cfg"


def load_smm_config():
    cfg = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        cfg.read(CONFIG_FILE, encoding="utf-8")
    return cfg


def extract_link(text: str) -> str | None:
    m = re.search(r"(https?://[^\s]+|@[a-zA-Z0-9_]{4,}|t\.me/[^\s]+)", text or "")
    return m.group(0) if m else None


def _fallback_pair(cfg):
    url2 = key2 = ""
    if os.path.exists(FALLBACK_FILE):
        s = configparser.ConfigParser()
        s.read(FALLBACK_FILE, encoding="utf-8")
        if s.has_section("smm"):
            url2 = s["smm"].get("fallback_api_url", "")
            key2 = s["smm"].get("fallback_api_key", "")
    return url2, key2


def smm_panel_candidates(service_id) -> list[dict]:
    """Панель из configs/autosmm.cfg. confirm.py её иначе не видит."""
    cfg = load_smm_config()
    if not cfg.has_section("Settings"):
        return []
    api_url = cfg["Settings"].get("api_url", "").strip()
    api_key = cfg["Settings"].get("api_key", "").strip()
    if not api_url or not api_key:
        return []
    cpu = "0"
    if os.path.exists(FALLBACK_FILE):
        s = configparser.ConfigParser()
        s.read(FALLBACK_FILE, encoding="utf-8")
        if s.has_section("smm"):
            cpu = s["smm"].get("cost_per_unit", "0")
    sid = str(service_id or cfg["Settings"].get("service_id", "") or "").strip()
    out = [{
        "name": "autosmm.cfg",
        "api_url": api_url,
        "api_key": api_key,
        "service_id": sid,
        "cost_per_unit": cpu,
        "plugin_name": "autosmm",
        "section": "autosmm",
        "keywords": "smm",
    }]
    u2, k2 = _fallback_pair(cfg)
    if u2 and k2:
        out.append({
            "name": "autosmm.cfg/запас",
            "api_url": u2,
            "api_key": k2,
            "service_id": sid,
            "cost_per_unit": cpu,
            "plugin_name": "autosmm",
            "section": "autosmm",
            "keywords": "smm",
        })
    return out


def _panel_add(url, key, service_id, link, quantity):
    payload = {"key": key, "action": "add", "service": service_id, "link": link, "quantity": quantity}
    res = supplier_post(requests.post, url, payload, timeout=12.0)
    data = res.json()
    if "order" in data:
        return str(data["order"]), data
    raise RuntimeError(str(data))


def _match_smm(event):
    cfg = load_smm_config()
    if not cfg.has_section("Settings") or not cfg["Settings"].getboolean("enabled", fallback=False):
        return None
    order = getattr(event, "order", None)
    if not order:
        return None
    order_desc = (order.description or "").strip()
    lots = cfg["Lots"] if cfg.has_section("Lots") else {}
    matched_rule = None
    for lot_name in lots:
        if lot_name.lower() in order_desc.lower():
            matched_rule = lots[lot_name]
            break
    if not matched_rule:
        return None
    service_id, quantity = matched_rule.split(":")
    service_id = int(service_id)
    quantity = int(quantity) * (order.amount or 1)
    return {
        "cfg": cfg,
        "order": order,
        "order_id": str(getattr(order, "id", "")),
        "order_desc": order_desc,
        "service_id": service_id,
        "quantity": quantity,
        "target_link": extract_link(order.description),
        "chat_id": getattr(order, "chat_id", None),
        "sale": float(getattr(order, "price", 0) or 0),
        "extra": {"query": order_desc, "service_id": str(service_id)},
    }


def _ask_smm(cardinal, matched):
    try:
        chat_id = matched["chat_id"]
        if matched.get("queue") == "queued":
            from plugins._common.confirm import ask_queued
            ask_queued(cardinal, chat_id)
            return
        if matched["target_link"]:
            from plugins._common.confirm import ask_confirm
            ask_confirm(cardinal, chat_id, "smm", matched["target_link"])
        else:
            bot_send(cardinal, chat_id, "Заказ накрутки принят.")
            ask_target(cardinal, chat_id, "smm")
    except Exception as ex:
        logger.error("[AutoSMM] ask: %s", ex)


def process_smm_order(cardinal, event):
    try:
        matched = _match_smm(event)
        if not matched:
            return
        _fulfill_smm_direct(cardinal, matched)
    except Exception as ex:
        logger.error("[AutoSMM] %s", ex)


def _fulfill_smm_direct(cardinal, matched):
    order = matched["order"]
    order_id = matched["order_id"]
    order_desc = matched["order_desc"]
    service_id = matched["service_id"]
    quantity = matched["quantity"]
    target_link = matched["target_link"]
    sale = matched["sale"]
    if not target_link:
        notify(cardinal, f"⚠️ AutoSMM #{order_id}: нет ссылки и нет чата.", True)
        return
    if not claim_delivery(order_id, "autosmm"):
        return

    cands = candidates_from_suppliers(order_desc, {"smm", "autosmm"})
    cands.extend(smm_panel_candidates(service_id))
    for c in cands:
        if not c.get("service_id"):
            c["service_id"] = str(service_id)
    best, why_m = pick_cheapest(cands, sale, quantity)
    if not best:
        release_delivery(order_id, "autosmm")
        notify(cardinal, f"📉 AutoSMM Price Guard #{order_id}: {why_m}", True)
        return
    cost = float(best.get("_cost") or 0)
    ok, why = preflight_or_abort(cardinal, order_id, "autosmm")
    if not ok and why != "dry_run":
        release_delivery(order_id, "autosmm")
        return

    if is_dry_run() or why == "dry_run":
        log_finance(order_id, "autosmm", sale, cost)
        bot_send(cardinal, order.chat_id, "[DRY-RUN] Закупка SMM не отправлялась. Заказ зафиксирован.")
        notify(cardinal, f"🧪 DRY-RUN AutoSMM #{order_id} qty={quantity}\n{why_m}", False)
        return

    task_id = None
    err = None
    try:
        sid = int(best.get("service_id") or service_id)
        task_id, _ = _panel_add(best["api_url"], best["api_key"], sid, target_link, quantity)
    except Exception as e1:
        err = e1
    if not task_id:
        release_delivery(order_id, "autosmm")
        notify(cardinal, f"❌ AutoSMM #{order_id} не ушёл поставщику: {err}", True)
        return

    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO smm_orders (order_id, service_id, target_link, task_id, status, created_at)
               VALUES (?, ?, ?, ?, 'success', ?)""",
            (order.id, service_id, target_link, task_id, time.time()),
        )
    log_finance(order_id, "autosmm", sale, cost)
    bot_send(cardinal, order.chat_id, f"Заказ накрутки в работе. ID задачи: #{task_id}.")
    logger.info("[AutoSMM] #%s [%s] task %s", order_id, best.get("name"), task_id)


def on_order_smm(cardinal, event):
    try:
        matched = _match_smm(event)
        if not matched:
            return
        chat_id = matched["chat_id"]
        if chat_id:
            extra = matched["extra"]
            buyer = getattr(matched["order"], "buyer_id", None)
            if matched["target_link"]:
                status = put_pending(
                    chat_id, matched["order_id"], "smm", "confirm",
                    matched["target_link"], matched["quantity"], matched["sale"], extra,
                    cardinal=cardinal, peer_id=buyer,
                )
            else:
                status = put_pending(
                    chat_id, matched["order_id"], "smm", "need_target", "",
                    matched["quantity"], matched["sale"], extra,
                    cardinal=cardinal, peer_id=buyer,
                )
            if status == "fail":
                return
            matched["queue"] = status
            Thread(target=_ask_smm, args=(cardinal, matched), daemon=True).start()
            return
        Thread(target=_fulfill_smm_direct, args=(cardinal, matched), daemon=True).start()
    except Exception as ex:
        logger.error("[AutoSMM] %s", ex)


def on_smm_message(cardinal, event):
    try:
        handle_pending_message(cardinal, event, {"smm"})
    except Exception as ex:
        logger.debug("[AutoSMM] msg: %s", ex)


def init_settings(cardinal):
    def status():
        cfg = load_smm_config()
        url = cfg["Settings"].get("api_url", "—") if cfg.has_section("Settings") else "—"
        lots = len(cfg["Lots"]) if cfg.has_section("Lots") else 0
        return f"API: <code>{url}</code>\nПравил лотов: <b>{lots}</b>\nКлюч — в configs/autosmm.cfg"

    SettingsPage(UUID, NAME, "Перепродажа SMM. Лоты и ключ — configs/autosmm.cfg.") \
        .add_toggle("enabled", "AutoSMM",
                    lambda: ini_bool(CONFIG_FILE, "Settings", "enabled", False),
                    lambda _v: flip_ini(CONFIG_FILE, "Settings", "enabled", False)) \
        .set_status(status) \
        .attach(cardinal)


BIND_TO_PRE_INIT = [init_settings]
BIND_TO_NEW_ORDER = [on_order_smm]
BIND_TO_NEW_MESSAGE = [on_smm_message]
