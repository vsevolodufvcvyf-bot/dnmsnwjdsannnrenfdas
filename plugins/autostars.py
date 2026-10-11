# -*- coding: utf-8 -*-
"""Stars: спросил @username, сверил, закупил у своей API-панели. Fragment-cookie не нужны."""
from __future__ import annotations

import html
import logging
from threading import Thread

from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, CallbackQuery, Message

from shop_core.bus import bot_send, is_frozen, notify
from shop_core.confirm import (
    ask_confirm, ask_target, handle_pending_message, parse_qty, parse_username, put_pending,
)
from shop_core.panels import load_suppliers_cfg
from shop_core.plugin_settings import SettingsPage
from shop_core.settings import ini_bool, is_dry_run, is_panic, set_ini

logger = logging.getLogger("FPC.AutoStars")

NAME = "AutoStars"
VERSION = "1.0.0"
DESCRIPTION = "После оплаты спрашивает @username, сверяет и шлёт звёзды через твою API-панель"
CREDITS = "nnanserShop"
UUID = "a7b3c901-4e2f-4a18-9d6c-2f8e1b5a7c90"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}
CONFIG_FILE = "configs/suppliers.cfg"
_READY = False
_KEYS = ("stars", "звезд", "телеграм стар", "tg stars", "telegram stars")


def _ok(cardinal, uid: int) -> bool:
    tg = getattr(cardinal, "telegram", None)
    return bool(tg) and uid in getattr(tg, "authorized_users", {})


def _enabled() -> bool:
    return ini_bool(CONFIG_FILE, "stars", "enabled", False)


def is_stars_lot(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in _KEYS)


def _panel_status() -> dict:
    cfg = load_suppliers_cfg()
    sec = cfg["stars"] if cfg.has_section("stars") else {}
    url = (sec.get("api_url") or "").strip()
    key = (sec.get("api_key") or "").strip()
    sid = (sec.get("service_id") or "").strip()
    return {
        "enabled": _enabled(),
        "url": bool(url),
        "key": bool(key),
        "sid": bool(sid),
        "ok": bool(url and key and sid),
    }


def check_lines() -> list[str]:
    st = _panel_status()
    return [
        ("✅" if st["enabled"] else "❌") + " плагин включён",
        ("✅" if st["url"] else "❌") + " API URL панели",
        ("✅" if st["key"] else "❌") + " API-ключ",
        ("✅" if st["sid"] else "❌") + " service_id услуги Stars",
        "🧪 учебный режим — деньги панели не уйдут" if is_dry_run() else "✅ живая закупка",
    ]


def hub_text() -> str:
    st = _panel_status()
    lines = [
        "⭐ <b>AutoStars</b>",
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
        "Как в ролике: покупатель пишет @username → бот спрашивает «верно?» → "
        "закупает звёзды у <b>твоей</b> API-панели (PerfectPanel / аналог).",
        "Fragment-cookie и сид TON не нужны и не храним.",
        "",
        "Сейчас: <b>" + ("вкл" if st["enabled"] else "выкл") + "</b>",
        "",
        "<b>Проверка настроек</b>",
        *check_lines(),
    ]
    if not st["ok"]:
        lines.append("")
        lines.append("Допиши URL, ключ и service_id в «🔌 Панель» → Stars.")
    return "\n".join(lines)


def hub_kb() -> K:
    kb = K()
    on = _enabled()
    kb.row(B("⏸ Выкл" if on else "▶️ Вкл", callback_data="STAR:tog"), B("🔎 Проверить", callback_data="STAR:check"))
    kb.row(B("🧪 Тест-заказ", callback_data="STAR:test"), B("🔌 Панель", callback_data="SHOP:wiz"))
    kb.row(B("🏠 Главная", callback_data="PANEL:home"))
    return kb


def on_order(cardinal, event):
    armed = _arm_order(cardinal, event)
    if armed:
        Thread(target=_ask_after_arm, args=(cardinal, armed), daemon=True).start()


