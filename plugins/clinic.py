# -*- coding: utf-8 -*-
"""Автопроверка магазина: что сломано, чего не хватает, когда звать человека."""
from __future__ import annotations

import html
import logging
import os
import time
from datetime import datetime
from threading import Thread

from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, Message, CallbackQuery

from shop_core.bus import get_flag, is_frozen, notify, set_flag
from shop_core.panels import load_suppliers_cfg
from shop_core.plugin_settings import SettingsPage
from shop_core.settings import is_dry_run, is_panic, min_margin_mult

logger = logging.getLogger("FPC.Clinic")

NAME = "Проверка магазина"
VERSION = "1.0.0"
DESCRIPTION = "Сканирует плагины, панели, лоты и пишет, только если нужно твоё действие"
CREDITS = "nnanserShop"
UUID = "d1e45f80-7b4c-4d29-9a16-3c8e0b5f6789"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}
_READY = False
_LAST_PING = ""


def _ok(cardinal, uid: int) -> bool:
    tg = getattr(cardinal, "telegram", None)
    return bool(tg) and uid in getattr(tg, "authorized_users", {})


def parse_issue_lines(now: float | None = None, window: float = 86400) -> list[str]:
    """Пропуски при разборе страниц FunPay за сутки — первый признак смены вёрстки."""
    import time
    from datetime import datetime
    try:
        from FunPayAPI.account import PARSE_ISSUES
    except Exception:
        return []
    now = time.time() if now is None else now
    out = []
    for what, (ts, skipped, total) in sorted(PARSE_ISSUES.items()):
        if now - ts <= window:
            out.append(f"FunPay: не разобрал {skipped} из {total} ({what}, {datetime.fromtimestamp(ts):%H:%M}). "
                       f"Похоже, FunPay поменял вёрстку — нужны правки из свежего FunPay Cardinal.")
    return out


