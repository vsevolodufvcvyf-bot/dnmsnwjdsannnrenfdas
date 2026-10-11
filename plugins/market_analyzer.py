# -*- coding: utf-8 -*-
"""Цена рынка: описываешь товар — бот ищет похожие лоты и говорит, за сколько выставлять."""
from __future__ import annotations

import configparser
import logging
import math
import os
import re
import statistics
from html import escape

from FunPayAPI.common.enums import SubCategoryTypes
from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, Message, CallbackQuery

from shop_core.settings import commission
from shop_core.plugin_settings import SettingsPage
from shop_core.panels import margin_report

logger = logging.getLogger("FPC.MarketAnalyzer")

NAME = "Цена рынка"
VERSION = "2.0.0"
DESCRIPTION = "Пишешь что продаёшь — бот ищет похожие лоты и рекомендует цену"
CREDITS = "nnanserShop"
UUID = "b1e0aa01-2222-4c00-9d02-000000000002"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}
_TG_CMDS = False
CONFIG_FILE = "configs/market.cfg"
_WAIT: dict[int, dict] = {}
_TOKEN = re.compile(r"[a-zа-я0-9]+", re.IGNORECASE)


def load_cfg():
    cfg = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        cfg.read(CONFIG_FILE, encoding="utf-8")
    return cfg


def clear_wait(uid: int) -> None:
    _WAIT.pop(int(uid), None)


def ask_price(bot, chat_id: int, uid: int) -> None:
    try:
        from tg_bot.panel_ui import clear_all_waits
        clear_all_waits(uid)
    except Exception:
        logger.debug("TRACEBACK", exc_info=True)
    _WAIT[int(uid)] = {"mode": "desc"}
    bot.send_message(
        chat_id,
        "📈 <b>За сколько выставлять?</b>\n\n"
        "Напиши своими словами, что хочешь продавать или сдавать.\n\n"
        "Примеры:\n"
        "• <code>аренда Steam на 2 часа, полный доступ</code>\n"
        "• <code>CS2 аккаунт, Prime</code>\n"
        "• <code>GTA 5, аренда, 24 часа</code>\n\n"
        "Бот найдёт похожие лоты, посмотрит у кого есть продажи (отзывы) и скажет цену.",
        parse_mode="HTML",
    )


def token_coverage_ok(n_tokens: int, hit: int) -> bool:
    """Один общий токен вроде «аккаунт» не делает дешёвый лот похожим."""
    if n_tokens <= 0:
        return True
    if n_tokens == 1:
        return hit >= 1
    return hit >= max(2, math.ceil(n_tokens * 0.6))


def _match_hit(tokens: list[str], hay: str) -> int | None:
    if not tokens:
        return 1
    hit = sum(1 for t in tokens if t in hay)
    if not token_coverage_ok(len(tokens), hit):
        return None
    return hit


def _tokens(text: str) -> list[str]:
    raw = (text or "").lower().replace("ё", "е")
    words = _TOKEN.findall(raw)
    stop = {
        "на", "и", "в", "с", "для", "по", "из", "к", "от", "это", "хочу", "сдать",
        "продать", "лот", "акк", "час", "часа", "часов", "the", "a", "of",
        "аккаунт", "аккаунты", "аккаунта", "аккаунтов", "ранг", "ранга", "рангом",
        "lvl", "уровень", "уровня", "лвл",
    }
    return [w for w in words if len(w) >= 2 and w not in stop]


def _score_name(query_tokens: list[str], name: str) -> int:
    hay = (name or "").lower().replace("ё", "е")
    score = 0
    for t in query_tokens:
        if t in hay:
            score += 3 if len(t) > 3 else 2
    return score


