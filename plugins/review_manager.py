# -*- coding: utf-8 -*-
from __future__ import annotations
import logging
import time
import random
from threading import Thread

from FunPayAPI.common.enums import MessageTypes
from shop_core.bus import bot_send, notify
from shop_core.db import get_db
from shop_core.settings import ini_bool, flip_ini
from shop_core.plugin_settings import SettingsPage

logger = logging.getLogger("FPC.ReviewManager")

NAME = "Review Manager & Bonus"
VERSION = "1.0.0"
DESCRIPTION = "Автоответы на отзывы 4-5 звезд и автопродление аренды на +1 час за 5 звезд"
CREDITS = "Cardinal Community"
UUID = "7d4b2e19-5a8c-4f31-9e2d-1a6f8b3c5e7a"
SETTINGS_PAGE = True
CONFIG_FILE = "configs/review.cfg"

BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}

THANK_YOU_REPLIES = [
    "Спасибо за покупку и отличный отзыв! Всегда рады видеть вас снова, приятной игры! 🎮",
    "Благодарим за высокую оценку! Рады были помочь, обращайтесь в любое время! ⭐",
    "Спасибо за доверие! Отличного вам настроения и побед в игре! 🔥"
]

def handle_good_review(cardinal, event):
    try:
        msg = getattr(event, "message", None)
        if not msg or msg.type not in [MessageTypes.NEW_FEEDBACK, MessageTypes.FEEDBACK_CHANGED]:
            return

        if getattr(msg, "i_am_buyer", False):
            return

        order = cardinal.get_order_from_object(msg)
        if not order or not order.review:
            return

        if not ini_bool(CONFIG_FILE, "Review", "enabled", True):
            return

        stars = order.review.stars
        if stars not in [4, 5]:
            return

        if not order.review.reply:
            reply_text = random.choice(THANK_YOU_REPLIES)
            try:
                cardinal.account.send_review(order.id, reply_text, rating=stars)
                logger.info(f"[ReviewManager] Ответ на отзыв #{order.id}: {reply_text}")
            except Exception as e:
                logger.debug(f"[ReviewManager] Не удалось отправить ответ: {e}")

        if stars == 5 and ini_bool(CONFIG_FILE, "Review", "bonus_hour", True):
            now = time.time()
            from shop_core.bus import peer_ids
            aid = getattr(getattr(cardinal, "account", None), "id", None)
            ids = peer_ids(msg.chat_id, getattr(order, "buyer_id", None), account_id=aid) or [-1]
            q = ",".join("?" * len(ids))
            with get_db() as conn:
                c = conn.cursor()
                c.execute(f"""
                    SELECT account_id, account_name, expire_time 
                    FROM mafile_rentals 
                    WHERE (renter_chat_id IN ({q}) OR renter_node = ? OR renter_name = ?)
                      AND is_rented = 1 AND expire_time > ?
                    ORDER BY expire_time ASC
                """, (*ids, str(msg.chat_id), order.buyer_username, now))
                rental = c.fetchone()

                if rental:
                    from shop_core.finance import claim_order
                    if not claim_order(f"{order.id}_bonus", "review_bonus"):
                        return
                    new_exp = rental["expire_time"] + 3600
                    c.execute("UPDATE mafile_rentals SET expire_time = ? WHERE account_id = ?", (new_exp, rental["account_id"]))
                    bonus_msg = (
                        f"Бонус за высокую оценку: аренда ({rental['account_name']}) продлена на +1 час."
                    )
                    bot_send(cardinal, msg.chat_id, bonus_msg, order.buyer_username)
                    if cardinal.telegram:
                        cardinal.telegram.send_notification(f"⭐ <b>[ReviewManager] Начислен бонус +1 час к аренде для {order.buyer_username}!</b>")

    except Exception as ex:
        logger.error(f"[ReviewManager] Ошибка: {ex}")

def on_review_event(cardinal, event):
    Thread(target=handle_good_review, args=(cardinal, event), daemon=True).start()

def init_settings(cardinal):
    SettingsPage(UUID, NAME, "Ответ на 4–5★ и бонус +1 час аренды за 5★.") \
        .add_toggle("enabled", "Автоответы на отзывы",
                    lambda: ini_bool(CONFIG_FILE, "Review", "enabled", True),
                    lambda _v: flip_ini(CONFIG_FILE, "Review", "enabled", True)) \
        .add_toggle("bonus", "Бонус +1 час за 5★",
                    lambda: ini_bool(CONFIG_FILE, "Review", "bonus_hour", True),
                    lambda _v: flip_ini(CONFIG_FILE, "Review", "bonus_hour", True)) \
        .attach(cardinal)


BIND_TO_PRE_INIT = [init_settings]
BIND_TO_NEW_MESSAGE = [on_review_event]
