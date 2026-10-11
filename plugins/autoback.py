# -*- coding: utf-8 -*-
from __future__ import annotations
import configparser
import logging
import time
import os
from threading import Thread

from FunPayAPI.common.enums import MessageTypes
from plugins._common.bus import bot_send, is_frozen, notify
from plugins._common.db import get_db
from plugins._common.finance import claim_order, release_claim
from plugins._common.settings import is_dry_run, is_panic, ini_bool, flip_ini
from plugins._common.plugin_settings import SettingsPage

logger = logging.getLogger("FPC.Autoback")

NAME = "Autoback Rating Shield"
VERSION = "1.0.0"
DESCRIPTION = "Мгновенный автовозврат при получении отзыва 1-3 звезды для автоматического удаления негатива"
CREDITS = "Cardinal Community"
UUID = "3c8e4a91-1d5f-4a7b-8c2e-9f3a1b4c6d8e"
SETTINGS_PAGE = True

BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}

CONFIG_FILE = "configs/autoback.cfg"

def _order_money(order) -> float:
    """Страница заказа хранит сумму в sum, виджет продаж — в price."""
    raw = getattr(order, "price", None)
    if raw is None:
        raw = getattr(order, "sum", 0)
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def load_autoback_config():
    cfg = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        cfg.read(CONFIG_FILE, encoding="utf-8")
    else:
        cfg["Autoback"] = {
            "enabled": "1",
            "max_refund_rub": "300.0",
            "min_stars": "1",
            "max_stars": "3",
            "send_buyer_message": "1",
            "buyer_message": "Здравствуйте! Оформили полный возврат средств по вашему заказу #{order_id}. Приносим искренние извинения за неудобства!"
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)
    return cfg["Autoback"]

def process_review_event(cardinal, event):
    try:
        cfg = load_autoback_config()
        if not cfg.getboolean("enabled"):
            return

        msg = getattr(event, "message", None)
        if not msg or msg.type not in [MessageTypes.NEW_FEEDBACK, MessageTypes.FEEDBACK_CHANGED]:
            return

        if getattr(msg, "i_am_buyer", False):
            return

        order = cardinal.get_order_from_object(msg)
        if not order or not order.review:
            return

        stars = order.review.stars
        if not isinstance(stars, int):
            return
        min_stars = cfg.getint("min_stars", 1)
        max_stars = cfg.getint("max_stars", 3)
        max_price = cfg.getfloat("max_refund_rub", 300.0)
        price = _order_money(order)

        if not (min_stars <= stars <= max_stars):
            return
        if is_frozen() or is_panic():
            return
        if not claim_order(str(order.id), "autoback"):
            return
        if is_dry_run():
            notify(cardinal, f"🧪 DRY-RUN Autoback #{order.id} {stars}* — возврат не отправлялся.", True)
            return

        if price > max_price:
            logger.warning("[Autoback] Заказ #%s (%s*) выше лимита (%.2f > %.2f).", order.id, stars, price, max_price)
            if cardinal.telegram:
                cardinal.telegram.send_notification(
                    f"⚠️ <b>[Autoback] Отзыв {stars}★, сумма {price:.0f} ₽ выше лимита {max_price:.0f} ₽.</b>\n"
                    f"Заказ: <code>#{order.id}</code> от <b>{order.buyer_username}</b>\n"
                    f"Текст: <i>{order.review.text}</i>"
                )
            return

        try:
            cardinal.account.refund(order.id)
        except Exception as ex:
            release_claim(str(order.id), "autoback")
            logger.error("[Autoback] refund #%s: %s", order.id, ex)
            notify(cardinal, f"❌ Autoback #{order.id}: возврат не прошёл, можно повторить. {ex}", True)
            return
        logger.info("[Autoback] возврат #%s (%.2f).", order.id, price)

        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO autoback_log (order_id, buyer_name, stars, price, currency, review_text, refunded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (order.id, order.buyer_username, stars, price, str(order.currency), order.review.text, time.time()))

        if cfg.getboolean("send_buyer_message"):
            reply_text = cfg.get("buyer_message", "").replace("{order_id}", order.id)
            bot_send(cardinal, msg.chat_id, reply_text, order.buyer_username)

        if cardinal.telegram:
            cardinal.telegram.send_notification(
                f"🛡️ <b>[AUTOBACK] НЕГАТИВНЫЙ ОТЗЫВ УДАЛЕН ВОЗВРАТОМ!</b>\n\n"
                f"📇 Заказ: <code>#{order.id}</code>\n"
                f"⭐ Оценка: <b>{stars} зв.</b>\n"
                f"💵 Сумма: <b>{price:.0f} {order.currency}</b>\n"
                f"👤 Покупатель: <b>{order.buyer_username}</b>\n"
                f"💬 Отзыв: <i>{order.review.text}</i>\n\n"
                f"<i>Заказ возвращен, негатив удален с FunPay автоматически!</i>"
            )

    except Exception as ex:
        logger.error(f"[Autoback] Ошибка выполнения: {ex}", exc_info=True)

def on_message_feedback(cardinal, event):
    Thread(target=process_review_event, args=(cardinal, event), daemon=True).start()

def init_settings(cardinal):
    def status():
        cfg = load_autoback_config()
        return (
            f"Лимит возврата: <code>{cfg.get('max_refund_rub', '300')}</code> ₽\n"
            f"Звёзды: {cfg.get('min_stars', '1')}–{cfg.get('max_stars', '3')}"
        )

    SettingsPage(UUID, NAME, "Автовозврат при отзыве 1–3★. Лимит в configs/autoback.cfg.") \
        .add_toggle("enabled", "Автовозврат",
                    lambda: ini_bool(CONFIG_FILE, "Autoback", "enabled", True),
                    lambda _v: flip_ini(CONFIG_FILE, "Autoback", "enabled", True)) \
        .add_toggle("msg", "Писать покупателю",
                    lambda: ini_bool(CONFIG_FILE, "Autoback", "send_buyer_message", True),
                    lambda _v: flip_ini(CONFIG_FILE, "Autoback", "send_buyer_message", True)) \
        .set_status(status) \
        .attach(cardinal)


BIND_TO_PRE_INIT = [init_settings]
BIND_TO_NEW_MESSAGE = [on_message_feedback]
