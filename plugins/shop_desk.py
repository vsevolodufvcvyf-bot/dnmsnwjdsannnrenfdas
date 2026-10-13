# -*- coding: utf-8 -*-
"""Пульт продавца: панели, здоровье FunPay, утренний отчёт, команда Telegram."""
from __future__ import annotations

import html
import logging
import os
import time
from datetime import datetime
from threading import Thread

from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, Message, CallbackQuery

from shop_core.bus import get_flag, is_frozen, notify, set_flag
from shop_core.db import get_db
from shop_core.panels import (
    PRESETS, apply_preset, load_suppliers_cfg, margin_report, next_section_name,
    panels_overview, save_supplier_section, test_panel,
)
from shop_core.plugin_settings import SettingsPage
from shop_core.settings import is_dry_run, is_panic, min_margin_mult
from shop_core.team import (
    bootstrap, grant_operator, invite_username, invited_usernames, is_owner, owner_id, team_text,
)
from tg_bot.panel_ui import all_reply_labels

WAIT_TTL = 600
logger = logging.getLogger("FPC.ShopDesk")

NAME = "Пульт магазина"
VERSION = "1.0.0"
DESCRIPTION = "Панели поставщиков, здоровье FunPay, утренний отчёт, команда"
CREDITS = "nnanserShop"
UUID = "a8c31d55-9e2b-4f70-b1c4-7d6e8a9f0123"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}

_READY = False
_WIZ: dict[int, dict] = {}
_LAST_DAY = ""


def clear_wait(uid: int) -> None:
    _WIZ.pop(int(uid), None)


def forget_secret(bot, message, field: str) -> bool:
    """Ключ API не должен оставаться в истории чата. Карту и телефон кошелёк удаляет так же."""
    if field != "key" or message is None:
        return False
    try:
        bot.delete_message(message.chat.id, message.id)
        return True
    except Exception:
        logger.debug("TRACEBACK", exc_info=True)
        return False


def _owner_id() -> int:
    return owner_id()


def _is_owner(uid: int) -> bool:
    return is_owner(uid)


def _ok(cardinal, uid: int) -> bool:
    tg = getattr(cardinal, "telegram", None)
    return bool(tg) and uid in getattr(tg, "authorized_users", {})


def lots_count(cardinal) -> int:
    profile = getattr(cardinal, "profile", None)
    if not profile:
        return 0
    try:
        lots = profile.get_sorted_lots(1) or {}
        return len(lots)
    except Exception:
        return 0


def infer_sale_price(cardinal, lot_name: str) -> float:
    name = (lot_name or "").strip().lower()
    profile = getattr(cardinal, "profile", None)
    if not profile or not name:
        return 0.0
    try:
        lots = profile.get_sorted_lots(1) or {}
        best_p, best_score = 0.0, 0
        for lot in lots.values():
            desc = " ".join(filter(None, [
                getattr(lot, "description", None) or "",
                getattr(lot, "server", None) or "",
                getattr(lot, "side", None) or "",
            ])).lower()
            try:
                price = float(getattr(lot, "price", 0) or 0)
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            score = 0
            if name == desc:
                score = 100
            elif name in desc or (desc and desc in name):
                score = 60
            else:
                hits = sum(1 for w in name.split() if len(w) > 2 and w in desc)
                if hits:
                    score = hits * 10
            if score > best_score:
                best_score, best_p = score, price
        return best_p if best_score else 0.0
    except Exception as ex:
        logger.debug("[ShopDesk] infer price: %s", ex)
        return 0.0


