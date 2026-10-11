# -*- coding: utf-8 -*-
"""Подарки Telegram: спросил @username, сверил, заказал у своей API-панели."""
from __future__ import annotations

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

logger = logging.getLogger("FPC.AutoGift")

NAME = "AutoGift"
VERSION = "1.0.0"
DESCRIPTION = "После оплаты спрашивает @username и отправляет подарок через твою API-панель"
CREDITS = "nnanserShop"
UUID = "b8c4d012-5f3a-4b29-8e7d-3a9f2c6b8d01"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}
CONFIG_FILE = "configs/suppliers.cfg"
_READY = False
_KEYS = ("подарок", "подарк", "gift", "teddy", "медвед", "trophy", "кубок")


def _ok(cardinal, uid: int) -> bool:
    tg = getattr(cardinal, "telegram", None)
    return bool(tg) and uid in getattr(tg, "authorized_users", {})


def _enabled() -> bool:
    return ini_bool(CONFIG_FILE, "gifts", "enabled", False)


def is_gift_lot(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in _KEYS)


def _panel_ok() -> bool:
    cfg = load_suppliers_cfg()
    sec = cfg["gifts"] if cfg.has_section("gifts") else {}
    return bool((sec.get("api_url") or "").strip() and (sec.get("api_key") or "").strip()
                and (sec.get("service_id") or "").strip())


def check_lines() -> list[str]:
    cfg = load_suppliers_cfg()
    sec = cfg["gifts"] if cfg.has_section("gifts") else {}
    return [
        ("✅" if _enabled() else "❌") + " плагин включён",
        ("✅" if (sec.get("api_url") or "").strip() else "❌") + " API URL",
        ("✅" if (sec.get("api_key") or "").strip() else "❌") + " API-ключ",
        ("✅" if (sec.get("service_id") or "").strip() else "❌") + " service_id подарка",
        "🧪 учебный режим" if is_dry_run() else "✅ живая закупка",
    ]


def hub_text() -> str:
    return (
        "🎁 <b>AutoGift</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        "Как в ролике: бот спрашивает, верно ли @username, и после «да» "
        "заказывает подарок у твоей панели. Чужие Telegram-аккаунты не подключаем.\n\n"
        "Сейчас: <b>" + ("вкл" if _enabled() else "выкл") + "</b>\n\n"
        "<b>Проверка</b>\n" + "\n".join(check_lines())
    )


def hub_kb() -> K:
    kb = K()
    kb.row(
        B("⏸ Выкл" if _enabled() else "▶️ Вкл", callback_data="GIFT:tog"),
        B("🔎 Проверить", callback_data="GIFT:check"),
    )
    kb.row(B("🧪 Тест", callback_data="GIFT:test"), B("🔌 Панель", callback_data="SHOP:wiz"))
    kb.row(B("🏠 Главная", callback_data="PANEL:home"))
    return kb


def _arm_order(cardinal, event):
    try:
        if not _enabled():
            return None
        paused = is_panic() or is_frozen()
        order = getattr(event, "order", None)
        if not order:
            return None
        desc = (getattr(order, "description", "") or getattr(order, "title", "") or "")
        if not is_gift_lot(desc) or is_stars_overlap(desc):
            return None
        chat_id = getattr(order, "chat_id", None)
        if not chat_id:
            return None
        qty = parse_qty(desc, getattr(order, "amount", 1) or 1)
        sale = float(getattr(order, "price", 0) or 0)
        oid = str(getattr(order, "id", ""))
        user = parse_username(desc)
        extra = {"query": desc or "telegram gift"}
        if paused:
            extra["paused"] = 1
        name = getattr(order, "buyer_username", None)
        buyer = getattr(order, "buyer_id", None)
        if user:
            status = put_pending(chat_id, oid, "gift", "confirm", user, qty, sale, extra,
                                 cardinal=cardinal, peer_id=buyer)
            if status == "fail":
                return None
            if paused:
                return {"chat_id": chat_id, "name": name, "user": user, "mode": "paused", "order_id": oid}
            if status == "queued":
                return {"chat_id": chat_id, "name": name, "user": user, "mode": "queued"}
            return {"chat_id": chat_id, "name": name, "user": user, "mode": "confirm"}
        status = put_pending(chat_id, oid, "gift", "need_target", "", qty, sale, extra,
                             cardinal=cardinal, peer_id=buyer)
        if status == "fail":
            return None
        if paused:
            return {"chat_id": chat_id, "name": name, "user": None, "mode": "paused", "order_id": oid}
        if status == "queued":
            return {"chat_id": chat_id, "name": name, "user": None, "mode": "queued"}
        return {"chat_id": chat_id, "name": name, "user": None, "mode": "need"}
    except Exception as ex:
        logger.error("[AutoGift] order: %s", ex)
        return None


