# -*- coding: utf-8 -*-
"""Инструменты продавца: зависшие заказы, бэкап лотов, выгрузка продаж, калькулятор, заказы в работе.

Идеи из обзоров ботов FunPay: «автотикет» (заказы, которые покупатель не подтверждает),
сохранение лотов в файл, экспорт статистики и калькулятор цен для пачек товара.
"""
from __future__ import annotations

import csv
import html
import io
import json
import logging
import os
import time
from datetime import datetime
from threading import Thread

from FunPayAPI.common.enums import OrderStatuses, SubCategoryTypes
from shop_core.bus import is_frozen, notify
from shop_core.db import get_db
from shop_core.plugin_settings import SettingsPage
from shop_core.settings import commission, ini_bool, load_ini, min_margin_mult, set_ini

logger = logging.getLogger("FPC.SellerTools")

NAME = "Инструменты продавца"
VERSION = "1.0.0"
DESCRIPTION = "Зависшие заказы, бэкап лотов, CSV, калькулятор, черновик текста лота"
CREDITS = "nnanserShop"
UUID = "7ab19607-2c0f-4294-877b-fa22e40ccf91"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}

CONFIG_FILE = "configs/seller_tools.cfg"
CB = "TOOLS:"


def _llm_ready() -> bool:
    return bool(os.getenv("OPENROUTER_KEY", "").strip() or os.getenv("YANDEX_API_KEY", "").strip())


def _lot_llm():
    from plugins.ai_funpay_ultimate import call_llm
    from shop_core.lotcopy import llm_messages

    def ask(product: str, hint: str) -> str | None:
        return call_llm(llm_messages(product, hint), timeout=12)

    return ask


PACKS = (50, 100, 250, 500, 1000, 2500, 5000)
SUPPORT_URL = "https://support.funpay.com/"
_READY = False
_LOOP = False
_LAST_STUCK: set[str] = set()


def _cfg_float(key: str, default: float) -> float:
    try:
        return float(load_ini(CONFIG_FILE).get("SellerTools", key, fallback=str(default)) or default)
    except ValueError:
        return default


def _ok(cardinal, uid: int) -> bool:
    tg = getattr(cardinal, "telegram", None)
    return bool(tg) and uid in getattr(tg, "authorized_users", {})


# ---------- зависшие заказы ----------

def _ts(when) -> float | None:
    try:
        return when.timestamp()
    except Exception:
        return None


def find_stuck(orders, older_than_hours: float, now: float | None = None) -> list:
    """Оплаченные, но не подтверждённые покупателем дольше older_than_hours часов (самые старые первыми)."""
    now = time.time() if now is None else now
    cutoff = now - older_than_hours * 3600
    out = []
    for o in orders or []:
        ts = _ts(getattr(o, "date", None))
        if getattr(o, "status", None) == OrderStatuses.PAID and ts is not None and ts < cutoff:
            out.append(o)
    return sorted(out, key=lambda o: _ts(o.date) or 0)


def fetch_paid_orders(account, pages: int = 3) -> list:
    orders, start = [], None
    for _ in range(max(1, pages)):
        nxt, chunk, *_rest = account.get_sales(start_from=start, include_paid=True,
                                               include_closed=False, include_refunded=False)
        orders.extend(chunk or [])
        if not nxt:
            break
        start = nxt
        time.sleep(1)
    return orders


def ticket_text(order_id: str, hours: int) -> str:
    return (f"Здравствуйте! Покупатель не подтверждает выполнение заказа #{order_id} уже больше {hours} ч. "
            f"Товар выдан в чате заказа. Прошу проверить и закрыть заказ. Спасибо!")


