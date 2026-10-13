# -*- coding: utf-8 -*-
"""Схемы продажи: Steam, Robux, оффлайн-ключи, SMM — профит, сложность, выбор."""
from __future__ import annotations

import configparser
import html
import logging
import os
import time
from dataclasses import dataclass

from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, CallbackQuery, Message

from shop_core.panels import (
    candidates_from_suppliers, load_suppliers_cfg, min_sale_for_cost, pick_cheapest,
)
from shop_core.plugin_settings import SettingsPage
from shop_core.settings import min_margin_mult

logger = logging.getLogger("FPC.TradeMethods")

NAME = "Как продавать"
VERSION = "1.0.0"
DESCRIPTION = "Варианты Steam / Robux / SMM / оффлайн: профит, сложность, звезда на лучшем"
CREDITS = "nnanserShop"
UUID = "c9d24e71-6a3b-4c18-8f05-1b7e9a2d4456"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}
CFG = os.path.join("configs", "methods.cfg")
_READY = False
_WAIT: dict[int, dict] = {}
WAIT_TTL = 600


@dataclass
class Method:
    key: str
    title: str
    how: str
    difficulty: int
    profit: float | None
    ready: bool
    blocked: bool = False
    reason: str = ""


def clear_wait(uid: int) -> None:
    _WAIT.pop(int(uid), None)


def _ok(cardinal, uid: int) -> bool:
    tg = getattr(cardinal, "telegram", None)
    return bool(tg) and uid in getattr(tg, "authorized_users", {})


def load_pref() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if os.path.exists(CFG):
        cfg.read(CFG, encoding="utf-8")
    if not cfg.has_section("Pick"):
        cfg["Pick"] = {}
    return cfg


def save_pref(kind: str, key: str) -> None:
    cfg = load_pref()
    cfg.set("Pick", kind, key)
    os.makedirs("configs", exist_ok=True)
    from shop_core.fileio import write_config
    write_config(CFG, cfg)


def _panel_profit(query: str, sale_hint: float = 500.0) -> tuple[float | None, str, bool]:
    cands = candidates_from_suppliers(query)
    if not cands:
        return None, "Панель без ключа. Нажми «🔌 Панель» и вставь URL + ключ.", False
    best, why = pick_cheapest(cands, sale_hint, 1, fetch_live=False)
    if not best:
        return None, why, True
    mult = float(best.get("_mult") or 0)
    name = best.get("name") or "панель"
    return mult, f"{name}: x{mult:.2f} при цене лота {sale_hint:.0f} ₽. {why.splitlines()[0]}", True


def _file_ready() -> bool:
    folder = os.path.join("storage", "products")
    if not os.path.isdir(folder):
        return False
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return True
    return False


def _diff(n: int) -> str:
    n = max(1, min(5, int(n)))
    return "●" * n + "○" * (5 - n)


def steam_methods() -> list[Method]:
    mult, note, ready = _panel_profit("steam wallet пополнение")
    file_ok = _file_ready()
    return [
        Method(
            "panel",
            "API-панель (коды / пополнение)",
            "Твой лот на FunPay → бот закупает у панели из «🔌 Панель» → отдаёт логин/пин покупателю. "
            "Steam Store из РФ не трогаем (санкции). " + note,
            2, mult, ready,
        ),
        Method(
            "file",
            "Ключи в файле автовыдачи",
            "Кладёшь коды в storage/products и привязываешь лот в Автовыдаче. "
            "Бот не закупает сам — ты пополняешь файл. Запас x2 считаешь руками.",
            3, None, file_ok, reason="" if file_ok else "Файл товара пустой.",
        ),
        Method(
            "store",
            "Оплата в Steam Store картой",
            "Из РФ магазин Steam часто не принимает оплату. Этого варианта в боте нет и не будет.",
            5, None, False, True, "Санкции / отказ магазина. Не используем.",
        ),
    ]