def _ask_after_arm(cardinal, armed):
    try:
        if armed["mode"] == "paused":
            notify(
                cardinal,
                f"⏸ Gift #{armed.get('order_id')}: заказ пришёл на стопе (panic/freeze). "
                f"Запрос сохранён, покупателю пока не писал. Ник: <code>{armed.get('user') or '—'}</code>",
                True,
            )
            return
        if armed["mode"] == "queued":
            from shop_core.confirm import ask_queued
            ask_queued(cardinal, armed["chat_id"], armed["name"])
            return
        if armed["mode"] == "confirm":
            ask_confirm(cardinal, armed["chat_id"], "gift", armed["user"], armed["name"])
        else:
            bot_send(cardinal, armed["chat_id"], "Заказ на подарок принят.", armed["name"])
            ask_target(cardinal, armed["chat_id"], "gift", armed["name"])
    except Exception as ex:
        logger.error("[AutoGift] ask: %s", ex)


def is_stars_overlap(desc: str) -> bool:
    t = (desc or "").lower()
    return "звезд" in t or "stars" in t


def on_order(cardinal, event):
    armed = _arm_order(cardinal, event)
    if armed:
        Thread(target=_ask_after_arm, args=(cardinal, armed), daemon=True).start()


def on_message(cardinal, event):
    try:
        handle_pending_message(cardinal, event, {"gift"})
    except Exception as ex:
        logger.debug("[AutoGift] msg: %s", ex)


def init_pre(cardinal):
    global _READY
    SettingsPage(UUID, NAME, "Подарки Telegram через твою панель. Ник → «да» → выдача.") \
        .add_toggle("enabled", "AutoGift", _enabled,
                    lambda _v: set_ini(CONFIG_FILE, "gifts", "enabled", "0" if _enabled() else "1")) \
        .set_status(lambda: "\n".join(check_lines())) \
        .attach(cardinal)
    cardinal.add_telegram_commands(UUID, [("gifts", "автоподарки Telegram", True)])
    tg = getattr(cardinal, "telegram", None)
    if not tg or not getattr(tg, "bot", None) or _READY:
        return
    _READY = True
    bot = tg.bot

    @bot.message_handler(commands=["gifts", "autogift"])
    def cmd(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        bot.send_message(m.chat.id, hub_text(), reply_markup=hub_kb(), parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("GIFT:"))
    def cb(c: CallbackQuery):
        if not _ok(cardinal, c.from_user.id):
            return
        action = (c.data or "GIFT:hub").split(":")[1]
        try:
            bot.answer_callback_query(c.id)
        except Exception:
            pass
        if action == "tog":
            set_ini(CONFIG_FILE, "gifts", "enabled", "0" if _enabled() else "1")
        if action == "test":
            txt = (
                "✅ Тест: ник спросит, звёзды/подарок не спишет."
                if _panel_ok() else
                "❌ Нет URL/ключа/service_id в секции gifts. «🔌 Панель»."
            )
            bot.send_message(c.message.chat.id, txt)
            return
        try:
            bot.edit_message_text(hub_text(), c.message.chat.id, c.message.id,
                                  reply_markup=hub_kb(), parse_mode="HTML")
        except Exception:
            bot.send_message(c.message.chat.id, hub_text(), reply_markup=hub_kb(), parse_mode="HTML")


BIND_TO_PRE_INIT = [init_pre]
BIND_TO_NEW_ORDER = [on_order]
BIND_TO_NEW_MESSAGE = [on_message]
