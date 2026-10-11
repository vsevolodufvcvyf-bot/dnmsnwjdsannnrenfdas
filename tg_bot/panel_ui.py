# -*- coding: utf-8 -*-
"""Пульт nnanserShop: простой, на русском, кнопки внизу чата."""
from __future__ import annotations

import html
import logging

from telebot.types import (
    InlineKeyboardMarkup as K,
    InlineKeyboardButton as B,
    ReplyKeyboardMarkup,
    KeyboardButton,
    Message,
)
from tg_bot import CBT

logger = logging.getLogger("TGBot.Panel")

BTN_HOME = "🏠 Главная"
BTN_PRICE = "📈 Цена"
BTN_STOCK = "📦 Склад"
BTN_BAL = "💰 Кошелёк"
BTN_CHECK = "🔍 Проверка"
BTN_APR = "⚖️ Автоцена"
BTN_PANIC = "🛑 Стоп"
BTN_OK = "▶️ В работу"
BTN_DRY = "🧪 Учёба"
BTN_MORE = "📂 Ещё"
BTN_STATS = "📊 Статы"

HR = "━━━━━━━━━━━━━━━━"


def all_reply_labels() -> set[str]:
    return {
        BTN_HOME, BTN_PRICE, BTN_STOCK, BTN_BAL, BTN_CHECK, BTN_APR,
        BTN_PANIC, BTN_OK, BTN_DRY, BTN_MORE, BTN_STATS,
    }


def reply_keyboard() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    kb.row(KeyboardButton(BTN_HOME), KeyboardButton(BTN_BAL), KeyboardButton(BTN_APR))
    kb.row(KeyboardButton(BTN_CHECK), KeyboardButton(BTN_PRICE), KeyboardButton(BTN_MORE))
    return kb


def clear_all_waits(uid: int) -> None:
    for mod, attr in (
        ("plugins.market_analyzer", "clear_wait"),
        ("plugins.shop_desk", "clear_wait"),
        ("plugins.balance_monitor", "clear_wait"),
        ("plugins.trade_methods", "clear_wait"),
    ):
        try:
            m = __import__(mod, fromlist=[attr])
            getattr(m, attr)(uid)
        except Exception:
            pass


def home_text(cardinal) -> str:
    try:
        from shop_core.settings import is_dry_run, is_panic
        from shop_core.bus import is_frozen, get_flag
    except Exception:
        is_dry_run = lambda: False
        is_panic = lambda: False
        is_frozen = lambda: False
        get_flag = lambda *_a, **_k: ""

    acc = getattr(cardinal, "account", None)
    name = html.escape(str(getattr(acc, "username", "—") or "—"))
    uid = getattr(acc, "id", "—")
    bal = getattr(cardinal, "balance", None)
    try:
        rub = float(getattr(bal, "total_rub", 0) or 0) if bal else 0.0
    except (TypeError, ValueError):
        rub = 0.0
    try:
        avail = float(getattr(bal, "available_rub", 0) or 0) if bal else 0.0
    except (TypeError, ValueError):
        avail = 0.0
    sales = getattr(acc, "active_sales", 0) if acc else 0
    freeze_reason = html.escape(str(get_flag("freeze_reason", "") or "—"))
    panic_on = is_panic()
    dry_on = is_dry_run()
    frozen = is_frozen()
    n_lots = 0
    profile = getattr(cardinal, "profile", None)
    try:
        if profile:
            n_lots = len(profile.get_sorted_lots(1) or {})
    except Exception:
        n_lots = 0
    banned = bool(getattr(profile, "banned", False))
    if banned:
        badge = "🔴  FunPay заблокировал аккаунт — витрина недоступна"
    elif panic_on:
        badge = "🔴  стоп — закупки и выдача выключены"
    elif dry_on:
        badge = "🟡  учёба — поставщику деньги не уходят"
    elif frozen:
        badge = f"🔴  FunPay заморожен · <code>{freeze_reason}</code>"
    else:
        badge = "🟢  магазин в работе"
    apr = "выкл"
    try:
        from shop_core.settings import ini_bool
        apr = "вкл" if ini_bool("configs/autoprice.cfg", "AutoPrice", "enabled", True) else "выкл"
    except Exception:
        logger.debug("TRACEBACK", exc_info=True)
    return (
        f"<b>nnanserShop</b>\n"
        f"{HR}\n"
        f"{badge}\n\n"
        f"👤  {name}   <code>#{uid}</code>\n"
        f"💰  <b>{rub:.0f}</b> ₽    к выводу  {avail:.0f} ₽\n"
        f"📦  лотов  <b>{n_lots}</b>    сделки  {sales}\n"
        f"⚖️  автоцена  <b>{apr}</b>\n\n"
        f"<i>Автоцена двигает лоты под рынок и оставляет плюс. "
        f"Микролоты 5–10 ₽ не трогает. ИИ не зовёт из‑за «кода».</i>"
    )