def scan(cardinal) -> tuple[list[str], list[str], list[str]]:
    """ok, warn, critical — без секретов."""
    ok, warn, bad = [], [], []
    acc = getattr(cardinal, "account", None)
    cfg = getattr(cardinal, "MAIN_CFG", None)

    key_ok = False
    try:
        key_ok = bool((cfg["FunPay"].get("golden_key") or "").strip()) if cfg else False
    except Exception:
        pass
    if key_ok:
        ok.append("Сессия FunPay: ключ на месте")
    else:
        bad.append("Нет golden_key в configs/_main.cfg — бот не зайдёт на FunPay")
    for line in parse_issue_lines():
        warn.append(line)
    try:
        if cfg and cfg.has_section("Proxy") and cfg["Proxy"].getboolean("enable", fallback=False):
            ok.append("Прокси для FunPay включён")
        elif cfg:
            warn.append("Прокси для FunPay выключен. Отдельный прокси снижает риск блокировки "
                        "за «подозрительную активность» с одного IP.")
    except Exception:
        logger.debug("TRACEBACK", exc_info=True)

    if is_frozen():
        bad.append(f"FunPay заморожен: {get_flag('freeze_reason') or 'причина не записана'}")
    else:
        ok.append("Заморозки сессии нет")
    if is_panic():
        bad.append("Аварийный стоп включён — закупки и выдача стоят. Нажми «▶️ В работу».")
    if is_dry_run():
        warn.append("Учебный режим: поставщику деньги не уходят")

    n_lots = 0
    profile = getattr(cardinal, "profile", None)
    try:
        if profile:
            n_lots = len(profile.get_sorted_lots(1) or {})
    except Exception:
        n_lots = 0
    if getattr(profile, "banned", False):
        bad.append(
            "FunPay заблокировал этот аккаунт. Витрина и продажи недоступны, "
            "пока FunPay не снимет блок (или нужен другой golden_key)."
        )
    elif n_lots:
        ok.append(f"Лотов на витрине: {n_lots}")
    else:
        warn.append(
            "Лотов 0 — витрина пустая, продаж пока не будет. "
            "Выставь товар на FunPay или микролот 5–10 ₽ (кнопка «📝 Микролоты»)."
        )

    ad_on = False
    try:
        ad_on = cfg.getboolean("FunPay", "autoDelivery") if cfg else False
    except Exception:
        pass
    ad_n = 0
    try:
        ad = getattr(cardinal, "AD_CFG", None)
        ad_n = len(ad.sections()) if ad else 0
    except Exception:
        pass
    if ad_on and ad_n:
        ok.append(f"Автовыдача включена, лотов в конфиге: {ad_n}")
    elif ad_n and not ad_on:
        warn.append("Файлы автовыдачи есть, но в _main.cfg autoDelivery=0. Включи: Настройки → глобальные.")
    elif not ad_n:
        warn.append("Автовыдача не привязана. Микролоты или ключи в storage/products.")

    cfg_s = load_suppliers_cfg()
    keyed = [s for s in cfg_s.sections() if (cfg_s[s].get("api_key") or "").strip()]
    if keyed:
        ok.append("Панелей с ключом: " + ", ".join(keyed))
        zero_cost = []
        for s in keyed:
            try:
                cpu = float(cfg_s[s].get("cost_per_unit") or 0)
            except ValueError:
                cpu = 0.0
            if cpu <= 0:
                zero_cost.append(s)
        if zero_cost:
            warn.append(
                "Себестоимость 0 у: " + ", ".join(zero_cost)
                + ". Пока cost_per_unit не больше нуля, закупка не уйдёт."
            )
    else:
        warn.append("Ни одной панели с API-ключом. Steam/Robux/SMM сами не закупятся. «🔌 Панель».")

    ma_dir = "mafiles"
    ma_n = 0
    if os.path.isdir(ma_dir):
        ma_n = sum(1 for n in os.listdir(ma_dir) if n.lower().endswith((".mafile", ".json")))
    if ma_n:
        ok.append(f"Steam maFile: {ma_n} шт.")
    else:
        warn.append("Папка mafiles пустая — автоаренда Steam не выдаст слот.")
    try:
        from shop_core.db import get_db
        with get_db() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM mafile_rentals").fetchone()["n"]
            empty = conn.execute(
                "SELECT COUNT(*) AS n FROM mafile_rentals WHERE length(trim(coalesce(password,''))) < 2"
            ).fetchone()["n"]
            locked = conn.execute(
                "SELECT COUNT(*) AS n FROM mafile_rentals WHERE COALESCE(needs_reset, 0) = 1"
            ).fetchone()["n"]
        if total and empty:
            warn.append(
                f"Аренда Steam: у {empty} из {total} аккаунтов нет пароля — слот покупателю не выдастся. "
                "Задай пароль: /rentpass ID пароль."
            )
        if locked:
            warn.append(
                f"Аренда Steam: {locked} слот(ов) ждут смены пароля после аренды. "
                "Смени пароль и пришли /rentpass ID новый_пароль."
            )
    except Exception:
        logger.debug("TRACEBACK", exc_info=True)

    plugins = getattr(cardinal, "plugins", {}) or {}
    enabled = sum(1 for p in plugins.values() if getattr(p, "enabled", True))
    ok.append(f"Плагинов включено: {enabled}/{len(plugins)}")

    tg = getattr(cardinal, "telegram", None)
    n_ops = len(getattr(tg, "authorized_users", {}) or {}) if tg else 0
    if n_ops:
        ok.append(f"Операторов в пульте: {n_ops}")
    else:
        warn.append("В пульте никого кроме возможного владельца.")

    need = min_margin_mult()
    ok.append(f"Запас к закупке: x{need:.1f} (ниже — панель не получит заказ)")

    if n_lots == 0:
        warn.append(
            "Чтобы выходить в плюс 100–1000 ₽: микролоты 5–10 ₽ (закупка 0, чистыми ~97%) "
            "и дорогие лоты только если панель даёт x2."
        )

    try:
        from plugins.autostars import _panel_status as _stars_st
        st = _stars_st()
        if st.get("enabled") and st.get("ok"):
            ok.append("AutoStars: панель и ключ на месте")
        elif st.get("enabled"):
            warn.append("AutoStars включён, но в панели Stars нет URL/ключа/service_id.")
    except Exception:
        pass
    try:
        from plugins.raise_clock import status_line
        ok.append(status_line())
    except Exception:
        pass

    try:
        from plugins.auto_price import _enabled as _apr_on
        if _apr_on():
            ok.append("Автоцена включена (микролоты не трогает)")
        else:
            warn.append("Автоцена выкл — лоты сами под рынок не подстроятся.")
    except Exception:
        pass

    try:
        from shop_core.settings import ini_bool as _ini
        if _ini("configs/ai.cfg", "AI", "enabled", False):
            ya = bool(os.getenv("YANDEX_API_KEY", "").strip() or os.getenv("OPENROUTER_KEY", "").strip())
            if ya:
                ok.append("ИИ в FunPay-чате включён, ключ есть")
            else:
                warn.append("ИИ включён, но нет YANDEX_API_KEY / OPENROUTER_KEY в .env — отвечает шаблонами.")
    except Exception:
        pass
    return ok, warn, bad