def robux_methods() -> list[Method]:
    mult, note, ready = _panel_profit("робукс robux gamepass")
    file_ok = _file_ready()
    return [
        Method(
            "gamepass",
            "Game Pass через панель",
            "Покупатель даёт ник Roblox → панель покупает Game Pass / робуксы. " + note,
            2, mult, ready,
        ),
        Method(
            "file",
            "Коды в файле автовыдачи",
            "Готовые коды в storage/products + автовыдача. Панель не нужна, но запас сам не купится.",
            3, None, file_ok, reason="" if file_ok else "Нет ключей в файле.",
        ),
        Method(
            "acc",
            "Чужие аккаунты Roblox",
            "Покупка/продажа чужих аккаунтов — вне правил. Варианта в боте нет.",
            5, None, False, True, "Не делаем.",
        ),
    ]


def stars_methods() -> list[Method]:
    mult, note, ready = _panel_profit("telegram stars звезды")
    return [
        Method(
            "panel",
            "API-панель Stars",
            "Лот FunPay → бот спрашивает @username → «да» → закупка у твоей панели. "
            "Fragment-cookie не нужны. " + note,
            2, mult, ready,
        ),
        Method(
            "off",
            "Выдача вручную",
            "Плагин выкл: сам кидаешь звёзды. Ночью продажи стоят.",
            4, None, True,
        ),
    ]


def gift_methods() -> list[Method]:
    mult, note, ready = _panel_profit("telegram gift подарок")
    return [
        Method(
            "panel",
            "API-панель подарков",
            "Как в ролике: сверка @username, потом заказ на панель. " + note,
            2, mult, ready,
        ),
        Method(
            "off",
            "Отправка с телефона",
            "Бот только принимает ник, подарок шлёшь сам из Telegram.",
            3, None, True,
        ),
    ]


def smm_methods() -> list[Method]:
    mult, note, ready = _panel_profit("накрут подписчик smm")
    cfg = load_suppliers_cfg()
    n = sum(1 for s in cfg.sections() if "smm" in s.lower() and (cfg[s].get("api_key") or "").strip())
    return [
        Method(
            "panel",
            "SMM-панель action=add",
            "Лот с ссылкой → бот шлёт заказ на панель. Берёт самую дешёвую из твоих, если запас x2 есть. " + note,
            2, mult, ready,
        ),
        Method(
            "two",
            "Две панели (основная + запас)",
            f"В suppliers.cfg секции smm и smm_2. Сейчас с ключом: {n}. Бот сам возьмёт дешевле.",
            3, mult if n >= 2 else None, n >= 2,
            reason="" if n >= 2 else "Вторая панель без ключа — добавь запасной URL.",
        ),
        Method(
            "hand",
            "Вручную из пульта",
            "АвтоSMM выключен, ты сам накручиваешь. Профит любой, но ночью не спишь.",
            4, None, True,
        ),
    ]


def offline_methods() -> list[Method]:
    file_ok = _file_ready()
    return [
        Method(
            "file",
            "Оффлайн-ключ из файла",
            "Windows / Office / игра — ключ в storage/products, лот на автовыдаче. "
            "После оплаты FunPay сразу шлёт ключ. Закупка панели не нужна.",
            1, None, file_ok, reason="" if file_ok else "Положи ключи в файл товара.",
        ),
        Method(
            "manual",
            "Ручная выдача из Telegram",
            "Заказ приходит в пульт, ты жмёшь и отправляешь ключ. Надёжно, но не 24/7.",
            2, None, True,
        ),
        Method(
            "crack",
            "Пиратские активаторы",
            "В боте этого нет.",
            5, None, False, True, "Не делаем.",
        ),
    ]


KINDS = {
    "steam": ("Steam — пополнение", steam_methods),
    "robux": ("Robux", robux_methods),
    "smm": ("SMM-накрутка", smm_methods),
    "stars": ("Telegram Stars", stars_methods),
    "gift": ("Подарки Telegram", gift_methods),
    "off": ("Оффлайн-активация", offline_methods),
}


def _best_key(items: list[Method]) -> str | None:
    ready = [m for m in items if m.ready and not m.blocked]
    if not ready:
        return None
    with_p = [m for m in ready if m.profit and m.profit > 0]
    if with_p:
        return max(with_p, key=lambda m: m.profit).key
    return min(ready, key=lambda m: m.difficulty).key