def _arm_order(cardinal, event):
    try:
        if not _enabled():
            return None
        paused = is_panic() or is_frozen()
        order = getattr(event, "order", None)
        if not order:
            return None
        desc = (getattr(order, "description", "") or getattr(order, "title", "") or "")
        if not is_stars_lot(desc):
            return None
        chat_id = getattr(order, "chat_id", None)
        if not chat_id:
            return None
        qty = parse_qty(desc, getattr(order, "amount", 1) or 1)
        sale = float(getattr(order, "price", 0) or 0)
        oid = str(getattr(order, "id", ""))
        user = parse_username(desc)
        extra = {"query": desc or "telegram stars"}
        if paused:
            extra["paused"] = 1
        name = getattr(order, "buyer_username", None)
        buyer = getattr(order, "buyer_id", None)
        if user:
            status = put_pending(chat_id, oid, "stars", "confirm", user, qty, sale, extra,
                                 cardinal=cardinal, peer_id=buyer)
            if status == "fail":
                return None
            if paused:
                return {"chat_id": chat_id, "name": name, "user": user, "mode": "paused", "order_id": oid}
            if status == "queued":
                return {"chat_id": chat_id, "name": name, "user": user, "mode": "queued"}
            return {"chat_id": chat_id, "name": name, "user": user, "mode": "confirm"}
        status = put_pending(chat_id, oid, "stars", "need_target", "", qty, sale, extra,
                             cardinal=cardinal, peer_id=buyer)
        if status == "fail":
            return None
        if paused:
            return {"chat_id": chat_id, "name": name, "user": None, "mode": "paused", "order_id": oid}
        if status == "queued":
            return {"chat_id": chat_id, "name": name, "user": None, "mode": "queued"}
        return {"chat_id": chat_id, "name": name, "user": None, "mode": "need"}
    except Exception as ex:
        logger.error("[AutoStars] order: %s", ex)
        return None


def _ask_after_arm(cardinal, armed):
    try:
        if armed["mode"] == "paused":
            notify(
                cardinal,
                f"⏸ Stars #{armed.get('order_id')}: заказ пришёл на стопе (panic/freeze). "
                f"Запрос сохранён, покупателю пока не писал. Ник: <code>{armed.get('user') or '—'}</code>",
                True,
            )
            return
        if armed["mode"] == "queued":
            from shop_core.confirm import ask_queued
            ask_queued(cardinal, armed["chat_id"], armed["name"])
            return
        if armed["mode"] == "confirm":
            ask_confirm(cardinal, armed["chat_id"], "stars", armed["user"], armed["name"])
        else:
            bot_send(cardinal, armed["chat_id"], "Заказ на звёзды принят.", armed["name"])
            ask_target(cardinal, armed["chat_id"], "stars", armed["name"])
    except Exception as ex:
        logger.error("[AutoStars] ask: %s", ex)


def on_message(cardinal, event):
    try:
        handle_pending_message(cardinal, event, {"stars"})
    except Exception as ex:
        logger.debug("[AutoStars] msg: %s", ex)


def init_pre(cardinal):
    global _READY
    SettingsPage(UUID, NAME, "Звёзды: спросил ник → сверил → панель. Ключ в «🔌 Панель».") \
        .add_toggle("enabled", "AutoStars", _enabled,
                    lambda _v: set_ini(CONFIG_FILE, "stars", "enabled", "0" if _enabled() else "1")) \
        .set_status(lambda: "\n".join(check_lines())) \
        .attach(cardinal)
    cardinal.add_telegram_commands(UUID, [("stars", "автовыдача Stars", True)])
    tg = getattr(cardinal, "telegram", None)
    if not tg or not getattr(tg, "bot", None) or _READY:
        return
    _READY = True
    bot = tg.bot

    @bot.message_handler(commands=["stars", "autostars"])
    def cmd(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        bot.send_message(m.chat.id, hub_text(), reply_markup=hub_kb(), parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("STAR:"))
    def cb(c: CallbackQuery):
        if not _ok(cardinal, c.from_user.id):
            return
        action = (c.data or "STAR:hub").split(":")[1]
        try:
            bot.answer_callback_query(c.id)
        except Exception:
            pass
        if action == "tog":
            set_ini(CONFIG_FILE, "stars", "enabled", "0" if _enabled() else "1")
        if action == "test":
            st = _panel_status()
            if not st["ok"]:
                txt = "❌ Тест не прошёл — сначала URL, ключ и service_id в «🔌 Панель»."
            else:
                txt = (
                    "✅ Настройки на месте. Реальные звёзды не покупались.\n"
                    "Как только будет оплаченный лот со словом «stars»/«звёзды», "
                    "бот спросит @username и после «да» уйдёт на панель"
                    + (" (учебный режим — без списания)." if is_dry_run() else ".")
                )
            bot.send_message(c.message.chat.id, txt)
            return
        try:
            bot.edit_message_text(hub_text(), c.message.chat.id, c.message.id,
                                  reply_markup=hub_kb(), parse_mode="HTML")
        except Exception:
            bot.send_message(c.message.chat.id, hub_text(), reply_markup=hub_kb(), parse_mode="HTML")
        _ = html


BIND_TO_PRE_INIT = [init_pre]
BIND_TO_NEW_ORDER = [on_order]
BIND_TO_NEW_MESSAGE = [on_message]