def home_kb(cardinal) -> K:
    kb = K()
    kb.row(B("·  деньги  ·", callback_data=CBT.EMPTY))
    kb.row(B("💰 Кошелёк", callback_data="PANEL:bal"), B("💸 Вывод", callback_data="WAL:out"))
    kb.row(B("·  витрина  ·", callback_data=CBT.EMPTY))
    kb.row(B("⚖️ Автоцена", callback_data="APR:hub"), B("📈 Цена рынка", callback_data="PANEL:price"))
    kb.row(B("📝 Микролоты", callback_data="MICRO:hub"), B("📦 Склад", callback_data="PANEL:stock"))
    kb.row(B("·  поставка  ·", callback_data=CBT.EMPTY))
    kb.row(B("⭐ Stars", callback_data="STAR:hub"), B("🎁 Подарки", callback_data="GIFT:hub"))
    kb.row(B("🔌 Панель API", callback_data="SHOP:wiz"), B("🚚 Схемы", callback_data="METH:hub"))
    kb.row(B("🔍 Проверка", callback_data="CHECK:run"), B("📖 Как настроить", callback_data="CHECK:how"))
    kb.row(B("🛑 Стоп", callback_data="PANEL:panic"), B("▶️ В работу", callback_data="PANEL:live"))
    kb.row(B("👥 Команда", callback_data="SHOP:team"), B("⚙️ Ещё", callback_data=CBT.MAIN))
    return kb


def settings_page1() -> K:
    kb = K()
    kb.row(B("🗣️ Язык", callback_data=f"{CBT.CATEGORY}:lang"), B("⚙️ Глобальные", callback_data=f"{CBT.CATEGORY}:main"))
    kb.row(B("🔔 Уведомления", callback_data=f"{CBT.CATEGORY}:tg"), B("🤖 Автоответ", callback_data=f"{CBT.CATEGORY}:ar"))
    kb.row(B("📦 Автовыдача", callback_data=f"{CBT.CATEGORY}:ad"), B("🧩 Плагины", callback_data=f"{CBT.PLUGINS_LIST}:0"))
    kb.row(B("📝 Заготовки", callback_data=f"{CBT.TMPLT_LIST}:0"), B("▶️ Ещё", callback_data=CBT.MAIN2))
    kb.row(B("🏠 На главную", callback_data="PANEL:home"))
    return kb


def settings_page2() -> K:
    kb = K()
    kb.row(B("👋 Приветствие", callback_data=f"{CBT.CATEGORY}:gr"), B("✅ Подтверждение", callback_data=f"{CBT.CATEGORY}:oc"))
    kb.row(B("⭐ Отзывы", callback_data=f"{CBT.CATEGORY}:rr"), B("✉️ Вид сообщений", callback_data=f"{CBT.CATEGORY}:mv"))
    kb.row(B("🚫 Чёрный список", callback_data=f"{CBT.CATEGORY}:bl"), B("📁 Конфиги", callback_data=CBT.CONFIG_LOADER))
    kb.row(B("👥 Доступ TG", callback_data=f"{CBT.AUTHORIZED_USERS}:0"), B("🌐 Прокси", callback_data=f"{CBT.PROXY}:0"))
    kb.row(B("◀️ Назад", callback_data=CBT.MAIN), B("🏠 Главная", callback_data="PANEL:home"))
    return kb


def send_home(tg, m: Message) -> None:
    clear_all_waits(m.from_user.id)
    tg.bot.send_message(m.chat.id, "клавиатура внизу — кошелёк · автоцена · проверка", reply_markup=reply_keyboard())
    tg.bot.send_message(
        m.chat.id,
        home_text(tg.cardinal),
        reply_markup=home_kb(tg.cardinal),
        disable_web_page_preview=True,
        parse_mode="HTML",
    )
