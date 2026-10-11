# -*- coding: utf-8 -*-
"""Telegram settings page for Cardinal plugins (SETTINGS_PAGE + CBT.PLUGIN_SETTINGS)."""
from __future__ import annotations

import html
import logging
from typing import Callable

from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B

from tg_bot import CBT

logger = logging.getLogger("FPC.PluginSettings")
_ATTACHED: set[str] = set()


def _mark(on: bool) -> str:
    return "✅" if on else "❌"


class SettingsPage:
    def __init__(self, uuid: str, title: str, hint: str = ""):
        self.uuid = uuid
        self.title = title
        self.hint = hint
        self.toggles: list[tuple[str, str, Callable[[], bool], Callable[[bool], None]]] = []
        self.status_fn: Callable[[], str] | None = None
        try:
            from shop_core.howto import for_uuid
            self.howto = for_uuid(uuid)
        except Exception:
            self.howto = ""

    def add_toggle(self, key: str, label: str, getter: Callable[[], bool], setter: Callable[[bool], None]):
        self.toggles.append((key, label, getter, setter))
        return self

    def set_status(self, fn: Callable[[], str]):
        self.status_fn = fn
        return self

    def _text_kb(self, offset: str) -> tuple[str, K]:
        lines = [f"<b>⚙️ {html.escape(self.title)}</b>"]
        if self.hint:
            lines.append(html.escape(self.hint))
        if self.status_fn:
            try:
                extra = self.status_fn() or ""
            except Exception as ex:
                extra = f"Статус недоступен: {ex}"
            if extra:
                lines.append("")
                lines.append(extra)
        kb = K()
        if self.howto:
            kb.add(B("📖 Как настроить", callback_data=f"HOW:{self.uuid}:{offset}"))
        for key, label, getter, _setter in self.toggles:
            try:
                on = bool(getter())
            except Exception:
                on = False
            kb.add(B(f"{_mark(on)} {label}", callback_data=f"PSET:{self.uuid}:{key}:{offset}"))
        kb.add(B("◀️ Назад к плагину", callback_data=f"{CBT.EDIT_PLUGIN}:{self.uuid}:{offset}"))
        return "\n".join(lines), kb

    def _render(self, cardinal, offset: str, c):
        bot = cardinal.telegram.bot
        text, kb = self._text_kb(offset)
        try:
            bot.edit_message_text(
                text, c.message.chat.id, c.message.id,
                reply_markup=kb, parse_mode="HTML",
            )
        except Exception:
            bot.send_message(c.message.chat.id, text, reply_markup=kb, parse_mode="HTML")

    def attach(self, cardinal) -> None:
        if self.uuid in _ATTACHED:
            return
        tg = getattr(cardinal, "telegram", None)
        if not tg or not getattr(tg, "bot", None):
            return
        _ATTACHED.add(self.uuid)
        page = self

        def open_page(c):
            parts = (c.data or "").split(":")
            uuid, offset = parts[1], parts[2] if len(parts) > 2 else "0"
            if uuid != page.uuid:
                return
            page._render(cardinal, offset, c)
            try:
                tg.bot.answer_callback_query(c.id)
            except Exception:
                logger.debug("TRACEBACK", exc_info=True)

        def on_toggle(c):
            parts = (c.data or "").split(":")
            if len(parts) < 4:
                return
            _prefix, uuid, key, offset = parts[0], parts[1], parts[2], parts[3]
            if uuid != page.uuid:
                return
            for t_key, _label, getter, setter in page.toggles:
                if t_key != key:
                    continue
                try:
                    setter(not bool(getter()))
                except Exception:
                    logger.debug("TRACEBACK", exc_info=True)
                break
            page._render(cardinal, offset, c)
            try:
                tg.bot.answer_callback_query(c.id, "Сохранено")
            except Exception:
                logger.debug("TRACEBACK", exc_info=True)

        def show_howto(c):
            parts = (c.data or "").split(":")
            uuid = parts[1] if len(parts) > 1 else ""
            if uuid != page.uuid:
                return
            text = page.howto or "Инструкции нет."
            try:
                tg.bot.answer_callback_query(c.id)
            except Exception:
                logger.debug("TRACEBACK", exc_info=True)
            tg.bot.send_message(c.message.chat.id, text, parse_mode="HTML")

        tg.cbq_handler(open_page, lambda c: (c.data or "").startswith(f"{CBT.PLUGIN_SETTINGS}:{self.uuid}"))
        tg.cbq_handler(on_toggle, lambda c: (c.data or "").startswith(f"PSET:{self.uuid}:"))
        tg.cbq_handler(show_howto, lambda c: (c.data or "").startswith(f"HOW:{self.uuid}:"))