def report_text(cardinal) -> str:
    ok, warn, bad = scan(cardinal)
    lines = ["🔍 <b>Проверка магазина</b>", "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"]
    if bad:
        lines.append("🔴 <b>Нужно твоё действие</b>")
        lines.extend(f"• {html.escape(x)}" for x in bad)
        lines.append("")
    if warn:
        lines.append("🟡 <b>Можно позже</b>")
        lines.extend(f"• {html.escape(x)}" for x in warn)
        lines.append("")
    if ok:
        lines.append("🟢 <b>В порядке</b>")
        lines.extend(f"• {html.escape(x)}" for x in ok)
    lines.append("")
    lines.append("Тебя зовут только если в списке 🔴 или покупатель написал «позови продавца».")
    return "\n".join(lines)


def report_kb() -> K:
    kb = K()
    kb.row(B("🔄 Ещё раз", callback_data="CHECK:run"), B("📖 Инструкции", callback_data="CHECK:how"))
    kb.row(B("📝 Микролоты", callback_data="MICRO:hub"), B("🔌 Панель", callback_data="SHOP:wiz"))
    kb.row(B("🏠 Главная", callback_data="PANEL:home"))
    return kb


def how_index() -> str:
    lines = ["📖 <b>Инструкции</b>", "Открой плагин в «🧩 Плагины» → ⚙️ → «Как настроить», либо кнопки ниже.", ""]
    names = [
        ("Панель API", "SHOP:wiz"),
        ("Как продавать", "METH:hub"),
        ("Микролоты 5–10 ₽", "MICRO:hub"),
        ("Кошелёк / вывод", "WAL:ref"),
    ]
    return "\n".join(lines) + "\n" + "\n".join(f"• {n}" for n, _ in names)


def how_kb() -> K:
    kb = K()
    kb.row(B("🔌 Панель", callback_data="SHOP:wiz"), B("🚚 Схемы", callback_data="METH:hub"))
    kb.row(B("📝 Микролоты", callback_data="MICRO:hub"), B("💰 Кошелёк", callback_data="PANEL:bal"))
    kb.row(B("◀️ Проверка", callback_data="CHECK:run"))
    return kb


def init_settings(cardinal):
    SettingsPage(UUID, NAME, "Автопроверка. Пишет в Telegram, только если нужно действие.") \
        .set_status(lambda: report_text(cardinal)[:1500]) \
        .attach(cardinal)
    cardinal.add_telegram_commands(UUID, [
        ("check", "проверка магазина", True),
        ("howto", "инструкции", True),
    ])


def init_pre(cardinal):
    global _READY
    init_settings(cardinal)
    tg = getattr(cardinal, "telegram", None)
    if not tg or not getattr(tg, "bot", None) or _READY:
        return
    _READY = True
    bot = tg.bot

    @bot.message_handler(commands=["check", "проверка", "clinic"])
    def cmd_check(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        bot.send_message(m.chat.id, report_text(cardinal), reply_markup=report_kb(), parse_mode="HTML")

    @bot.message_handler(commands=["howto", "инструкция", "инструкции"])
    def cmd_how(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        bot.send_message(m.chat.id, how_index(), reply_markup=how_kb(), parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("CHECK:"))
    def cb_check(c: CallbackQuery):
        if not _ok(cardinal, c.from_user.id):
            return
        try:
            bot.answer_callback_query(c.id)
        except Exception:
            pass
        action = (c.data or "").split(":")[1] if ":" in (c.data or "") else "run"
        if action == "how":
            bot.send_message(c.message.chat.id, how_index(), reply_markup=how_kb(), parse_mode="HTML")
            return
        bot.send_message(c.message.chat.id, report_text(cardinal), reply_markup=report_kb(), parse_mode="HTML")


def _loop(cardinal):
    global _LAST_PING
    time.sleep(25)
    while True:
        try:
            day = datetime.now().strftime("%Y-%m-%d")
            _ok_l, _w, bad = scan(cardinal)
            if bad and _LAST_PING != day:
                _LAST_PING = day
                notify(cardinal, "🔴 <b>Нужно действие</b>\n\n" + report_text(cardinal), True)
        except Exception as ex:
            logger.debug("[Clinic] loop: %s", ex)
        time.sleep(3600)


def init_post(cardinal):
    Thread(target=_loop, args=(cardinal,), daemon=True).start()


BIND_TO_PRE_INIT = [init_pre]
BIND_TO_POST_START = [init_post]
