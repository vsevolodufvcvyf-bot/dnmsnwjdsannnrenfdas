"""
В данном модуле описаны функции для ПУ настроек прокси.
Модуль реализован в виде плагина.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cardinal import Cardinal
from telebot.types import CallbackQuery, Message
import logging

from locales.localizer import Localizer
from . import CBT

logger = logging.getLogger("TGBot")
localizer = Localizer()
_ = localizer.translate

PLUGIN_CB_PREFIXES = [
    "PANEL:", "PSET:", "MKT:", "RST:", "OPS:", "SHOP:", "WAL:", "METH:",
    "CHECK:", "HOW:", "MICRO:", "APR:", "STAR:", "GIFT:", "MA_RENT",
    "TEAM:", "ABK:", "CNF:", "TOOLS:",
    f"{CBT.PLUGIN_SETTINGS}:",
]


def register_callback_prefix(*prefixes: str) -> None:
    for p in prefixes:
        p = str(p)
        if p and p not in PLUGIN_CB_PREFIXES:
            PLUGIN_CB_PREFIXES.append(p)


def init_default_cp(crd: Cardinal, *args):
    tg = crd.telegram
    bot = tg.bot

    def default_callback_answer(c: CallbackQuery):
        """
        Отвечает на колбеки, которые не поймал ни один хендлер.
        Регистрируется после плагинов: first-match, этот хендлер — запасной.
        """
        data = c.data or ""
        if any(data.startswith(p) for p in PLUGIN_CB_PREFIXES):
            return
        bot.answer_callback_query(c.id, text=_(c.data), show_alert=True)

    tg.cbq_handler(default_callback_answer, lambda c: True)


BIND_TO_POST_INIT = [init_default_cp]
