# -*- coding: utf-8 -*-
"""Безопасный HTML для Telegram.

Разрешённые теги Telegram сохраняются, всё остальное экранируется. Без этого текст ошибки
вида `<urllib3.connection...>`, ник или отзыв с `<` и `&` делали сообщение невалидным, и
Telegram молча его отбрасывал.
"""
from __future__ import annotations

import html
import re

LIMIT = 4096
CAPTION_LIMIT = 1024

_SIMPLE = ("b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre", "tg-spoiler", "blockquote")
_TOKEN_RE = re.compile(
    r"(?P<tag></?(?:" + "|".join(_SIMPLE) + r")>"
    r"|<a\s+href=(?:\"[^\"<>]*\"|'[^'<>]*')\s*>|</a>"
    r"|<span\s+class=\"tg-spoiler\">|</span>"
    r"|<code\s+class=\"language-[\w+-]+\">)"
    r"|(?P<entity>&(?:lt|gt|amp|quot|#\d{1,7}|#x[0-9a-fA-F]{1,6});)",
    re.IGNORECASE,
)
_NAME_RE = re.compile(r"</?\s*([a-z-]+)", re.IGNORECASE)


def _tag_name(tag: str) -> str:
    m = _NAME_RE.match(tag)
    return m.group(1).lower() if m else ""


def _balanced(tags: list[str]) -> bool:
    stack: list[str] = []
    for tag in tags:
        name = _tag_name(tag)
        if tag.startswith("</"):
            if not stack or stack[-1] != name:
                return False
            stack.pop()
        else:
            stack.append(name)
    return not stack


def safe_html(text):
    """Экранирует всё, что не является разрешённым тегом или сущностью. Несбалансированные теги
    превращаются в обычный текст, чтобы сообщение всё равно дошло."""
    if not isinstance(text, str) or not text:
        return text
    out: list[str] = []
    tags: list[str] = []
    pos = 0
    for m in _TOKEN_RE.finditer(text):
        out.append(html.escape(text[pos:m.start()], quote=False))
        token = m.group(0)
        out.append(token)
        if m.group("tag"):
            tags.append(token)
        pos = m.end()
    out.append(html.escape(text[pos:], quote=False))
    if _balanced(tags):
        return "".join(out)
    return html.escape(strip_tags(text), quote=False)


def strip_tags(text: str) -> str:
    plain = _TOKEN_RE.sub(lambda m: html.unescape(m.group(0)) if m.group("entity") else "", text)
    return plain


def split_message(text: str, limit: int = LIMIT) -> list[str]:
    """Режет по строкам, не длиннее limit. Каждый кусок снова проверяется на валидность HTML."""
    if not text or len(text) <= limit:
        return [text]
    chunks: list[str] = []
    cur = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{cur}\n{line}" if cur else line
        if len(candidate) > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = candidate
    if cur:
        chunks.append(cur)
    return [safe_html(c) for c in chunks if c]


def install(bot) -> None:
    """Оборачивает send_message / edit_message_text / send_photo у экземпляра TeleBot."""
    if getattr(bot, "_safe_html_installed", False):
        return
    default_mode = (getattr(bot, "parse_mode", None) or "").upper()
    orig_send = bot.send_message
    orig_edit = bot.edit_message_text
    orig_photo = bot.send_photo

    def _is_html(mode) -> bool:
        return (mode if mode is not None else default_mode or "").upper() == "HTML"

    def send_message(chat_id, text, *args, **kwargs):
        mode = kwargs.get("parse_mode", args[0] if args else None)
        if not _is_html(mode) or not isinstance(text, str):
            return orig_send(chat_id, text, *args, **kwargs)
        parts = split_message(safe_html(text))
        if len(parts) == 1:
            return orig_send(chat_id, parts[0], *args, **kwargs)
        markup = kwargs.pop("reply_markup", None)
        last = None
        for i, part in enumerate(parts):
            extra = dict(kwargs)
            if i == len(parts) - 1 and markup is not None:
                extra["reply_markup"] = markup
            last = orig_send(chat_id, part, *args, **extra)
        return last

    def edit_message_text(text, *args, **kwargs):
        mode = kwargs.get("parse_mode")
        if _is_html(mode) and isinstance(text, str):
            text = safe_html(text)
            if len(text) > LIMIT:
                text = safe_html(strip_tags(text)[: LIMIT - 1] + "…")
        return orig_edit(text, *args, **kwargs)

    def send_photo(chat_id, photo, caption=None, *args, **kwargs):
        mode = kwargs.get("parse_mode")
        if _is_html(mode) and isinstance(caption, str):
            caption = safe_html(caption)
            if len(caption) > CAPTION_LIMIT:
                rest = caption
                caption = None
                msg = orig_photo(chat_id, photo, caption, *args, **kwargs)
                send_message(chat_id, rest)
                return msg
        return orig_photo(chat_id, photo, caption, *args, **kwargs)

    bot.send_message = send_message
    bot.edit_message_text = edit_message_text
    bot.send_photo = send_photo
    bot._safe_html_installed = True
