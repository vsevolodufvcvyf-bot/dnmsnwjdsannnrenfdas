# -*- coding: utf-8 -*-
"""Кто отправляет сообщение в чат FunPay: бот или человек из Telegram.

По умолчанию — бот. Человеком помечаются только ответы продавца из Telegram, иначе
автовыдача и приветствия Cardinal отключали ИИ в чате на сутки.
"""
from __future__ import annotations

import contextlib
import contextvars

MSG_ORIGIN = contextvars.ContextVar("fp_msg_origin", default="bot")


@contextlib.contextmanager
def human_origin():
    token = MSG_ORIGIN.set("human")
    try:
        yield
    finally:
        MSG_ORIGIN.reset(token)


@contextlib.contextmanager
def bot_origin():
    token = MSG_ORIGIN.set("bot")
    try:
        yield
    finally:
        MSG_ORIGIN.reset(token)