def find_categories(cardinal, query: str, limit: int = 6) -> list:
    tokens = _tokens(query)
    if not tokens:
        return []
    acc = getattr(cardinal, "account", None)
    subs = list(getattr(acc, "subcategories", None) or [])
    scored = []
    for sc in subs:
        if getattr(sc, "type", None) is not SubCategoryTypes.COMMON:
            continue
        full = getattr(sc, "fullname", None) or f"{getattr(sc, 'name', '')} {getattr(getattr(sc, 'category', None), 'name', '')}"
        sc_score = _score_name(tokens, full)
        if sc_score <= 0:
            continue
        scored.append((sc_score, sc))
    scored.sort(key=lambda x: (-x[0], getattr(x[1], "fullname", "")))
    # unique by id
    seen = set()
    out = []
    for _s, sc in scored:
        if sc.id in seen:
            continue
        seen.add(sc.id)
        out.append(sc)
        if len(out) >= limit:
            break
    return out


def _lot_hay(lot) -> str:
    parts = [
        getattr(lot, "description", "") or "",
        getattr(lot, "server", "") or "",
        getattr(lot, "side", "") or "",
    ]
    seller = getattr(lot, "seller", None)
    if seller:
        parts.append(getattr(seller, "username", "") or "")
    return " ".join(parts).lower().replace("ё", "е")


def _activity(lot) -> int:
    seller = getattr(lot, "seller", None)
    reviews = int(getattr(seller, "reviews", 0) or 0) if seller else 0
    stars = int(getattr(seller, "stars", 0) or 0) if seller else 0
    online = 8 if seller and getattr(seller, "online", False) else 0
    auto = 4 if getattr(lot, "auto", False) else 0
    promo = 6 if getattr(lot, "promo", False) else 0
    return reviews * 3 + stars * 2 + online + auto + promo


