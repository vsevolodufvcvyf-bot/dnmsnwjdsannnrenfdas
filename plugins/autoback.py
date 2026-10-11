# -*- coding: utf-8 -*-
"""Возврат за отзыв 1–3★: по умолчанию спрашивает владельца кнопками.

Автоматический режим (mode = auto) возвращает сам только в пределах лимитов: сумма, не за
уже выданный автоматически товар, один возврат на покупателя за 30 дней, дневной лимит.
Всё, что за пределами, уходит на кнопки. Так «купил, получил, поставил 1★, вернул деньги»
не работает как бесплатная схема.
"""
from __future__ import annotations

import configparser
import html
import logging
import os
import time
from datetime import datetime
from threading import Thread

from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K

from FunPayAPI.common.enums import MessageTypes
from shop_core.bus import bot_send, is_frozen, notify
from shop_core.db import get_db
from shop_core.finance import already_processed, claim_order, release_claim
from shop_core.plugin_settings import SettingsPage
from shop_core.settings import flip_ini, ini_bool, is_dry_run, is_panic, set_ini

logger = logging.getLogger("FPC.Autoback")

NAME = "Autoback Rating Shield"
VERSION = "2.0.0"
DESCRIPTION = "Возврат при отзыве 1–3★: кнопки «вернуть / не возвращать», автоматически — только в лимитах"
CREDITS = "Cardinal Community"
UUID = "3c8e4a91-1d5f-4a7b-8c2e-9f3a1b4c6d8e"
SETTINGS_PAGE = True

BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}

CONFIG_FILE = "configs/autoback.cfg"
CB = "ABK:"
PLUGIN = "autoback"
DEFAULTS = {
    "enabled": "1",
    "mode": "ask",
    "max_refund_rub": "300.0",
    "min_stars": "1",
    "max_stars": "3",
    "buyer_limit_30d": "1",
    "daily_limit_rub": "1000",
    "skip_if_delivered": "1",
    "refund_by_operators": "0",
    "send_buyer_message": "1",
    "buyer_message": "Здравствуйте! Оформили полный возврат средств по вашему заказу #{order_id}. "
                     "Приносим извинения за неудобства.",
}
_READY = False


def _order_money(order) -> float:
    """Страница заказа хранит сумму в sum, виджет продаж — в price."""
    raw = getattr(order, "price", None)
    if raw is None:
        raw = getattr(order, "sum", 0)
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def load_autoback_config() -> configparser.SectionProxy:
    cfg = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        cfg.read(CONFIG_FILE, encoding="utf-8")
    if not cfg.has_section("Autoback"):
        cfg.add_section("Autoback")
    changed = False
    for key, value in DEFAULTS.items():
        if not cfg.has_option("Autoback", key):
            cfg.set("Autoback", key, value)
            changed = True
    if changed:
        from shop_core.fileio import write_config
        write_config(CONFIG_FILE, cfg)
    return cfg["Autoback"]


def decide(mode: str, price: float, max_refund: float, delivered: bool, skip_if_delivered: bool,
           buyer_refunds_30d: int, buyer_limit: int, refunded_today: float, daily_limit: float) -> tuple[str, str]:
    """auto — вернуть сразу, ask — спросить владельца. Чистая функция, покрыта тестами."""
    if (mode or "ask").strip().lower() != "auto":
        return "ask", "ручное подтверждение"
    if price > max_refund:
        return "ask", f"сумма {price:.0f} ₽ выше автолимита {max_refund:.0f} ₽"
    if delivered and skip_if_delivered:
        return "ask", "товар по заказу уже выдан автоматически"
    if buyer_refunds_30d >= buyer_limit:
        return "ask", "у этого покупателя уже был возврат за 30 дней"
    if refunded_today + price > daily_limit:
        return "ask", f"дневной лимит автовозвратов {daily_limit:.0f} ₽ исчерпан"
    return "auto", "в пределах лимитов"


def _was_delivered(order_id: str) -> bool:
    oid = str(order_id)
    with get_db() as conn:
        fin = conn.execute(
            "SELECT 1 FROM finance_log WHERE order_id = ? AND plugin_name != ? LIMIT 1", (oid, PLUGIN),
        ).fetchone()
        claim = conn.execute(
            "SELECT 1 FROM processed_orders WHERE order_id = ? AND plugin_name = '__delivery__' LIMIT 1", (oid,),
        ).fetchone()
    return bool(fin or claim)


def _buyer_refunds_30d(buyer: str) -> int:
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM autoback_log WHERE lower(buyer_name) = lower(?) AND refunded_at > ?",
            (buyer or "", time.time() - 30 * 86400),
        ).fetchone()
    return int(row[0] or 0)


def _refunded_today() -> float:
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    with get_db() as conn:
        row = conn.execute("SELECT COALESCE(SUM(price), 0) FROM autoback_log WHERE refunded_at >= ?", (start,)).fetchone()
    return float(row[0] or 0)