def render_kind(kind: str) -> tuple[str, K]:
    title, fn = KINDS[kind]
    items = fn()
    star = _best_key(items)
    pref = load_pref().get("Pick", kind, fallback="")
    need = min_margin_mult()
    lines = [
        f"🚚 <b>{html.escape(title)}</b>",
        f"Чтобы уйти в плюс, запас минимум <b>x{need:.1f}</b> после комиссии FunPay.",
        "★ — самый профитный из тех, что уже готовы.",
        "Сложность: ●○○○○ легко → ●●●●● тяжело.",
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
    ]
    kb = K()
    for m in items:
        mark = ""
        if m.blocked:
            mark = "🚫 "
        elif m.key == star:
            mark = "★ "
        elif not m.ready:
            mark = "○ "
        else:
            mark = "• "
        sel = " ← выбран" if pref == m.key else ""
        profit = f"профит x{m.profit:.2f}" if m.profit else "профит: посчитаем после ключа"
        if m.blocked:
            profit = "недоступно"
        lines.append(
            f"{mark}<b>{html.escape(m.title)}</b>{sel}\n"
            f"   {profit}  ·  сложность {_diff(m.difficulty)}\n"
            f"   <i>{html.escape(m.how[:280])}</i>"
        )
        if m.reason:
            lines.append(f"   ⚠️ {html.escape(m.reason)}")
        if not m.blocked:
            kb.add(B(f"{'★ ' if m.key == star else ''}{m.title}"[:64], callback_data=f"METH:set:{kind}:{m.key}"))
            if (kind, m.key) in (("steam", "panel"), ("steam", "file"), ("robux", "gamepass"), ("robux", "file")):
                kb.add(B("▶ Шаги: куда заходить", callback_data=f"METH:go:{kind}:{m.key}"))
    kb.row(B("🔌 Панель", callback_data="SHOP:wiz"), B("◀️ К схемам", callback_data="METH:hub"))
    return "\n\n".join(lines), kb


def hub_text() -> str:
    bits = []
    for kind, (title, fn) in KINDS.items():
        items = fn()
        star = _best_key(items)
        star_title = next((m.title for m in items if m.key == star), "пока не готов")
        ready_n = sum(1 for m in items if m.ready and not m.blocked)
        bits.append(f"• <b>{html.escape(title)}</b> — готовых схем {ready_n}\n   ★ {html.escape(star_title)}")
    return (
        "🚚 <b>Как продавать, чтобы быть в плюсе</b>\n"
        "Открой товар — бот разложит варианты, пометит ★ самый профитный "
        "и покажет сложность. Сайты и чужие ТГ-боты сам не ищет: только твои панели и файлы.\n\n"
        + "\n".join(bits)
    )


def hub_kb() -> K:
    kb = K()
    kb.row(B("🎮 Steam", callback_data="METH:k:steam"), B("💎 Robux", callback_data="METH:k:robux"))
    kb.row(B("⭐ Stars", callback_data="METH:k:stars"), B("🎁 Подарки", callback_data="METH:k:gift"))
    kb.row(B("📣 SMM", callback_data="METH:k:smm"), B("🔑 Оффлайн", callback_data="METH:k:off"))
    kb.row(B("🔌 Панель", callback_data="SHOP:wiz"), B("🏠 Главная", callback_data="PANEL:home"))
    return kb


def init_settings(cardinal):
    SettingsPage(UUID, NAME, "Схемы Steam / Robux / SMM / оффлайн. ★ = выгоднее.") \
        .set_status(lambda: hub_text()[:1500]) \
        .attach(cardinal)
    cardinal.add_telegram_commands(UUID, [("methods", "как продавать — схемы и профит", True)])