def health_text(cardinal) -> str:
    acc = getattr(cardinal, "account", None)
    name = html.escape(str(getattr(acc, "username", "—") or "—"))
    uid = getattr(acc, "id", "—")
    bal = getattr(cardinal, "balance", None)
    rub = getattr(bal, "total_rub", 0) if bal else 0
    n_lots = lots_count(cardinal)
    cfg = getattr(cardinal, "MAIN_CFG", None)
    wm = ""
    old_mode = False
    key_ok = False
    try:
        wm = (cfg["Other"].get("watermark") or "").strip() if cfg else ""
        old_mode = cfg.getboolean("FunPay", "oldMsgGetMode") if cfg else False
        key_ok = bool((cfg["FunPay"].get("golden_key") or "").strip()) if cfg else False
    except Exception:
        logger.debug("TRACEBACK", exc_info=True)
    freeze_on = is_frozen()
    reason = html.escape(str(get_flag("freeze_reason", "") or "—"))
    if freeze_on:
        fp = f"🔴 заморожен: <code>{reason}</code>"
    elif is_panic():
        fp = "🔴 аварийный стоп"
    else:
        fp = "🟢 сессия живая"
    hid = []
    if "🐦" in wm or "cardinal" in wm.lower():
        hid.append("водяной знак Cardinal — FunPay прячет такие сообщения")
    if "\u2061" in wm:
        hid.append("невидимый символ в водяном знаке")
    if old_mode:
        hid.append("включён старый режим сообщений (oldMsgGetMode)")
    hid_line = ("⚠️ Исходящие: " + "; ".join(hid)) if hid else "Исходящие: водяной знак чистый, mute FunPay бот не обходит."
    cfg_s = load_suppliers_cfg()
    keyed = sum(1 for s in cfg_s.sections() if (cfg_s[s].get("api_key") or "").strip())
    on = sum(1 for s in cfg_s.sections() if cfg_s[s].getboolean("enabled", fallback=False))
    plugins = getattr(cardinal, "plugins", {}) or {}
    enabled = sum(1 for p in plugins.values() if getattr(p, "enabled", True))
    lines = [
        "🩺 <b>FunPay</b>",
        f"👤 {name}  <code>#{uid}</code>",
        f"💰 Баланс: <code>{rub}</code> ₽",
        f"📦 Лотов на витрине: <b>{n_lots}</b>",
        f"Ключ golden_key: {'есть' if key_ok else 'нет — пропиши в configs/_main.cfg'}",
        fp,
        hid_line,
        "",
        f"🧩 Плагинов включено: <b>{enabled}</b> / {len(plugins)}",
        f"🔌 Панелей с ключом: <b>{keyed}</b> · включено: {on}",
        f"Запас к закупке: <b>x{min_margin_mult():.1f}</b>  ·  учёба: {'да' if is_dry_run() else 'нет'}",
    ]
    if n_lots == 0:
        lines.append("\nℹ️ Лотов 0 — сначала выставь товар на FunPay, иначе цена рынка и склад будут пустыми.")
    return "\n".join(lines)