def _get_pending(order_id: str):
    with get_db() as conn:
        return conn.execute("SELECT * FROM autoback_pending WHERE order_id = ?", (str(order_id),)).fetchone()


def _set_status(order_id: str, status: str, user_id: int | None = None) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE autoback_pending SET status = ?, decided_by = ?, decided_at = ? WHERE order_id = ?",
            (status, user_id, time.time(), str(order_id)),
        )


def _refund(cardinal, order_id: str, chat_id, buyer: str, stars: int, price: float, currency: str,
            review_text: str) -> tuple[bool, str]:
    """Возврат с замком по заказу: повторно один заказ не вернётся."""
    if not claim_order(str(order_id), PLUGIN):
        return False, "по этому заказу уже был возврат"
    try:
        cardinal.account.refund(order_id)
    except Exception as ex:
        release_claim(str(order_id), PLUGIN)
        logger.error("[Autoback] refund #%s: %s", order_id, ex)
        return False, f"FunPay не принял возврат: {str(ex)[:200]}"
    with get_db() as conn:
        conn.execute(
            """INSERT INTO autoback_log (order_id, buyer_name, stars, price, currency, review_text, refunded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(order_id), buyer, stars, price, currency, review_text, time.time()),
        )
    cfg = load_autoback_config()
    if cfg.getboolean("send_buyer_message", fallback=True) and chat_id:
        text = cfg.get("buyer_message", "").replace("{order_id}", str(order_id))
        if text.strip():
            bot_send(cardinal, chat_id, text, buyer)
    logger.info("[Autoback] возврат #%s (%.2f).", order_id, price)
    return True, "возврат оформлен"


def _ask_kb(order_id: str, price: float) -> K:
    kb = K()
    kb.row(
        B(f"↩️ Вернуть {price:.0f} ₽", callback_data=f"{CB}yes:{order_id}"),
        B("✋ Не возвращать", callback_data=f"{CB}no:{order_id}"),
    )
    return kb


def _review_block(order_id, stars, price, currency, buyer, review_text) -> str:
    return (
        f"Заказ: <code>#{html.escape(str(order_id))}</code> · {stars}★ · <b>{price:.0f} {html.escape(str(currency))}</b>\n"
        f"Покупатель: <b>{html.escape(buyer or '—')}</b>\n"
        f"Отзыв: <i>{html.escape((review_text or '—')[:500])}</i>"
    )


def process_review_event(cardinal, event):
    try:
        cfg = load_autoback_config()
        if not cfg.getboolean("enabled", fallback=True):
            return
        msg = getattr(event, "message", None)
        if not msg or msg.type not in (MessageTypes.NEW_FEEDBACK, MessageTypes.FEEDBACK_CHANGED):
            return
        if getattr(msg, "i_am_buyer", False):
            return
        order = cardinal.get_order_from_object(msg)
        if not order or not order.review:
            return
        stars = order.review.stars
        if not isinstance(stars, int):
            return
        if not (cfg.getint("min_stars", fallback=1) <= stars <= cfg.getint("max_stars", fallback=3)):
            return
        oid = str(order.id)
        if already_processed(oid, PLUGIN) or _get_pending(oid):
            return
        price = _order_money(order)
        buyer = getattr(order, "buyer_username", "") or ""
        currency = str(getattr(order, "currency", "") or "₽")
        review_text = getattr(order.review, "text", "") or ""
        decision, reason = decide(
            cfg.get("mode", "ask"), price, cfg.getfloat("max_refund_rub", fallback=300.0),
            _was_delivered(oid), cfg.getboolean("skip_if_delivered", fallback=True),
            _buyer_refunds_30d(buyer), cfg.getint("buyer_limit_30d", fallback=1),
            _refunded_today(), cfg.getfloat("daily_limit_rub", fallback=1000.0),
        )
        block = _review_block(oid, stars, price, currency, buyer, review_text)
        if decision == "auto" and not (is_frozen() or is_panic()):
            if is_dry_run():
                notify(cardinal, f"🧪 Учебный режим: автовозврат не отправлен.\n{block}", True)
                return
            ok, why = _refund(cardinal, oid, msg.chat_id, buyer, stars, price, currency, review_text)
            notify(cardinal, ("🛡️ <b>Автовозврат</b> (" + html.escape(reason) + ")\n" if ok
                              else f"❌ <b>Автовозврат не прошёл:</b> {html.escape(why)}\n") + block, True)
            return
        with get_db() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO autoback_pending
                   (order_id, chat_id, buyer_name, stars, price, currency, review_text, reason, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (oid, str(msg.chat_id), buyer, stars, price, currency, review_text, reason, time.time()),
            )
        notify(
            cardinal,
            f"⚠️ <b>Отзыв {stars}★ — вернуть деньги?</b>\nПочему спрашиваю: {html.escape(reason)}.\n{block}",
            True,
            keyboard=_ask_kb(oid, price),
        )
    except Exception as ex:
        logger.error("[Autoback] Ошибка выполнения: %s", ex, exc_info=True)


def _can_decide(cardinal, uid: int) -> bool:
    from shop_core.team import is_owner, owner_id
    tg = getattr(cardinal, "telegram", None)
    if not tg or uid not in getattr(tg, "authorized_users", {}):
        return False
    if not owner_id() or is_owner(uid):
        return True
    return load_autoback_config().getboolean("refund_by_operators", fallback=False)


def handle_callback(cardinal, c) -> None:
    bot = cardinal.telegram.bot
    parts = (c.data or "").split(":", 2)
    if len(parts) != 3:
        bot.answer_callback_query(c.id)
        return
    action, oid = parts[1], parts[2]
    if not _can_decide(cardinal, c.from_user.id):
        bot.answer_callback_query(c.id, "Возврат подтверждает владелец.", show_alert=True)
        return
    row = _get_pending(oid)
    if not row or row["status"] != "pending":
        bot.answer_callback_query(c.id, "По этому заказу уже решено.")
        return
    block = _review_block(oid, row["stars"], float(row["price"] or 0), row["currency"], row["buyer_name"],
                          row["review_text"])
    if action == "no":
        claim_order(oid, PLUGIN)
        _set_status(oid, "declined", c.from_user.id)
        result = f"✋ Возврат не делаю.\n{block}"
    elif is_dry_run():
        result = f"🧪 Учебный режим: возврат не отправлен.\n{block}"
    elif is_frozen() or is_panic():
        bot.answer_callback_query(c.id, "Сейчас стоп или заморозка — сначала сними их.", show_alert=True)
        return
    else:
        chat = row["chat_id"]
        chat = int(chat) if chat and str(chat).lstrip("-").isdigit() else chat
        ok, why = _refund(cardinal, oid, chat, row["buyer_name"], int(row["stars"] or 0),
                          float(row["price"] or 0), row["currency"], row["review_text"])
        if not ok:
            bot.answer_callback_query(c.id, why[:180], show_alert=True)
            return
        _set_status(oid, "refunded", c.from_user.id)
        result = f"↩️ Возврат оформлен.\n{block}"
    bot.answer_callback_query(c.id)
    try:
        bot.edit_message_text(result, c.message.chat.id, c.message.id, parse_mode="HTML")
    except Exception:
        bot.send_message(c.message.chat.id, result, parse_mode="HTML")


def on_message_feedback(cardinal, event):
    Thread(target=process_review_event, args=(cardinal, event), daemon=True).start()


def init_settings(cardinal):
    global _READY
    load_autoback_config()

    def status():
        cfg = load_autoback_config()
        mode = cfg.get("mode", "ask")
        return (
            f"Режим: <b>{'автоматически в лимитах' if mode == 'auto' else 'спрашивать меня'}</b>\n"
            f"Автолимит: <code>{cfg.get('max_refund_rub', '300')}</code> ₽, "
            f"в день до <code>{cfg.get('daily_limit_rub', '1000')}</code> ₽, "
            f"на покупателя {cfg.get('buyer_limit_30d', '1')} за 30 дней\n"
            f"Звёзды: {cfg.get('min_stars', '1')}–{cfg.get('max_stars', '3')}"
        )

    def mode_auto() -> bool:
        return load_autoback_config().get("mode", "ask").strip().lower() == "auto"

    SettingsPage(UUID, NAME, "Возврат при отзыве 1–3★. По умолчанию — кнопки в Telegram.") \
        .add_toggle("enabled", "Следить за плохими отзывами",
                    lambda: ini_bool(CONFIG_FILE, "Autoback", "enabled", True),
                    lambda _v: flip_ini(CONFIG_FILE, "Autoback", "enabled", True)) \
        .add_toggle("mode", "Возвращать сам в пределах лимитов", mode_auto,
                    lambda _v: set_ini(CONFIG_FILE, "Autoback", "mode", "ask" if mode_auto() else "auto")) \
        .add_toggle("msg", "Писать покупателю после возврата",
                    lambda: ini_bool(CONFIG_FILE, "Autoback", "send_buyer_message", True),
                    lambda _v: flip_ini(CONFIG_FILE, "Autoback", "send_buyer_message", True)) \
        .set_status(status) \
        .attach(cardinal)
    tg = getattr(cardinal, "telegram", None)
    if _READY or not tg or not getattr(tg, "bot", None):
        return
    _READY = True
    tg.cbq_handler(lambda c: handle_callback(cardinal, c), lambda c: (c.data or "").startswith(CB))


BIND_TO_PRE_INIT = [init_settings]
BIND_TO_NEW_MESSAGE = [on_message_feedback]
