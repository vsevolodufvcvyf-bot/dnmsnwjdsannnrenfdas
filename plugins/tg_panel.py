# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import logging

from dotenv import load_dotenv
from telebot.types import Message, CallbackQuery

from tg_bot import utils as tg_utils
from tg_bot.panel_ui import (
    BTN_APR, BTN_BAL, BTN_CHECK, BTN_DRY, BTN_HOME, BTN_MORE, BTN_OK, BTN_PANIC, BTN_PRICE, BTN_STATS, BTN_STOCK,
    home_kb, home_text, reply_keyboard, send_home,
)
from plugins._common.settings import is_dry_run, set_flag
from plugins._common.plugin_settings import SettingsPage
from plugins._common.bus import freeze, unfreeze

load_dotenv()

logger = logging.getLogger("FPC.TgPanel")

NAME = "Пульт nnanserShop"
VERSION = "2.0.0"
DESCRIPTION = "Простой пульт: цена рынка, склад, стоп, кнопки внизу чата"
CREDITS = "nnanserShop"
UUID = "d11e0001-4444-4a11-8e01-000000000011"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}
_READY = False


def _owner_id() -> int | None:
    raw = os.getenv("TELEGRAM_OWNER_ID", "").strip()
    return int(raw) if raw.isdigit() else None


def _auth_owner(cardinal) -> None:
    tg = getattr(cardinal, "telegram", None)
    oid = _owner_id()
    if not tg or oid is None:
        return
    if oid not in tg.authorized_users:
        tg.authorized_users[oid] = {}
        tg_utils.save_authorized_users(tg.authorized_users)
        logger.info("[TgPanel] owner %s добавлен в authorized_users", oid)
    chat = str(oid)
    if chat not in tg.notification_settings:
        tg.notification_settings[chat] = {
            tg_utils.NotificationTypes.bot_start: True,
            tg_utils.NotificationTypes.new_message: True,
            tg_utils.NotificationTypes.new_order: True,
            tg_utils.NotificationTypes.critical: True,
            tg_utils.NotificationTypes.other: True,
        }
        tg_utils.save_notification_settings(tg.notification_settings)


def _ok(cardinal, uid: int) -> bool:
    tg = cardinal.telegram
    return uid in getattr(tg, "authorized_users", {})


def init_settings(cardinal):
    SettingsPage(UUID, NAME, "Пульт nnanserShop: /menu и кнопки внизу чата.") \
        .set_status(lambda: "Команды: /menu /price /stock /balances /panic") \
        .attach(cardinal)
    cardinal.add_telegram_commands(UUID, [
        ("menu", "пульт продавца", True),
        ("panel", "пульт продавца", True),
        ("panic", "аварийный стоп закупок", True),
        ("unpanic", "снять аварийный стоп", True),
        ("dryrun", "учебный режим (без закупок)", True),
    ])