def day_text(cardinal) -> str:
    since = time.time() - 86400
    with get_db() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(sale_price),0), COALESCE(SUM(cost),0), COALESCE(SUM(profit),0), COUNT(*)
               FROM finance_log WHERE created_at > ? AND dry_run = 0""",
            (since,),
        ).fetchone()
        sales, cost, profit, n = row
        empty_stock = 0
    stock_lines = []
    try:
        from plugins.auto_restock import iter_stock, load_cfg
        cfg = load_cfg()
        min_s = int(cfg.get("min_stock", 2) or 2)
        for r in iter_stock(cardinal):
            if r.get("infinite"):
                continue
            cnt = int(r.get("count") or 0)
            if cnt < min_s:
                empty_stock += 1
                stock_lines.append(f"• {r['lot']}: {cnt} шт.")
    except Exception:
        logger.debug("TRACEBACK", exc_info=True)
    from shop_core.goals import goal_line, today_totals
    day_sales, _day_cost, day_profit, day_n = today_totals()
    try:
        from plugins.raise_clock import plan
        _hours, why = plan()
        hours_line = "🕐 " + html.escape(why)
    except Exception:
        logger.debug("TRACEBACK", exc_info=True)
        hours_line = ""
    lines = [
        "☀️ <b>Отчёт</b>",
        health_text(cardinal),
        "",
        f"📒 Сегодня: сделок <b>{day_n}</b> · оборот <code>{day_sales:.0f}</code> · чистыми <code>{day_profit:.0f}</code>",
        goal_line(day_profit),
        f"📒 За 24 часа: сделок <b>{n}</b> · оборот <code>{sales:.0f}</code> · закупка <code>{cost:.0f}</code> · чистыми <code>{profit:.0f}</code>",
    ]
    if hours_line:
        lines.append(hours_line + "  ·  подробнее /hours")
    if stock_lines:
        lines.append(f"\n📦 Мало на складе ({empty_stock}):")
        lines.extend(stock_lines[:12])
    else:
        lines.append("\n📦 Склад: пустых позиций нет (или автовыдача ещё не привязана).")
    lines.append("\n" + team_text(cardinal.telegram) if getattr(cardinal, "telegram", None) else "")
    return "\n".join(lines)


def wiz_kb() -> K:
    kb = K()
    cfg = load_suppliers_cfg()
    for section in list(cfg.sections())[:12]:
        on = cfg[section].getboolean("enabled", fallback=False)
        has = bool((cfg[section].get("api_key") or "").strip())
        mark = "✅" if on and has else ("🔑" if has else "➕")
        kb.add(B(f"{mark} {section}"[:64], callback_data=f"SHOP:p:{section}"[:64]))
    kb.row(
        B("+ SMM", callback_data="SHOP:new:smm"),
        B("+ Stars", callback_data="SHOP:new:stars"),
    )
    kb.row(
        B("+ Подарки", callback_data="SHOP:new:gifts"),
        B("+ Steam", callback_data="SHOP:new:steam_wallet"),
    )
    kb.row(
        B("+ Robux", callback_data="SHOP:new:robux"),
        B("+ своя панель", callback_data="SHOP:new:other"),
    )
    kb.row(
        B("📋 Задачи поставщиков", callback_data="SHOP:tasks"),
        B("🙋 Чаты человеку", callback_data="SHOP:human"),
    )
    kb.row(B("🚨 Очередь оператора", callback_data="SHOP:q"))
    kb.row(B("◀️ Главная", callback_data="PANEL:home"))
    return kb


def tasks_view() -> tuple[str, K]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT rowid AS rid, order_id, plugin_name, provider, task_id, status, created_at
               FROM supplier_orders ORDER BY created_at DESC LIMIT 10"""
        ).fetchall()
    kb = K()
    if not rows:
        kb.row(B("◀️ Панели", callback_data="SHOP:wiz"))
        return "📋 <b>Задачи поставщиков</b>\nПока ни одной закупки через панель.", kb
    lines = ["📋 <b>Задачи поставщиков</b> (последние 10)", "Кнопка спрашивает только статус, новую закупку не шлёт.", ""]
    for r in rows:
        when = datetime.fromtimestamp(float(r["created_at"] or 0)).strftime("%d.%m %H:%M")
        lines.append(
            f"• {html.escape(str(r['plugin_name']))} #{html.escape(str(r['order_id'])[:40])} → "
            f"[{html.escape(str(r['provider'] or '—'))}] задача <code>{html.escape(str(r['task_id'] or '—'))}</code> · "
            f"{html.escape(str(r['status'] or '—'))} · {when}"
        )
        if r["task_id"]:
            kb.add(B(f"🔎 #{str(r['task_id'])[:20]} статус", callback_data=f"SHOP:st:{int(r['rid'])}"))
    kb.row(B("◀️ Панели", callback_data="SHOP:wiz"))
    return "\n".join(lines), kb


def task_status_text(rid: int) -> str:
    from shop_core.task_status import format_task_status
    with get_db() as conn:
        row = conn.execute(
            "SELECT order_id, plugin_name, provider, task_id FROM supplier_orders WHERE rowid = ?",
            (int(rid),),
        ).fetchone()
    if not row or not row["task_id"]:
        return "Задача не найдена."
    section = str(row["provider"] or "").split("/")[0]
    cfg = load_suppliers_cfg()
    block = cfg[section] if cfg.has_section(section) else {}
    url, key = (block.get("api_url") or "").strip(), (block.get("api_key") or "").strip()
    if not url or not key:
        return f"Панель [{html.escape(section or '—')}] не найдена в suppliers.cfg или без ключа — статус спроси в кабинете."
    if is_frozen() or is_panic():
        return "Сейчас стоп или заморозка — к панели не обращаюсь."
    try:
        import requests
        from shop_core.finance import supplier_post
        res = supplier_post(
            requests.post, url, {"key": key, "action": "status", "order": str(row["task_id"])}, timeout=12.0,
        )
        data = res.json() if res is not None else {}
    except Exception as ex:
        return f"Панель не ответила: <code>{html.escape(type(ex).__name__)}</code>"
    return format_task_status(str(row["task_id"]), section, data)


def queue_view() -> tuple[str, K]:
    from shop_core.operator_queue import open_items, queue_text
    rows = open_items()
    kb = K()
    for row in rows:
        rid = int(row["id"])
        label = str(row["reason"] or "human")
        kb.add(B(f"✅ Решено #{rid} ({label})"[:64], callback_data=f"SHOP:qok:{rid}"))
        if row["chat_id"] is not None:
            kb.add(B(f"💬 Чат {int(row['chat_id'])} человеку"[:64], callback_data=f"SHOP:qhm:{rid}"))
    kb.row(B("🔄 Обновить", callback_data="SHOP:q"), B("◀️ Панели", callback_data="SHOP:wiz"))
    return queue_text(rows), kb