def _age(ts: float, now: float) -> str:
    hours = int((now - ts) // 3600)
    return f"{hours // 24} дн. {hours % 24} ч." if hours >= 24 else f"{hours} ч."


def stuck_text(stuck: list, hours: float, now: float | None = None) -> str:
    now = time.time() if now is None else now
    if not stuck:
        return f"✅ Нет оплаченных заказов без подтверждения дольше {hours:.0f} ч."
    lines = [f"⏳ <b>Не подтверждены дольше {hours:.0f} ч: {len(stuck)}</b>"]
    for o in stuck[:25]:
        ts = _ts(o.date) or now
        oid = html.escape(str(o.id))
        lines.append(
            f"• <a href=\"https://funpay.com/orders/{oid}/\">#{oid}</a> · {html.escape(str(o.buyer_username))} · "
            f"{float(o.price or 0):.0f} {html.escape(str(getattr(o, 'currency', '') or ''))} · {_age(ts, now)}"
        )
    if len(stuck) > 25:
        lines.append(f"…и ещё {len(stuck) - 25}")
    first = stuck[0]
    lines.append("\nТекст для тикета (скопируй, поменяй номер для остальных):")
    lines.append(f"<code>{html.escape(ticket_text(str(first.id), int(hours)))}</code>")
    lines.append(f"Поддержка FunPay: {SUPPORT_URL}")
    return "\n".join(lines)


def _stuck_loop(cardinal) -> None:
    global _LAST_STUCK
    time.sleep(120)
    while True:
        try:
            if ini_bool(CONFIG_FILE, "SellerTools", "stuck_report", True) and not is_frozen():
                hours = _cfg_float("stuck_hours", 24)
                stuck = find_stuck(fetch_paid_orders(cardinal.account), hours)
                ids = {str(o.id) for o in stuck}
                if ids and ids != _LAST_STUCK:
                    notify(cardinal, stuck_text(stuck, hours), False)
                _LAST_STUCK = ids
        except Exception as ex:
            logger.debug("[SellerTools] stuck: %s", ex)
        time.sleep(6 * 3600)


# ---------- калькулятор ----------

def price_table(unit_cost: float, markup_pct: float, buyer_fee_pct: float, packs=PACKS) -> list[dict]:
    """Цена пачек: закупка × наценка = что получишь; покупатель видит больше на комиссию раздела."""
    rows = []
    for qty in packs:
        cost = unit_cost * qty
        receive = cost * (1 + markup_pct / 100.0)
        buyer = receive * (1 + buyer_fee_pct / 100.0)
        rows.append({"qty": qty, "cost": round(cost, 2), "receive": round(receive, 2),
                     "buyer": round(buyer, 2), "profit": round(receive - cost, 2)})
    return rows


def calc_text(unit_cost: float, markup_pct: float, buyer_fee_pct: float) -> str:
    rows = price_table(unit_cost, markup_pct, buyer_fee_pct)
    head = f"{'шт':>5} {'закупка':>9} {'в форме':>9} {'увидит':>9} {'прибыль':>8}"
    body = "\n".join(
        f"{r['qty']:>5} {r['cost']:>9.2f} {r['receive']:>9.2f} {r['buyer']:>9.2f} {r['profit']:>8.2f}" for r in rows
    )
    return (
        f"🧮 <b>Калькулятор</b>: 1 шт = <code>{unit_cost:g}</code> ₽, наценка {markup_pct:g}%, "
        f"комиссия раздела для покупателя ≈ {buyer_fee_pct:g}%\n"
        f"<pre>{html.escape(head)}\n{html.escape(body)}</pre>\n"
        f"«В форме» — цена, которую вводишь в лот и получаешь на баланс. «Увидит» — сколько заплатит покупатель.\n"
        f"Закупка у панели уйдёт, только если запас ≥ x{min_margin_mult():.1f} (команда /margin)."
    )


def parse_calc_args(text: str) -> tuple[float, float, float] | None:
    parts = (text or "").replace(",", ".").split()[1:]
    try:
        unit = float(parts[0])
        markup = float(parts[1]) if len(parts) > 1 else 10.0
        fee = float(parts[2]) if len(parts) > 2 else round(commission() * 100, 2)
    except (IndexError, ValueError):
        return None
    if unit <= 0 or markup < 0 or not 0 <= fee < 100:
        return None
    return unit, markup, fee


# ---------- выгрузки ----------

def _send_file(bot, chat_id: int, name: str, data: bytes, caption: str = "") -> None:
    bot.send_document(chat_id, io.BytesIO(data), visible_file_name=name, caption=html.escape(caption)[:1000] or None)


def finance_csv(since: float = 0.0) -> bytes:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT created_at, order_id, plugin_name, sale_price, cost, profit, currency, dry_run
               FROM finance_log WHERE created_at >= ? ORDER BY created_at ASC""", (since,),
        ).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["дата", "заказ", "источник", "продажа", "закупка", "прибыль", "валюта", "учебный"])
    for r in rows:
        w.writerow([
            datetime.fromtimestamp(float(r["created_at"] or 0)).strftime("%Y-%m-%d %H:%M"),
            r["order_id"], r["plugin_name"],
            f"{float(r['sale_price'] or 0):.2f}".replace(".", ","),
            f"{float(r['cost'] or 0):.2f}".replace(".", ","),
            f"{float(r['profit'] or 0):.2f}".replace(".", ","),
            r["currency"], "да" if r["dry_run"] else "нет",
        ])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def collect_lots(account, profile, pause: float = 1.0) -> list[dict]:
    out = []
    for lot in (profile.get_lots() if profile else []) or []:
        sub = getattr(lot, "subcategory", None)
        if sub is not None and getattr(sub, "type", None) is SubCategoryTypes.CURRENCY:
            continue
        try:
            fields = account.get_lot_fields(int(lot.id))
            data = {k: v for k, v in (fields.fields or {}).items() if k != "csrf_token"}
        except Exception as ex:
            logger.debug("[SellerTools] lot %s: %s", lot.id, ex)
            data = {}
        out.append({
            "lot_id": str(lot.id),
            "subcategory_id": getattr(sub, "id", None),
            "subcategory": getattr(sub, "name", None),
            "title": getattr(lot, "description", None),
            "public_price": getattr(lot, "price", None),
            "fields": data,
        })
        time.sleep(pause)
    return out


def _lots_backup(cardinal, chat_id: int) -> None:
    bot = cardinal.telegram.bot
    try:
        lots = collect_lots(cardinal.account, getattr(cardinal, "profile", None))
        day = datetime.now().strftime("%Y-%m-%d")
        data = json.dumps({"saved_at": day, "lots": lots}, ensure_ascii=False, indent=2).encode("utf-8")
        os.makedirs(os.path.join("storage", "backups"), exist_ok=True)
        with open(os.path.join("storage", "backups", f"lots_{day}.json"), "wb") as f:
            f.write(data)
        _send_file(bot, chat_id, f"lots_{day}.json", data, f"Бэкап лотов: {len(lots)} шт. Копия — storage/backups.")
    except Exception as ex:
        logger.warning("[SellerTools] lots backup: %s", ex)
        bot.send_message(chat_id, f"Не смог сохранить лоты: {html.escape(str(ex)[:200])}")


# ---------- заказы в работе ----------

_STEP_NAMES = {
    "need_target": "ждём ник/ссылку от покупателя",
    "confirm": "ждём «да» от покупателя",
    "check": "⚠️ панель ответила неоднозначно — проверь",
}


def orders_text(now: float | None = None) -> tuple[str, list[str]]:
    from shop_core.confirm import list_pending
    now = time.time() if now is None else now
    pending = list_pending()
    with get_db() as conn:
        refunds = conn.execute(
            "SELECT order_id, buyer_name, stars, price FROM autoback_pending WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
        rents = conn.execute(
            "SELECT account_name, renter_name, expire_time FROM mafile_rentals WHERE is_rented = 1 AND expire_time > ?",
            (now,),
        ).fetchall()
    lines = ["📋 <b>Заказы в работе</b>"]
    checks = []
    if pending:
        for p in pending:
            age = int((now - float(p["created_at"] or now)) // 60)
            step = _STEP_NAMES.get(p["step"], p["step"])
            lines.append(f"• {html.escape(p['kind'])} #{html.escape(str(p['order_id']))} · {p['qty']} шт. · "
                         f"{html.escape(step)} · {age} мин.")
            if p["step"] == "check":
                checks.append(str(p["order_id"]))
    else:
        lines.append("Закупок в ожидании нет.")
    if refunds:
        lines.append("\n↩️ <b>Ждут решения по возврату</b>")
        for r in refunds:
            lines.append(f"• #{html.escape(str(r['order_id']))} · {html.escape(str(r['buyer_name']))} · "
                         f"{r['stars']}★ · {float(r['price'] or 0):.0f} ₽")
    if rents:
        lines.append("\n🎮 <b>Аренды сейчас</b>")
        for r in rents:
            left = int((float(r["expire_time"]) - now) // 60)
            lines.append(f"• {html.escape(str(r['account_name']))} · {html.escape(str(r['renter_name'] or '—'))} · "
                         f"ещё {left // 60} ч {left % 60} мин")
    return "\n".join(lines), checks


# ---------- Telegram ----------

def _hub_kb():
    from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
    kb = K()
    kb.row(B("📋 Заказы", callback_data=f"{CB}orders"), B("⏳ Зависшие", callback_data=f"{CB}stuck"))
    kb.row(B("📦 Бэкап лотов", callback_data=f"{CB}lots"), B("📊 Продажи CSV", callback_data=f"{CB}export"))
    kb.row(B("🧮 Калькулятор", callback_data=f"{CB}calc"), B("📝 Текст лота", callback_data=f"{CB}lot"))
    return kb


def init_pre(cardinal):
    global _READY
    if not os.path.exists(CONFIG_FILE):
        set_ini(CONFIG_FILE, "SellerTools", "stuck_report", "1")
        set_ini(CONFIG_FILE, "SellerTools", "stuck_hours", "24")
    SettingsPage(UUID, NAME, "Зависшие заказы, бэкап лотов, выгрузка продаж, калькулятор, заказы в работе.") \
        .add_toggle("stuck", "Раз в 6 часов присылать зависшие заказы",
                    lambda: ini_bool(CONFIG_FILE, "SellerTools", "stuck_report", True),
                    lambda _v: set_ini(CONFIG_FILE, "SellerTools", "stuck_report",
                                       "0" if ini_bool(CONFIG_FILE, "SellerTools", "stuck_report", True) else "1")) \
        .set_status(lambda: "Команды: /orders /stuck /lots_backup /export /calc /lottext") \
        .attach(cardinal)
    cardinal.add_telegram_commands(UUID, [
        ("orders", "заказы в работе", True),
        ("stuck", "неподтверждённые заказы", True),
        ("lots_backup", "бэкап лотов в файл", True),
        ("export", "выгрузка продаж CSV", True),
        ("calc", "калькулятор цен пачек", True),
        ("lottext", "черновик текста лота", True),
    ])
    tg = getattr(cardinal, "telegram", None)
    if _READY or not tg or not getattr(tg, "bot", None):
        return
    _READY = True
    bot = tg.bot

    def do_orders(chat_id: int) -> None:
        text, checks = orders_text()
        kb = None
        if checks:
            from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
            kb = K()
            for oid in checks[:10]:
                kb.row(B(f"🔁 #{oid} повторить", callback_data=f"CNF:retry:{oid}"),
                       B(f"✅ #{oid} выполнен", callback_data=f"CNF:done:{oid}"))
        bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")

    def do_stuck(chat_id: int) -> None:
        hours = _cfg_float("stuck_hours", 24)
        try:
            stuck = find_stuck(fetch_paid_orders(cardinal.account), hours)
        except Exception as ex:
            bot.send_message(chat_id, f"FunPay не отдал список продаж: {html.escape(str(ex)[:200])}")
            return
        bot.send_message(chat_id, stuck_text(stuck, hours), parse_mode="HTML", disable_web_page_preview=True)

    def do_export(chat_id: int) -> None:
        _send_file(bot, chat_id, f"sales_{datetime.now():%Y-%m-%d}.csv", finance_csv(),
                   "Журнал продаж (открывается в Excel).")

    def guarded(fn):
        def run(m):
            if _ok(cardinal, m.from_user.id):
                fn(m)
        return run

    tg.msg_handler(guarded(lambda m: bot.send_message(m.chat.id, "🧰 <b>Инструменты продавца</b>",
                                                      reply_markup=_hub_kb(), parse_mode="HTML")),
                   commands=["tools"])
    tg.msg_handler(guarded(lambda m: do_orders(m.chat.id)), commands=["orders"])
    tg.msg_handler(guarded(lambda m: Thread(target=do_stuck, args=(m.chat.id,), daemon=True).start()),
                   commands=["stuck"])
    tg.msg_handler(guarded(lambda m: do_export(m.chat.id)), commands=["export"])
    def cmd_lots(m):
        bot.send_message(m.chat.id, "📦 Сохраняю лоты, это займёт около минуты…")
        Thread(target=_lots_backup, args=(cardinal, m.chat.id), daemon=True).start()

    tg.msg_handler(guarded(cmd_lots), commands=["lots_backup"])

    def cmd_calc(m):
        args = parse_calc_args(m.text or "")
        if not args:
            bot.send_message(
                m.chat.id,
                "Формат: <code>/calc цена_за_1_шт наценка_% [комиссия_%]</code>\n"
                "Пример: <code>/calc 1.35 15 8</code> — звезда по 1.35 ₽, наценка 15%, комиссия раздела 8%.",
                parse_mode="HTML",
            )
            return
        bot.send_message(m.chat.id, calc_text(*args), parse_mode="HTML")

    tg.msg_handler(guarded(cmd_calc), commands=["calc"])

    def cmd_lot(m):
        from shop_core.lotcopy import LotDraftError, format_lot_message, lot_text, parse_lot_args
        product, hint = parse_lot_args(m.text or "")
        if len(product) < 2:
            bot.send_message(
                m.chat.id,
                "Что продаёшь?\n<code>/lottext 1000 робуксов</code>\n"
                "С уточнением: <code>/lottext 100 звёзд | выдача по логину</code>",
                parse_mode="HTML",
            )
            return
        llm = _lot_llm() if _llm_ready() else None
        try:
            draft = lot_text(product, hint, llm=llm)
        except LotDraftError:
            bot.send_message(
                m.chat.id,
                "В тексте есть слова, которые лучше не ставить на витрину: отзыв, скидка, ссылка, контакт. "
                "Убери их и пришли ещё раз.",
            )
            return
        bot.send_message(m.chat.id, format_lot_message(draft), parse_mode="HTML")

    tg.msg_handler(guarded(cmd_lot), commands=["lottext"])

    def cb(c):
        if not _ok(cardinal, c.from_user.id):
            return
        action = (c.data or "")[len(CB):]
        bot.answer_callback_query(c.id)
        chat_id = c.message.chat.id
        if action == "orders":
            do_orders(chat_id)
        elif action == "stuck":
            Thread(target=do_stuck, args=(chat_id,), daemon=True).start()
        elif action == "export":
            do_export(chat_id)
        elif action == "lots":
            bot.send_message(chat_id, "📦 Сохраняю лоты, это займёт около минуты…")
            Thread(target=_lots_backup, args=(cardinal, chat_id), daemon=True).start()
        elif action == "calc":
            bot.send_message(chat_id, "Напиши: <code>/calc цена_за_1_шт наценка_% [комиссия_%]</code>", parse_mode="HTML")
        elif action == "lot":
            bot.send_message(
                chat_id,
                "Напиши товар:\n<code>/lottext 1000 робуксов</code>",
                parse_mode="HTML",
            )

    tg.cbq_handler(cb, lambda c: (c.data or "").startswith(CB))


def init_post(cardinal):
    global _LOOP
    if _LOOP or getattr(cardinal, "account", None) is None:
        return
    _LOOP = True
    Thread(target=_stuck_loop, args=(cardinal,), daemon=True).start()


BIND_TO_PRE_INIT = [init_pre]
BIND_TO_POST_START = [init_post]