def init_pre(cardinal):
    global _READY
    _auth_owner(cardinal)
    init_settings(cardinal)
    tg = getattr(cardinal, "telegram", None)
    if not tg or not getattr(tg, "bot", None) or _READY:
        return
    _READY = True
    bot = tg.bot

    @bot.message_handler(func=lambda m: bool(m.text) and m.text.strip() == BTN_HOME)
    def _home(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        send_home(tg, m)

    @bot.message_handler(func=lambda m: bool(m.text) and m.text.strip() == BTN_MORE)
    def _more(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        from tg_bot.panel_ui import settings_page1
        bot.send_message(m.chat.id, "📂 Настройки магазина — выбери раздел.", reply_markup=settings_page1())

    @bot.message_handler(func=lambda m: bool(m.text) and m.text.strip() == BTN_STATS)
    def _stats(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        try:
            from plugins.ops_core import _stats_text
            bot.send_message(m.chat.id, _stats_text(cardinal), parse_mode="HTML")
        except Exception as ex:
            bot.send_message(m.chat.id, f"Статы недоступны: {ex}")

    @bot.message_handler(func=lambda m: bool(m.text) and m.text.strip() == BTN_PRICE)
    def _price(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        from plugins.market_analyzer import ask_price
        ask_price(bot, m.chat.id, m.from_user.id)

    @bot.message_handler(func=lambda m: bool(m.text) and m.text.strip() == BTN_STOCK)
    def _stock(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        try:
            from plugins.auto_restock import stock_text
            bot.send_message(m.chat.id, stock_text(cardinal), parse_mode="HTML")
        except Exception as ex:
            bot.send_message(m.chat.id, f"Склад недоступен: {ex}")

    @bot.message_handler(func=lambda m: bool(m.text) and m.text.strip() == BTN_BAL)
    def _bal(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        try:
            from plugins.balance_monitor import send_wallet
            send_wallet(bot, m.chat.id, cardinal)
        except Exception as ex:
            bot.send_message(m.chat.id, f"Кошелёк недоступен: {ex}")

    @bot.message_handler(func=lambda m: bool(m.text) and m.text.strip() == BTN_CHECK)
    def _check(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        try:
            from plugins.clinic import report_kb, report_text
            bot.send_message(m.chat.id, report_text(cardinal), reply_markup=report_kb(), parse_mode="HTML")
        except Exception as ex:
            bot.send_message(m.chat.id, f"Проверка недоступна: {ex}")

    @bot.message_handler(func=lambda m: bool(m.text) and m.text.strip() == BTN_APR)
    def _apr(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        try:
            from plugins.auto_price import hub_kb, hub_text
            bot.send_message(m.chat.id, hub_text(cardinal), reply_markup=hub_kb(), parse_mode="HTML")
        except Exception as ex:
            bot.send_message(m.chat.id, f"Автоцена недоступна: {ex}")

    @bot.message_handler(func=lambda m: bool(m.text) and m.text.strip() == BTN_PANIC)
    def _panic(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        set_flag("Ops", "panic", "1")
        freeze("аварийный стоп", cardinal)
        bot.send_message(
            m.chat.id,
            "🛑 <b>Аварийный стоп включён</b>\nБот больше не закупает, не выдаёт товар и не шлёт автоответы.",
            parse_mode="HTML",
        )

    @bot.message_handler(func=lambda m: bool(m.text) and m.text.strip() == BTN_OK)
    def _live(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        set_flag("Ops", "panic", "0")
        unfreeze()
        bot.send_message(m.chat.id, "▶️ Стоп снят. Бот снова в работе.")

    @bot.message_handler(func=lambda m: bool(m.text) and m.text.strip() == BTN_DRY)
    def _dry_btn(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        set_flag("Ops", "dry_run", "0" if is_dry_run() else "1")
        bot.send_message(
            m.chat.id,
            "🧪 <b>Учебный режим ВКЛ</b>\nЗаказы пишутся в журнал, поставщику ничего не уходит."
            if is_dry_run() else
            "🧪 <b>Учебный режим ВЫКЛ</b>\nЗакупки снова настоящие.",
            parse_mode="HTML",
        )

    def _redraw_home(c: CallbackQuery) -> None:
        try:
            bot.edit_message_text(
                home_text(cardinal),
                c.message.chat.id,
                c.message.id,
                reply_markup=home_kb(cardinal),
                parse_mode="HTML",
            )
        except Exception:
            pass

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("PANEL:"))
    def _cb(c: CallbackQuery):
        if not _ok(cardinal, c.from_user.id):
            return
        action = c.data.split(":", 1)[1]
        if action == "home":
            _redraw_home(c)
        elif action == "stats":
            from plugins.ops_core import _stats_text
            bot.send_message(c.message.chat.id, _stats_text(cardinal), parse_mode="HTML")
        elif action == "price":
            from plugins.market_analyzer import ask_price
            ask_price(bot, c.message.chat.id, c.from_user.id)
        elif action == "stock":
            from plugins.auto_restock import stock_text
            bot.send_message(c.message.chat.id, stock_text(cardinal), parse_mode="HTML")
        elif action == "bal":
            from plugins.balance_monitor import send_wallet
            send_wallet(bot, c.message.chat.id, cardinal)
        elif action == "panic":
            set_flag("Ops", "panic", "1")
            freeze("аварийный стоп", cardinal)
            bot.answer_callback_query(
                c.id,
                "Аварийный стоп: бот не закупает и не выдаёт товар.",
                show_alert=True,
            )
            _redraw_home(c)
            return
        elif action == "live":
            set_flag("Ops", "panic", "0")
            unfreeze()
            bot.answer_callback_query(c.id, "Стоп снят. Бот снова в работе.", show_alert=True)
            _redraw_home(c)
            return
        elif action == "dry":
            set_flag("Ops", "dry_run", "0" if is_dry_run() else "1")
            bot.answer_callback_query(
                c.id,
                "Учебный режим ВКЛ: поставщику ничего не уходит." if is_dry_run()
                else "Учебный режим ВЫКЛ: закупки настоящие.",
                show_alert=True,
            )
            _redraw_home(c)
            return
        elif action == "market":
            bot.send_message(
                c.message.chat.id,
                "📈 <b>Витрина</b>\nКоманда: /market ID_категории себестоимость\nПример: <code>/market 209 120</code>",
                parse_mode="HTML",
            )
        try:
            bot.answer_callback_query(c.id)
        except Exception:
            pass


def init_post(cardinal):
    _auth_owner(cardinal)
    tg = getattr(cardinal, "telegram", None)
    try:
        from plugins._common.team import bootstrap
        if tg:
            bootstrap(tg)
    except Exception as ex:
        logger.debug("[TgPanel] team bootstrap: %s", ex)
    oid = _owner_id()
    if not tg or oid is None:
        return
    try:
        tg.bot.send_message(oid, home_text(cardinal), reply_markup=home_kb(cardinal), parse_mode="HTML")
        tg.bot.send_message(oid, "⌨️ Кошелёк · проверка · цена — кнопки внизу.", reply_markup=reply_keyboard())
    except Exception as ex:
        logger.debug("[TgPanel] welcome: %s", ex)


BIND_TO_PRE_INIT = [init_pre]
BIND_TO_POST_START = [init_post]