def human_view() -> tuple[str, K]:
    from shop_core.bus import HUMAN_STALE_SEC, STATE_HUMAN_OPERATOR
    since = time.time() - HUMAN_STALE_SEC
    with get_db() as conn:
        rows = conn.execute(
            """SELECT chat_id, order_id, updated_at FROM bus_chats
               WHERE state = ? AND updated_at >= ? ORDER BY updated_at ASC LIMIT 20""",
            (STATE_HUMAN_OPERATOR, since),
        ).fetchall()
    kb = K()
    if not rows:
        kb.row(B("◀️ Панели", callback_data="SHOP:wiz"))
        return "🙋 <b>Чаты у человека</b>\nСейчас бот ни одного чата не отдал продавцу.", kb
    lines = ["🙋 <b>Чаты у человека</b> — бот в них молчит до «Отпустить» или 24 ч.", ""]
    now = time.time()
    for r in rows:
        mins = int((now - float(r["updated_at"] or now)) // 60)
        age = f"{mins // 60} ч {mins % 60} мин" if mins >= 60 else f"{mins} мин"
        order = f" · заказ #{html.escape(str(r['order_id']))}" if r["order_id"] else ""
        lines.append(f"• покупатель <code>{int(r['chat_id'])}</code>{order} · ждёт {age}")
        kb.add(B(f"▶️ Отпустить {int(r['chat_id'])}", callback_data=f"SHOP:rel:{int(r['chat_id'])}"))
    kb.row(B("🔄 Обновить", callback_data="SHOP:human"), B("◀️ Панели", callback_data="SHOP:wiz"))
    return "\n".join(lines), kb


def panel_kb(section: str) -> K:
    kb = K()
    cfg = load_suppliers_cfg()
    on = cfg.has_section(section) and cfg[section].getboolean("enabled", fallback=False)
    kb.row(
        B("🟢 Вкл" if not on else "⚪ Выкл", callback_data=f"SHOP:en:{section}"[:64]),
        B("📡 Проверить", callback_data=f"SHOP:test:{section}"[:64]),
    )
    kb.row(
        B("🔑 Ключ", callback_data=f"SHOP:ask:{section}:key"[:64]),
        B("🌐 URL", callback_data=f"SHOP:ask:{section}:url"[:64]),
    )
    kb.row(
        B("🆔 service_id", callback_data=f"SHOP:ask:{section}:sid"[:64]),
        B("💸 Себест.", callback_data=f"SHOP:ask:{section}:cost"[:64]),
    )
    kb.row(
        B("🏷 Ключевые слова", callback_data=f"SHOP:ask:{section}:kw"[:64]),
        B("◀️ К списку", callback_data="SHOP:wiz"),
    )
    return kb


def panel_text(section: str) -> str:
    cfg = load_suppliers_cfg()
    if not cfg.has_section(section):
        return f"Панели <b>{html.escape(section)}</b> нет."
    b = cfg[section]
    url = (b.get("api_url") or "").strip()
    host = url.split("/")[2] if "://" in url else (url or "—")
    from shop_core.panels import mask_secret
    on = "вкл" if b.getboolean("enabled", fallback=False) else "выкл"
    return (
        f"🔌 <b>{html.escape(section)}</b> · {on}\n"
        f"Плагин: <code>{html.escape(b.get('plugin_name') or '—')}</code>\n"
        f"URL: <code>{html.escape(host)}</code>\n"
        f"Ключ: {mask_secret(b.get('api_key') or '')}\n"
        f"service_id: <code>{html.escape(b.get('service_id') or '—')}</code>\n"
        f"Себестоимость 1 шт.: <code>{html.escape(b.get('cost_per_unit') or '0')}</code>\n"
        f"Слова для лота: <i>{html.escape(b.get('keywords') or '—')}</i>\n\n"
        f"Сайты сам не ищу — только то, что ты вставишь."
    )


def wiz_intro() -> str:
    return (
        "🔌 <b>Панели поставщиков</b>\n"
        "Нужны, чтобы автопополнение Steam / Robux / Stars / SMM работало само.\n\n"
        "<b>Откуда ключ</b>\n"
        "1. Зайди в кабинет своей панели (не FunPay, не Steam Store).\n"
        "2. Раздел API / Developers → скопируй <b>API Key</b>.\n"
        "3. URL почти всегда <code>https://твой-домен/api/v2</code>.\n"
        "4. service_id — номер услуги в прайсе панели.\n"
        "5. Себестоимость 1 шт. в ₽ — чтобы бот не закупал в минус (нужен запас x2).\n"
        "6. Кнопка «📡 Проверить» должна показать баланс панели.\n\n"
        "Чужие сайты и Telegram-боты сам не ищу.\n\n"
        + panels_overview()
    )


def _digest_loop(cardinal):
    global _LAST_DAY
    while True:
        try:
            now = datetime.now()
            if now.strftime("%H:%M") == "10:00":
                day = now.strftime("%Y-%m-%d")
                if _LAST_DAY != day:
                    _LAST_DAY = day
                    ping = True
                    try:
                        from plugins.clinic import scan
                        _ok, _w, bad = scan(cardinal)
                        ping = bool(bad)
                    except Exception:
                        ping = True
                    if ping:
                        notify(cardinal, day_text(cardinal), True)
        except Exception as ex:
            logger.debug("[ShopDesk] digest: %s", ex)
        time.sleep(40)


def init_settings(cardinal):
    SettingsPage(UUID, NAME, "Панели, здоровье FunPay, команда. Команды: /panels /health /day /op") \
        .set_status(lambda: health_text(cardinal)[:1500]) \
        .attach(cardinal)
    cardinal.add_telegram_commands(UUID, [
        ("panels", "панели поставщиков", True),
        ("health", "здоровье FunPay", True),
        ("day", "отчёт за сегодня", True),
        ("goal", "цель по прибыли на день", True),
        ("hours", "часы, когда покупают", True),
        ("op", "добавить оператора @username", True),
        ("queue", "очередь оператора", True),
    ])


def init_pre(cardinal):
    global _READY
    init_settings(cardinal)
    tg = getattr(cardinal, "telegram", None)
    if not tg or not getattr(tg, "bot", None) or _READY:
        return
    _READY = True
    bot = tg.bot

    def guard(m) -> bool:
        return _ok(cardinal, m.from_user.id)

    @bot.message_handler(commands=["queue", "очередь"])
    def cmd_queue(m: Message):
        if not guard(m):
            return
        text, kb = queue_view()
        bot.send_message(m.chat.id, text, reply_markup=kb, parse_mode="HTML")

    @bot.message_handler(commands=["panels", "panel_add", "поставщик"])
    def cmd_panels(m: Message):
        if not guard(m):
            return
        try:
            from tg_bot.panel_ui import clear_all_waits
            clear_all_waits(m.from_user.id)
        except Exception:
            clear_wait(m.from_user.id)
        bot.send_message(m.chat.id, wiz_intro(), reply_markup=wiz_kb(), parse_mode="HTML")

    @bot.message_handler(commands=["health", "funpay", "сессия"])
    def cmd_health(m: Message):
        if not guard(m):
            return
        bot.send_message(m.chat.id, health_text(cardinal), parse_mode="HTML")

    @bot.message_handler(commands=["day", "digest", "утро"])
    def cmd_day(m: Message):
        if not guard(m):
            return
        bot.send_message(m.chat.id, day_text(cardinal), parse_mode="HTML")

    @bot.message_handler(commands=["goal"])
    def cmd_goal(m: Message):
        if not guard(m):
            return
        from shop_core.goals import goal_help, parse_goal, set_daily_target
        kind, value = parse_goal(m.text or "")
        if kind == "bad":
            bot.send_message(
                m.chat.id,
                "Нужна сумма в рублях, например <code>/goal 3000</code>. Убрать цель: <code>/goal 0</code>.",
                parse_mode="HTML",
            )
            return
        if kind == "set" and value is not None:
            set_daily_target(value)
        bot.send_message(m.chat.id, goal_help(), parse_mode="HTML")

    @bot.message_handler(commands=["hours"])
    def cmd_hours(m: Message):
        if not guard(m):
            return
        from plugins.raise_clock import demand_text
        bot.send_message(m.chat.id, demand_text(), parse_mode="HTML")

    @bot.message_handler(commands=["team", "операторы"])
    def cmd_team(m: Message):
        if not guard(m):
            return
        bot.send_message(m.chat.id, team_text(tg), parse_mode="HTML")

    @bot.message_handler(commands=["op"])
    def cmd_op(m: Message):
        if not guard(m):
            return
        if not _is_owner(m.from_user.id):
            if not _owner_id():
                bot.send_message(m.chat.id, "Владелец не задан. Впиши свой ID в .env → TELEGRAM_OWNER_ID и перезапусти.")
            else:
                bot.send_message(m.chat.id, "Добавлять людей может только владелец.")
            return
        parts = (m.text or "").split()
        if len(parts) < 2:
            bot.send_message(
                m.chat.id,
                "Кого добавить?\n"
                "<code>/op 123456789</code> — сразу по Telegram ID (узнать у @userinfobot).\n"
                "<code>/op @username</code> — приглашение: когда человек напишет боту, "
                "тебе придёт кнопка «Пустить».",
                parse_mode="HTML",
            )
            return
        raw = parts[1].strip().lstrip("@")
        if raw.isdigit():
            grant_operator(tg, int(raw), None)
            bot.send_message(m.chat.id, f"✅ ID <code>{raw}</code> в команде. Пусть нажмёт /menu.", parse_mode="HTML")
            try:
                bot.send_message(int(raw), "✅ Тебя добавили в пульт nnanserShop. Нажми /menu.")
            except Exception:
                logger.debug("TRACEBACK", exc_info=True)
            return
        if not invite_username(raw):
            bot.send_message(m.chat.id, "Это не похоже на ник Telegram. Пример: <code>/op @username</code>", parse_mode="HTML")
            return
        bot.send_message(
            m.chat.id,
            f"✉️ @{html.escape(raw)} приглашён. Когда он напишет боту /menu, "
            f"тебе придёт запрос с кнопкой «Пустить». Без твоего подтверждения доступа не будет.",
        )

    def _is_wiz_text(m: Message) -> bool:
        if not m.from_user or m.from_user.id not in _WIZ:
            return False
        if time.time() - float((_WIZ.get(m.from_user.id) or {}).get("at", 0)) > WAIT_TTL:
            _WIZ.pop(m.from_user.id, None)
            return False
        text = (m.text or "").strip()
        if not text or text.startswith("/"):
            return False
        if text in all_reply_labels():
            return False
        try:
            if tg.get_state(m.chat.id, m.from_user.id):
                return False
        except Exception:
            logger.debug("TRACEBACK", exc_info=True)
        try:
            from plugins.market_analyzer import _WAIT as MWAIT
            if m.from_user.id in MWAIT:
                return False
        except Exception:
            logger.debug("TRACEBACK", exc_info=True)
        return True

    @bot.message_handler(func=_is_wiz_text)
    def cmd_wiz_wait(m: Message):
        if not guard(m):
            return
        st = _WIZ.get(m.from_user.id) or {}
        section = st.get("section")
        field = st.get("field")
        raw = (m.text or "").strip()
        if not section or not field:
            clear_wait(m.from_user.id)
            return
        mapping = {
            "url": "api_url",
            "key": "api_key",
            "sid": "service_id",
            "cost": "cost_per_unit",
            "kw": "keywords",
            "name": None,
        }
        if field == "name":
            new_name = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in raw)[:32] or "panel"
            kind = st.get("kind") or "other"
            apply_preset(new_name, kind)
            _WIZ[m.from_user.id] = {"at": time.time(), "section": new_name, "field": "url"}
            bot.send_message(m.chat.id, f"Панель <b>{html.escape(new_name)}</b>. Теперь пришли URL API.", parse_mode="HTML")
            return
        key = mapping.get(field)
        if not key:
            clear_wait(m.from_user.id)
            return
        if field == "url":
            from shop_core.panels import normalize_supplier_url
            url = normalize_supplier_url(raw)
            if not url:
                bot.send_message(
                    m.chat.id,
                    "Нужен адрес панели, например <code>panel.example.com</code> или <code>https://panel.example.com</code>.",
                    parse_mode="HTML",
                )
                return
            raw = url
        if field == "cost":
            raw = raw.replace(",", ".")
            try:
                float(raw)
            except ValueError:
                bot.send_message(m.chat.id, "Себестоимость — число, например <code>12.5</code>", parse_mode="HTML")
                return
        if field == "key":
            forget_secret(bot, m, field)
            if len(raw) < 8:
                bot.send_message(
                    m.chat.id,
                    "Ключ короткий — не записал. Пришли его ещё раз одним сообщением.",
                )
                return
        save_supplier_section(section, {key: raw})
        nxt = {"url": "key", "key": "sid", "sid": "cost", "cost": "kw", "kw": None}.get(field)
        if nxt:
            _WIZ[m.from_user.id] = {"at": time.time(), "section": section, "field": nxt}
            prompts = {
                "key": (
                    "🔑 <b>Ключ API</b>\n"
                    "Кабинет панели → API / Token. Одним сообщением. В лог не пишу.\n"
                    "Без ключа автопополнение Steam/Robux/SMM не запустится."
                ),
                "sid": (
                    "🔢 <b>service_id</b>\n"
                    "Номер услуги в прайсе панели (часто в URL или в списке Services).\n"
                    "Если не знаешь — пришли <code>0</code> и потом поправь."
                ),
                "cost": "Себестоимость 1 шт. в рублях, например <code>8.5</code>. Ниже продажи x2 бот не закупит.",
                "kw": "Слова из названия лота FunPay через запятую, например <code>робукс, robux</code>.",
            }
            bot.send_message(m.chat.id, "✅ Записал.\n" + prompts[nxt], parse_mode="HTML")
            return
        save_supplier_section(section, {"enabled": "1"})
        clear_wait(m.from_user.id)
        check = test_panel(section)
        bot.send_message(
            m.chat.id,
            f"✅ Панель <b>{html.escape(section)}</b> включена.\n{check}",
            reply_markup=panel_kb(section),
            parse_mode="HTML",
        )

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("SHOP:"))
    def cb_shop(c: CallbackQuery):
        if not _ok(cardinal, c.from_user.id):
            return
        parts = (c.data or "").split(":")
        action = parts[1] if len(parts) > 1 else ""
        try:
            bot.answer_callback_query(c.id)
        except Exception:
            logger.debug("TRACEBACK", exc_info=True)

        if action in ("wiz", "home"):
            try:
                from tg_bot.panel_ui import clear_all_waits
                clear_all_waits(c.from_user.id)
            except Exception:
                clear_wait(c.from_user.id)
            bot.send_message(c.message.chat.id, wiz_intro(), reply_markup=wiz_kb(), parse_mode="HTML")
            return
        if action == "health":
            bot.send_message(c.message.chat.id, health_text(cardinal), parse_mode="HTML")
            return
        if action == "day":
            bot.send_message(c.message.chat.id, day_text(cardinal), parse_mode="HTML")
            return
        if action == "team":
            bot.send_message(c.message.chat.id, team_text(tg), parse_mode="HTML")
            return
        if action == "tasks":
            text, kb = tasks_view()
            bot.send_message(c.message.chat.id, text, reply_markup=kb, parse_mode="HTML")
            return
        if action == "st" and len(parts) > 2 and parts[2].isdigit():
            bot.send_message(c.message.chat.id, task_status_text(int(parts[2])), parse_mode="HTML")
            return
        if action == "human":
            text, kb = human_view()
            bot.send_message(c.message.chat.id, text, reply_markup=kb, parse_mode="HTML")
            return
        if action == "q":
            text, kb = queue_view()
            bot.send_message(c.message.chat.id, text, reply_markup=kb, parse_mode="HTML")
            return
        if action == "qok" and len(parts) > 2 and parts[2].isdigit():
            from shop_core.operator_queue import resolve_item
            resolve_item(int(parts[2]))
            text, kb = queue_view()
            bot.send_message(c.message.chat.id, "Закрыл пункт очереди.\n\n" + text, reply_markup=kb, parse_mode="HTML")
            return
        if action == "qhm" and len(parts) > 2 and parts[2].isdigit():
            from shop_core.bus import mark_human
            from shop_core.operator_queue import open_items
            row = next((r for r in open_items(50) if int(r["id"]) == int(parts[2])), None)
            if row and row["chat_id"] is not None:
                mark_human(int(row["chat_id"]), str(row["order_id"] or "") or None)
                bot.send_message(c.message.chat.id, f"Чат <code>{int(row['chat_id'])}</code> отдан человеку. ИИ в нём молчит.", parse_mode="HTML")
            else:
                bot.send_message(c.message.chat.id, "Пункт уже закрыт или в нём нет чата.")
            return
        if action == "rel" and len(parts) > 2 and parts[2].lstrip("-").isdigit():
            from shop_core.bus import release_chat
            release_chat(int(parts[2]))
            text, kb = human_view()
            bot.send_message(c.message.chat.id, "▶️ Чат вернул боту.\n\n" + text, reply_markup=kb, parse_mode="HTML")
            return
        if action == "new" and len(parts) > 2:
            try:
                from tg_bot.panel_ui import clear_all_waits
                clear_all_waits(c.from_user.id)
            except Exception:
                logger.debug("TRACEBACK", exc_info=True)
            kind = parts[2] if parts[2] in PRESETS else "other"
            if kind == "other":
                _WIZ[c.from_user.id] = {"at": time.time(), "section": "", "field": "name", "kind": "other"}
                bot.send_message(c.message.chat.id, "Имя панели латиницей, например <code>my_panel</code>.", parse_mode="HTML")
                return
            section = next_section_name(kind)
            apply_preset(section, kind)
            _WIZ[c.from_user.id] = {"at": time.time(), "section": section, "field": "url"}
            bot.send_message(
                c.message.chat.id,
                f"Панель <b>{html.escape(section)}</b>.\n"
                "Пришли <b>URL API</b> из кабинета панели.\n"
                "Обычно так: <code>https://домен/api/v2</code>\n"
                "Не FunPay и не store.steampowered.com — именно твоя панель-посредник.",
                parse_mode="HTML",
            )
            return
        if action == "p" and len(parts) > 2:
            section = parts[2]
            bot.send_message(c.message.chat.id, panel_text(section), reply_markup=panel_kb(section), parse_mode="HTML")
            return
        if action == "en" and len(parts) > 2:
            section = parts[2]
            cfg = load_suppliers_cfg()
            on = cfg.has_section(section) and cfg[section].getboolean("enabled", fallback=False)
            save_supplier_section(section, {"enabled": "0" if on else "1"}, create=False)
            bot.send_message(c.message.chat.id, panel_text(section), reply_markup=panel_kb(section), parse_mode="HTML")
            return
        if action == "test" and len(parts) > 2:
            section = parts[2]
            bot.send_message(c.message.chat.id, "📡 " + test_panel(section), parse_mode="HTML")
            return
        if action == "ask" and len(parts) > 3:
            try:
                from tg_bot.panel_ui import clear_all_waits
                clear_all_waits(c.from_user.id)
            except Exception:
                logger.debug("TRACEBACK", exc_info=True)
            section, field = parts[2], parts[3]
            _WIZ[c.from_user.id] = {"at": time.time(), "section": section, "field": field}
            prompts = {
                "key": "🔑 Ключ API из кабинета панели, одним сообщением. В лог не пишу.",
                "url": "URL API, обычно <code>https://домен/api/v2</code>.",
                "sid": "service_id услуги в панели (число).",
                "cost": "Себестоимость 1 шт. в рублях.",
                "kw": "Ключевые слова лота FunPay через запятую.",
            }
            bot.send_message(c.message.chat.id, prompts.get(field, "Пришли значение."))
            return


def init_post(cardinal):
    tg = getattr(cardinal, "telegram", None)
    if tg and getattr(tg, "bot", None):
        try:
            bootstrap(tg)
        except Exception as ex:
            logger.debug("[ShopDesk] bootstrap: %s", ex)
        pending = sorted(invited_usernames())
        day = datetime.now().strftime("%Y-%m-%d")
        if pending and get_flag("team_pending_notice") != day:
            try:
                notify(
                    cardinal,
                    "👥 Приглашены, но ещё не подтверждены: "
                    + ", ".join(f"@{html.escape(n)}" for n in pending)
                    + "\nКогда человек напишет боту /menu, тебе придёт кнопка «Пустить».",
                    True,
                )
                set_flag("team_pending_notice", day)
            except Exception:
                logger.debug("TRACEBACK", exc_info=True)
        if not _owner_id():
            notify(
                cardinal,
                "⚠️ Владелец не задан: вывод денег и добавление операторов выключены.\n"
                "Впиши свой Telegram ID в .env → TELEGRAM_OWNER_ID и перезапусти бота.",
                True,
            )
    Thread(target=_digest_loop, args=(cardinal,), daemon=True).start()


BIND_TO_PRE_INIT = [init_pre]
BIND_TO_POST_START = [init_post]