def market_stats(cardinal, subcategory_id: int, query: str = "", exclude_seller_id: int | None = None, lots=None,
                 exclude_seller_ids=None) -> dict:
    """Снимок витрины категории: min/med/live_med/cheapest among similar lots."""
    if lots is None:
        lots = cardinal.account.get_subcategory_public_lots(SubCategoryTypes.COMMON, subcategory_id) or []
    skip = set()
    if exclude_seller_ids:
        skip.update(int(x) for x in exclude_seller_ids if x)
    if exclude_seller_id:
        skip.add(int(exclude_seller_id))
    tokens = _tokens(query)
    similar = []
    for lot in lots:
        seller = getattr(lot, "seller", None)
        sid = int(getattr(seller, "id", 0) or 0) if seller else 0
        if sid and sid in skip:
            continue
        try:
            price = float(getattr(lot, "price", 0) or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        hay = _lot_hay(lot)
        hit = _match_hit(tokens, hay)
        if hit is None:
            continue
        similar.append((hit, _activity(lot), price, lot))
    if not similar:
        return {"n": 0, "min": 0.0, "max": 0.0, "med": 0.0, "live_med": 0.0, "q1": 0.0, "cheapest": 0.0}
    similar.sort(key=lambda x: (-x[0], -x[1], x[2]))
    prices = sorted(p for _h, _a, p, _l in similar)
    n = len(prices)
    med = statistics.median(prices)
    by_act = sorted(similar, key=lambda x: -x[1])
    live = by_act[: max(3, n // 2)]
    live_prices = sorted(p for _h, _a, p, _l in live)
    return {
        "n": n,
        "min": prices[0],
        "max": prices[-1],
        "med": med,
        "live_med": statistics.median(live_prices) if live_prices else med,
        "q1": prices[max(0, n // 4)],
        "cheapest": prices[0],
        "similar": similar,
    }


def analyze_query(cardinal, subcategory, query: str, our_cost: float = 0.0, undercut: float = 0.0) -> str:
    lots = cardinal.account.get_subcategory_public_lots(SubCategoryTypes.COMMON, subcategory.id) or []
    tokens = _tokens(query)
    similar = []
    for lot in lots:
        price = getattr(lot, "price", None)
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        hay = _lot_hay(lot)
        hit = _match_hit(tokens, hay)
        if hit is None:
            continue
        similar.append((hit, _activity(lot), price, lot))
    if not similar:
        return (
            f"На витрине <b>{escape(getattr(subcategory, 'fullname', str(subcategory.id)))}</b> "
            "пока нет лотов с ценой.\nПопробуй другими словами или другую категорию."
        )
    similar.sort(key=lambda x: (-x[0], -x[1], x[2]))
    prices = [p for _h, _a, p, _l in similar]
    prices.sort()
    n = len(prices)
    mn, mx = prices[0], prices[-1]
    avg = sum(prices) / n
    med = statistics.median(prices)
    # «живые» продавцы — верхняя половина по активности
    by_act = sorted(similar, key=lambda x: -x[1])
    live = by_act[: max(3, n // 2)]
    live_prices = sorted(p for _h, _a, p, _l in live)
    live_med = statistics.median(live_prices) if live_prices else med
    rec = max(mn, live_med - float(undercut or 0))
    if rec <= 0:
        rec = mn
    # чуть ниже медианы живых, но не демпинг в пол
    q1 = prices[max(0, n // 4)]
    if rec < q1:
        rec = q1
    net = rec * (1.0 - commission())
    margin = net - float(our_cost or 0)
    warn = ""
    if our_cost and margin <= 0:
        warn = "\n\n⚠️ При этой цене ты в минусе. Либо подними цену, либо снизь себестоимость."
    lines = [
        f"📈 <b>За сколько выставлять</b>",
        f"Категория: <b>{escape(getattr(subcategory, 'fullname', ''))}</b>",
        f"Искал: <i>{escape(query)}</i>",
        f"Похожих лотов: <b>{n}</b>",
        "",
        f"Самый дешёвый: <code>{mn:.2f}</code>",
        f"Самый дорогой: <code>{mx:.2f}</code>",
        f"Средняя: <code>{avg:.2f}</code> · медиана: <code>{med:.2f}</code>",
        f"У кого есть продажи (отзывы), медиана: <code>{live_med:.2f}</code>",
        "",
        f"💡 <b>Ставь: {rec:.2f}</b>",
        f"После комиссии FunPay останется ≈ <code>{net:.2f}</code>",
    ]
    if our_cost:
        lines.append(f"Себестоимость: <code>{our_cost:.2f}</code> · чистыми ≈ <b>{margin:.2f}</b>")
    lines.append(warn)
    lines.append("")
    lines.append("<b>Кто рядом по рынку</b> (отзывы ≈ активность продаж):")
    for _h, act, price, lot in similar[:8]:
        seller = getattr(lot, "seller", None)
        nick = escape(str(getattr(seller, "username", "?") if seller else "?"))
        reviews = int(getattr(seller, "reviews", 0) or 0) if seller else 0
        online = "🟢" if seller and getattr(seller, "online", False) else "⚪"
        desc = escape((getattr(lot, "description", "") or "")[:80])
        lines.append(f"{online} <code>{price:.2f}</code> · {reviews} отз. · {nick}\n   <i>{desc}</i>")
    try:
        lines.append(margin_report(query, rec, 1))
    except Exception as ex:
        logger.debug("[Market] margin_report: %s", ex)
    lines.append("")
    lines.append("Напиши себестоимость числом — пересчитаю маржу с учётом панелей. /menu — на главную.")
    return "\n".join(lines)


def analyze(cardinal, subcategory_id: int, lot_type: str, our_cost: float, undercut: float) -> str:
    sc_type = SubCategoryTypes.COMMON if lot_type != "currency" else SubCategoryTypes.CURRENCY
    lots = cardinal.account.get_subcategory_public_lots(sc_type, subcategory_id)
    prices = []
    for lot in lots or []:
        p = getattr(lot, "price", None)
        if p is None:
            continue
        try:
            prices.append(float(p))
        except (TypeError, ValueError):
            continue
    if not prices:
        return "На витрине нет цен (проверь ID категории)."
    prices.sort()
    n = len(prices)
    mn, mx = prices[0], prices[-1]
    avg = sum(prices) / n
    med = statistics.median(prices)
    rec = max(mn, med - float(undercut or 0))
    if rec <= 0:
        rec = mn
    net = rec * (1.0 - commission())
    margin = net - float(our_cost or 0)
    warn = ""
    if our_cost and margin <= 0:
        warn = "\n⚠️ Маржа ≤ 0."
    text = (
        f"📈 <b>Витрина</b> /lots/{subcategory_id}/\n"
        f"Лотов с ценой: <b>{n}</b>\n"
        f"Мин <code>{mn:.2f}</code> · макс <code>{mx:.2f}</code>\n"
        f"Средняя <code>{avg:.2f}</code> · медиана <code>{med:.2f}</code>\n"
        f"💡 Ставь: <code>{rec:.2f}</code>\n"
        f"После комиссии: <code>{net:.2f}</code>\n"
        f"Себестоимость: <code>{our_cost:.2f}</code> · чистыми <b>{margin:.2f}</b>{warn}"
    )
    try:
        extra = margin_report(str(subcategory_id), rec, 1)
        if extra:
            text += extra
    except Exception:
        logger.debug("TRACEBACK", exc_info=True)
    return text


def init_post(cardinal):
    global _TG_CMDS
    tg = getattr(cardinal, "telegram", None)
    if not tg or not getattr(tg, "bot", None) or _TG_CMDS:
        return
    _TG_CMDS = True
    bot = tg.bot

    def _ok(uid: int) -> bool:
        return uid in getattr(tg, "authorized_users", {})

    @bot.message_handler(commands=["price", "цена", "оцен", "оценi"])
    def cmd_price(m: Message):
        if not _ok(m.from_user.id):
            return
        rest = (m.text or "").split(maxsplit=1)
        if len(rest) > 1:
            _WAIT[m.from_user.id] = {"mode": "desc"}
            _handle_desc(m, rest[1])
            return
        ask_price(bot, m.chat.id, m.from_user.id)

    @bot.message_handler(commands=["market", "prices", "витрина"])
    def cmd_market(m: Message):
        if not _ok(m.from_user.id):
            return
        cfg = load_cfg()
        sec = cfg["Market"] if cfg.has_section("Market") else {}
        parts = (m.text or "").split()
        sub_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else int(sec.get("subcategory_id", 0) or 0)
        cost = float(parts[2]) if len(parts) > 2 else float(sec.get("our_cost", 0) or 0)
        if not sub_id:
            bot.send_message(
                m.chat.id,
                "Проще нажать <b>📈 Цена</b> и описать товар словами.\n"
                "Или так: /market ID_категории себестоимость\nПример: <code>/market 209 120</code>",
                parse_mode="HTML",
            )
            return
        try:
            text = analyze(
                cardinal, sub_id, sec.get("lot_type", "common"),
                cost, float(sec.get("recommend_undercut", 0) or 0),
            )
        except Exception as ex:
            text = f"Не удалось снять витрину: {ex}"
        bot.send_message(m.chat.id, text, parse_mode="HTML")

    def _is_wait_text(m: Message) -> bool:
        if not m.from_user or m.from_user.id not in _WAIT:
            return False
        text = (m.text or "").strip()
        if not text or text.startswith("/"):
            return False
        try:
            from tg_bot.panel_ui import all_reply_labels
            if text in all_reply_labels():
                return False
        except Exception:
            logger.debug("TRACEBACK", exc_info=True)
        try:
            if tg.get_state(m.chat.id, m.from_user.id):
                return False
        except Exception:
            logger.debug("TRACEBACK", exc_info=True)
        return True

    @bot.message_handler(func=_is_wait_text)
    def cmd_wait(m: Message):
        if not _ok(m.from_user.id):
            return
        st = _WAIT.get(m.from_user.id) or {}
        mode = st.get("mode")
        if mode == "desc":
            _handle_desc(m, m.text)
        elif mode == "cost":
            raw = (m.text or "").replace(",", ".").strip()
            try:
                cost = float(raw)
            except ValueError:
                bot.send_message(m.chat.id, "Напиши число — себестоимость. Или /menu чтобы выйти.")
                return
            sc = st.get("sub")
            query = st.get("query") or ""
            try:
                text = analyze_query(cardinal, sc, query, cost, 0)
            except Exception as ex:
                text = f"Не удалось посчитать: {ex}"
            bot.send_message(m.chat.id, text, parse_mode="HTML", disable_web_page_preview=True)
            clear_wait(m.from_user.id)
        else:
            clear_wait(m.from_user.id)

    def _handle_desc(m: Message, query: str) -> None:
        cats = find_categories(cardinal, query)
        if not cats:
            bot.send_message(
                m.chat.id,
                "Не нашёл такую категорию на FunPay.\n"
                "Напиши игру и тип, например: <code>Steam аренда</code> или <code>CS2 аккаунт</code>.",
                parse_mode="HTML",
            )
            _WAIT[m.from_user.id] = {"mode": "desc"}
            return
        _WAIT[m.from_user.id] = {"mode": "pick", "query": query, "cats": {str(c.id): c for c in cats}}
        kb = K()
        for sc in cats:
            label = (getattr(sc, "fullname", None) or sc.name)[:64]
            kb.add(B(label, callback_data=f"MKT:c:{sc.id}"))
        kb.add(B("❌ Отмена", callback_data="MKT:x"))
        bot.send_message(
            m.chat.id,
            f"Нашёл категории под «{escape(query)}». Нажми свою:",
            reply_markup=kb,
        )

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("MKT:"))
    def cb_mkt(c: CallbackQuery):
        if not _ok(c.from_user.id):
            return
        parts = (c.data or "").split(":")
        if len(parts) < 2 or parts[1] == "x":
            clear_wait(c.from_user.id)
            try:
                bot.answer_callback_query(c.id, "Ок")
            except Exception:
                logger.debug("TRACEBACK", exc_info=True)
            return
        if parts[1] != "c" or len(parts) < 3:
            return
        st = _WAIT.get(c.from_user.id) or {}
        cats = st.get("cats") or {}
        sc = cats.get(parts[2])
        if sc is None:
            acc = cardinal.account
            sc = acc.get_subcategory(SubCategoryTypes.COMMON, int(parts[2]))
        if sc is None:
            bot.answer_callback_query(c.id, "Категория пропала, напиши заново.", show_alert=True)
            return
        query = st.get("query") or ""
        try:
            bot.answer_callback_query(c.id, "Смотрю витрину…")
        except Exception:
            logger.debug("TRACEBACK", exc_info=True)
        try:
            text = analyze_query(cardinal, sc, query, 0, 0)
        except Exception as ex:
            text = f"Не удалось снять витрину: {ex}"
        _WAIT[c.from_user.id] = {"mode": "cost", "sub": sc, "query": query}
        bot.send_message(c.message.chat.id, text, parse_mode="HTML", disable_web_page_preview=True)


def init_settings(cardinal):
    def status():
        return "Нажми «📈 Цена» и опиши товар своими словами."

    SettingsPage(UUID, NAME, "Пишешь что продаёшь — бот ищет похожие лоты и говорит цену.") \
        .set_status(status) \
        .attach(cardinal)
    cardinal.add_telegram_commands(UUID, [
        ("price", "за сколько выставлять", True),
        ("market", "витрина по ID категории", True),
    ])


BIND_TO_PRE_INIT = [init_post, init_settings]
BIND_TO_POST_INIT = [init_post]