def init_pre(cardinal):
    global _READY, _BOT
    init_settings(cardinal)
    tg = getattr(cardinal, "telegram", None)
    if not tg or not getattr(tg, "bot", None) or _READY:
        return
    _READY = True
    bot = tg.bot
    _BOT = bot

    @bot.message_handler(commands=["methods", "схемы", "товары"])
    def cmd_m(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        bot.send_message(m.chat.id, hub_text(), reply_markup=hub_kb(), parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("METH:"))
    def cb_m(c: CallbackQuery):
        if not _ok(cardinal, c.from_user.id):
            return
        parts = (c.data or "").split(":")
        try:
            bot.answer_callback_query(c.id)
        except Exception:
            logger.debug("TRACEBACK", exc_info=True)
        if len(parts) < 2 or parts[1] == "hub":
            bot.send_message(c.message.chat.id, hub_text(), reply_markup=hub_kb(), parse_mode="HTML")
            return
        if parts[1] == "k" and len(parts) > 2 and parts[2] in KINDS:
            text, kb = render_kind(parts[2])
            bot.send_message(c.message.chat.id, text, reply_markup=kb, parse_mode="HTML")
            return
        if parts[1] == "set" and len(parts) > 3 and parts[2] in KINDS:
            kind, key = parts[2], parts[3]
            items = {m.key: m for m in KINDS[kind][1]()}
            mth = items.get(key)
            if not mth or mth.blocked:
                bot.send_message(c.message.chat.id, "Этот вариант закрыт.")
                return
            save_pref(kind, key)
            hint = ""
            if key in ("panel", "gamepass", "two") and not mth.ready:
                hint = "\nДальше нажми «▶ Шаги: куда заходить» — проведу по кабинету панели и цене."
            elif key == "file" and not mth.ready:
                hint = "\nНажми «▶ Шаги: куда заходить» — покажу, куда положить файл. Автовыдачу сам не включу."
            bot.send_message(
                c.message.chat.id,
                f"✅ Выбрано: <b>{html.escape(mth.title)}</b>"
                f"{' ★ самый профитный' if key == _best_key(list(items.values())) else ''}"
                f"{hint}",
                parse_mode="HTML",
            )
            text, kb = render_kind(kind)
            bot.send_message(c.message.chat.id, text, reply_markup=kb, parse_mode="HTML")
            return
        if parts[1] == "go" and len(parts) > 3:
            _open_guide(c.message.chat.id, c.from_user.id, parts[2], parts[3])
            return
        if parts[1] == "w" and len(parts) > 2:
            _guide_action(c.message.chat.id, c.from_user.id, parts[2])

    def _is_guide_text(m: Message) -> bool:
        if not m.from_user or m.from_user.id not in _WAIT:
            return False
        if time.time() - float((_WAIT.get(m.from_user.id) or {}).get("at", 0)) > WAIT_TTL:
            _WAIT.pop(m.from_user.id, None)
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
        return True

    @bot.message_handler(func=_is_guide_text)
    def cmd_guide_text(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        from shop_core.setup_guide import apply_text, buttons, load
        ok, text, wipe = apply_text(m.from_user.id, m.text or "")
        if wipe:
            try:
                bot.delete_message(m.chat.id, m.id)
            except Exception:
                logger.debug("TRACEBACK", exc_info=True)
        run = load(m.from_user.id)
        _arm_wait(m.from_user.id, run)
        bot.send_message(
            m.chat.id, text,
            reply_markup=_guide_kb(buttons(run)) if run else None,
            parse_mode="HTML",
        )


def _guide_kb(pairs: list[tuple[str, str]]) -> K:
    kb = K()
    for label, action in pairs:
        kb.add(B(label[:64], callback_data=f"METH:w:{action}"[:64]))
    return kb


def _arm_wait(uid: int, run: dict | None) -> None:
    from shop_core.setup_guide import expects_text
    if expects_text(run):
        _WAIT[int(uid)] = {"at": time.time()}
    else:
        _WAIT.pop(int(uid), None)


_BOT = None


def _open_guide(chat_id: int, uid: int, kind: str, method: str) -> None:
    from shop_core.setup_guide import begin, buttons, screen
    try:
        from tg_bot.panel_ui import clear_all_waits
        clear_all_waits(uid)
    except Exception:
        logger.debug("TRACEBACK", exc_info=True)
    try:
        run = begin(uid, kind, method)
    except ValueError:
        _bot_for(chat_id, "Этот вариант мастер не ведёт.", None)
        return
    _arm_wait(uid, run)
    _bot_for(chat_id, screen(run), _guide_kb(buttons(run)))


def _bot_for(chat_id: int, text: str, kb) -> None:
    if _BOT is not None:
        _BOT.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")


def _guide_action(chat_id: int, uid: int, action: str) -> None:
    from shop_core.setup_guide import apply_action, buttons, load
    _ok_step, text = apply_action(uid, action)
    run = load(uid)
    _arm_wait(uid, run)
    pairs = [] if action == "stop" else buttons(run)
    _bot_for(chat_id, text, _guide_kb(pairs) if pairs else None)


BIND_TO_PRE_INIT = [init_pre]
