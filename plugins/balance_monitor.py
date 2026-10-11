# -*- coding: utf-8 -*-
"""Кошелёк FunPay: баланс, удержание, заработок, прогноз, вывод на карту РФ / СБП."""
from __future__ import annotations

import html
import logging
import os
import re
import time
from datetime import datetime

from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, Message, CallbackQuery

from FunPayAPI.common.enums import Currency, Wallet
from shop_core.bus import is_frozen, notify
from shop_core.db import get_db
from shop_core.plugin_settings import SettingsPage
from shop_core.settings import (
    is_dry_run, is_panic, withdraw_fee_pct, withdraw_min_rub,
)

logger = logging.getLogger("FPC.BalanceMonitor")

NAME = "Кошелёк FunPay"
VERSION = "2.0.0"
DESCRIPTION = "Баланс, удержание, заработок, прогноз и вывод на карту РФ / СБП"
CREDITS = "nnanserShop"
UUID = "5b1c9e83-3a7d-4e20-9f1c-8b4e6d2a7f01"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}

_READY = False
_WAIT: dict[int, dict] = {}
_LAST_WD: dict[int, float] = {}

BANKS = [
    ("sber", "Сбербанк"),
    ("tink", "Тинькофф"),
    ("alfa", "Альфа-Банк"),
    ("vtb", "ВТБ"),
    ("gzb", "Газпромбанк"),
    ("rshb", "Россельхозбанк"),
    ("raif", "Райффайзен"),
    ("sovc", "Совкомбанк"),
    ("psb", "Промсвязьбанк"),
    ("otkr", "Открытие"),
    ("mts", "МТС Банк"),
    ("poch", "Почта Банк"),
    ("rosb", "Росбанк"),
    ("ozon", "Озон Банк"),
    ("yndx", "Яндекс Банк"),
]
_BANK = {k: n for k, n in BANKS}


def clear_wait(uid: int) -> None:
    _WAIT.pop(int(uid), None)


def _owner_id() -> int:
    raw = os.getenv("TELEGRAM_OWNER_ID", "").strip()
    return int(raw) if raw.isdigit() else 0


def _ok(cardinal, uid: int) -> bool:
    tg = getattr(cardinal, "telegram", None)
    return bool(tg) and uid in getattr(tg, "authorized_users", {})


def _is_owner(uid: int) -> bool:
    return int(uid) == _owner_id()


def luhn_ok(num: str) -> bool:
    tot, alt = 0, False
    for ch in num[::-1]:
        n = ord(ch) - 48
        if n < 0 or n > 9:
            return False
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        tot += n
        alt = not alt
    return tot % 10 == 0


def mask_dest(raw: str, way: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    if way == "sbp":
        if len(d) >= 11:
            return f"+{d[0]}•••{d[-4:]}"
        return "телефон ••••"
    if len(d) >= 10:
        return f"{d[:4]} •• •• {d[-4:]}"
    return "карта ••••"


def is_mir(num: str) -> bool:
    return num.startswith(("2200", "2201", "2202", "2203", "2204"))


def parse_phone(text: str) -> str | None:
    d = re.sub(r"\D", "", text or "")
    if d.startswith("8") and len(d) == 11:
        d = "7" + d[1:]
    if len(d) == 10 and d.startswith("9"):
        d = "7" + d
    if len(d) == 11 and d.startswith("7"):
        return d
    return None


def parse_card(text: str) -> tuple[str | None, str]:
    d = re.sub(r"\D", "", text or "")
    if not (16 <= len(d) <= 19):
        return None, "Карта РФ — 16–19 цифр, без пробелов или с ними."
    if not luhn_ok(d):
        return None, "Номер не проходит проверку. Перепиши цифры."
    if d.startswith(("34", "37")):
        return None, "Только карта, выпущенная в РФ (МИР / Visa / Mastercard РФ)."
    if not (is_mir(d) or d[0] in "45"):
        return None, "Только РФ: МИР, Visa или Mastercard российского банка."
    return d, ""


def parse_amount(text: str) -> float | None:
    raw = (text or "").lower().replace("\xa0", " ").replace("₽", "").replace("руб", "").replace("р.", "")
    raw = raw.replace(" ", "").replace(",", ".")
    m = re.search(r"(\d+(?:\.\d{1,2})?)", raw)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    return v if v > 0 else None


def fee_of(amount: float) -> float:
    return round(float(amount) * withdraw_fee_pct(), 2)


def net_of(amount: float) -> float:
    return round(float(amount) - fee_of(amount), 2)


def _sums(since: float) -> tuple[float, float, int]:
    with get_db() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(sale_price),0), COALESCE(SUM(profit),0), COUNT(*)
               FROM finance_log WHERE created_at > ? AND dry_run = 0""",
            (since,),
        ).fetchone()
    return float(row[0] or 0), float(row[1] or 0), int(row[2] or 0)


def earnings_pack() -> dict:
    now = datetime.now()
    start_today = datetime(now.year, now.month, now.day).timestamp()
    start_week = start_today - 6 * 86400
    t_sale, t_profit, t_n = _sums(start_today)
    w_sale, w_profit, w_n = _sums(start_week)
    hours_gone = max(1.0, (time.time() - start_today) / 3600.0)
    pace = t_sale / hours_gone
    forecast_today = pace * 24.0
    avg_day = w_sale / 7.0
    forecast_week = avg_day * 7.0
    if w_n == 0 and t_n == 0:
        forecast_today = 0.0
        forecast_week = 0.0
    return {
        "t_sale": t_sale, "t_profit": t_profit, "t_n": t_n,
        "w_sale": w_sale, "w_profit": w_profit, "w_n": w_n,
        "forecast_today": forecast_today, "forecast_week": forecast_week,
    }


def wallet_kb() -> K:
    kb = K()
    kb.row(B("💸 Вывод", callback_data="WAL:out"), B("🔄 Обновить", callback_data="WAL:ref"))
    kb.row(B("🚚 Как продавать", callback_data="METH:hub"), B("🏠 Главная", callback_data="PANEL:home"))
    return kb


def get_balance_text(cardinal) -> str:
    bal = getattr(cardinal, "balance", None)
    total = float(getattr(bal, "total_rub", 0) or 0) if bal else 0.0
    avail = float(getattr(bal, "available_rub", 0) or 0) if bal else 0.0
    held = max(0.0, total - avail)
    usd = float(getattr(bal, "total_usd", 0) or 0) if bal else 0.0
    eur = float(getattr(bal, "total_eur", 0) or 0) if bal else 0.0
    e = earnings_pack()
    acc = getattr(cardinal, "account", None)
    sales = getattr(acc, "active_sales", 0) if acc else 0
    fee = withdraw_fee_pct() * 100
    mn = withdraw_min_rub()
    freeze = "заморожена" if is_frozen() else "живая"
    panic = "стоп" if is_panic() else "ок"
    lines = [
        "💰 <b>Кошелёк FunPay</b>",
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
        f"На счёте          <code>{total:.2f}</code> ₽",
        f"Можно вывести     <code>{avail:.2f}</code> ₽",
        f"Удержано          <code>{held:.2f}</code> ₽",
        f"$ <code>{usd:.2f}</code>  ·  € <code>{eur:.2f}</code>",
        f"Открытых сделок: <b>{sales}</b>  ·  сессия {freeze}  ·  {panic}",
        "",
        "📈 <b>Заработано</b>",
        f"Сегодня   оборот <code>{e['t_sale']:.2f}</code> ₽ · чистыми <code>{e['t_profit']:.2f}</code> · {e['t_n']} шт.",
        f"Неделя    оборот <code>{e['w_sale']:.2f}</code> ₽ · чистыми <code>{e['w_profit']:.2f}</code> · {e['w_n']} шт.",
        "",
        "🔮 <b>Прогноз</b> (по темпу журнала)",
        f"До конца дня ≈ <code>{e['forecast_today']:.2f}</code> ₽",
        f"За 7 дней ≈ <code>{e['forecast_week']:.2f}</code> ₽",
        "",
        f"Вывод: только карта/СБП <b>РФ</b>. Комиссия FunPay ≈ <b>{fee:.1f}%</b>, минимум <code>{mn:.0f}</code> ₽.",
        "Удержание — деньги в незакрытых заказах, их вывести нельзя.",
    ]
    if e["w_n"] == 0:
        lines.append("Журнал продаж пока пустой — прогноз нулевой, пока не пойдёт товар.")
    return "\n".join(lines)


def send_wallet(bot, chat_id: int, cardinal) -> None:
    bot.send_message(chat_id, get_balance_text(cardinal), reply_markup=wallet_kb(), parse_mode="HTML")


def _dest_prompt(way: str, bank: str) -> str:
    if way == "sbp":
        name = _BANK.get(bank, bank)
        return (
            f"🏦 Банк: <b>{html.escape(name)}</b>\n"
            f"Пришли номер телефона СБП в формате <code>+7XXXXXXXXXX</code>.\n"
            f"Только РФ."
        )
    return (
        "💳 <b>Только карта РФ</b> (МИР / Visa / Mastercard российского банка).\n"
        "Пришли номер карты одним сообщением. В лог уйдут только последние 4 цифры."
    )


def _summary(st: dict) -> str:
    way = st.get("way")
    amount = float(st.get("amount") or 0)
    fee = fee_of(amount)
    net = net_of(amount)
    dest = mask_dest(st.get("dest") or "", way)
    bank = _BANK.get(st.get("bank") or "", "—")
    how = "СБП" if way == "sbp" else "карта РФ"
    extra = f"\nБанк: <b>{html.escape(bank)}</b>" if way == "sbp" else ""
    return (
        "🧾 <b>Проверь вывод</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"Способ: <b>{how}</b>{extra}\n"
        f"Куда: <code>{html.escape(dest)}</code>\n"
        f"Списать с FunPay: <code>{amount:.2f}</code> ₽\n"
        f"Комиссия ≈ {withdraw_fee_pct()*100:.1f}%: <code>{fee:.2f}</code> ₽\n"
        f"На руки примерно: <b>{net:.2f} ₽</b>\n\n"
        "Без кнопки «Подтвердить» ничего не уйдёт."
    )


def confirm_kb() -> K:
    kb = K()
    kb.row(
        B("✅ Подтвердить", callback_data="WAL:go"),
        B("❌ Отмена", callback_data="WAL:x"),
    )
    return kb


def _do_withdraw(cardinal, st: dict) -> tuple[bool, str]:
    amount = float(st.get("amount") or 0)
    dest = (st.get("dest") or "").strip()
    way = st.get("way")
    if way == "sbp":
        wallet = Wallet.YOUMONEY
        address = dest if dest.startswith("7") else dest
        if address.startswith("7") and len(address) == 11:
            address = "+" + address
    else:
        wallet = Wallet.CARD_RUB
        address = dest
    acc = getattr(cardinal, "account", None)
    if acc is None:
        return False, "Нет сессии FunPay."
    send_amt: int | float = int(amount) if float(amount).is_integer() else round(float(amount), 2)
    if is_dry_run():
        return True, f"🧪 Учебный режим: вывод {send_amt} ₽ не отправлялся."
    try:
        got = acc.withdraw(Currency.RUB, wallet, send_amt, address)
        return True, f"FunPay принял заявку. На сторону уйдёт ≈ <code>{got:.2f}</code>."
    except Exception as ex:
        return False, html.escape(str(ex)[:400])


HOLD_HIST_KEY = "hold_hist"
HOLD_ALERT_KEY = "hold_alert_at"
HOLD_WINDOW = 48 * 3600
HOLD_EVERY = 6 * 3600
_HOLD_LOOP = False


def note_hold(held: float, now: float | None = None) -> list[list[float]]:
    import json
    from shop_core.bus import get_flag, set_flag
    now = float(now if now is not None else time.time())
    try:
        hist = json.loads(get_flag(HOLD_HIST_KEY, "[]") or "[]")
    except Exception:
        hist = []
    hist = [h for h in hist if isinstance(h, list) and len(h) == 2 and now - float(h[0]) <= HOLD_WINDOW + 86400]
    hist.append([now, round(float(held), 2)])
    set_flag(HOLD_HIST_KEY, json.dumps(hist))
    return hist


def hold_stuck(hist: list[list[float]], now: float) -> float:
    """Сумма, которая лежит в удержании все 48 ч и ни разу не уменьшилась. 0 — всё движется."""
    window = [h for h in hist if now - float(h[0]) <= HOLD_WINDOW + 3600]
    if len(window) < 2 or now - float(window[0][0]) < HOLD_WINDOW - 3600:
        return 0.0
    first = float(window[0][1])
    low = min(float(h[1]) for h in window)
    if first <= 0 or low < first * 0.99:
        return 0.0
    return first


def _hold_loop(cardinal) -> None:
    from shop_core.bus import get_flag, set_flag
    while True:
        time.sleep(HOLD_EVERY)
        try:
            if is_frozen() or is_panic():
                continue
            bal = cardinal.get_balance(attempts=2)
            if not bal or not float(getattr(bal, "total_rub", 0) or 0):
                continue
            cardinal.balance = bal
            held = max(0.0, float(bal.total_rub or 0) - float(bal.available_rub or 0))
            now = time.time()
            stuck = hold_stuck(note_hold(held, now), now)
            last = float(get_flag(HOLD_ALERT_KEY, "0") or 0)
            if stuck and now - last > 86400:
                set_flag(HOLD_ALERT_KEY, str(now))
                notify(
                    cardinal,
                    f"⏳ Удержание не уменьшается 48 ч: <code>{stuck:.2f}</code> ₽ (сейчас <code>{held:.2f}</code>).\n"
                    f"Проверь незакрытые заказы — покупатели не подтверждают или идёт спор.",
                    True,
                )
        except Exception as ex:
            logger.debug("[Wallet] hold: %s", ex)


def init_settings(cardinal):
    SettingsPage(UUID, NAME, "Кошелёк: баланс, удержание, прогноз, вывод РФ.") \
        .set_status(lambda: get_balance_text(cardinal)[:1500]) \
        .attach(cardinal)
    cardinal.add_telegram_commands(UUID, [
        ("balances", "кошелёк FunPay", True),
        ("withdraw", "вывод на карту РФ / СБП", True),
    ])


def init_post(cardinal):
    global _READY, _HOLD_LOOP
    init_settings(cardinal)
    if not _HOLD_LOOP:
        _HOLD_LOOP = True
        import threading
        threading.Thread(target=_hold_loop, args=(cardinal,), daemon=True).start()
    tg = getattr(cardinal, "telegram", None)
    if not tg or not getattr(tg, "bot", None) or _READY:
        return
    _READY = True
    bot = tg.bot

    def guard(m) -> bool:
        return _ok(cardinal, m.from_user.id)

    @bot.message_handler(commands=["balances", "balance", "баланс", "балансы", "кошелёк", "кошелек"])
    def cmd_balances(m: Message):
        if not guard(m):
            return
        clear_wait(m.from_user.id)
        send_wallet(bot, m.chat.id, cardinal)

    @bot.message_handler(commands=["withdraw", "вывод"])
    def cmd_wd(m: Message):
        if not guard(m):
            return
        if not _is_owner(m.from_user.id):
            bot.send_message(m.chat.id, "Вывод может подтвердить только владелец.")
            return
        _start_out(m.chat.id, m.from_user.id)

    def _start_out(chat_id: int, uid: int) -> None:
        try:
            from tg_bot.panel_ui import clear_all_waits
            clear_all_waits(uid)
        except Exception:
            clear_wait(uid)
        kb = K()
        kb.row(
            B("🏦 СБП", callback_data="WAL:way:sbp"),
            B("💳 Карта РФ", callback_data="WAL:way:card"),
        )
        kb.row(B("❌ Отмена", callback_data="WAL:x"))
        bot.send_message(
            chat_id,
            "💸 <b>Вывод с FunPay</b>\n"
            "Только <b>РФ</b>: СБП на телефон или карта российского банка.\n"
            "Выбери способ:",
            reply_markup=kb,
            parse_mode="HTML",
        )

    def _is_wal_text(m: Message) -> bool:
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
            pass
        try:
            if tg.get_state(m.chat.id, m.from_user.id):
                return False
        except Exception:
            pass
        return True

    @bot.message_handler(func=_is_wal_text)
    def cmd_wal_wait(m: Message):
        if not guard(m):
            return
        st = _WAIT.get(m.from_user.id) or {}
        mode = st.get("mode")
        if mode == "dest":
            way = st.get("way")
            if way == "sbp":
                phone = parse_phone(m.text or "")
                if not phone:
                    bot.send_message(m.chat.id, "Нужен телефон РФ: <code>+79001234567</code>", parse_mode="HTML")
                    return
                st["dest"] = phone
            else:
                card, err = parse_card(m.text or "")
                if not card:
                    bot.send_message(m.chat.id, err)
                    return
                st["dest"] = card
            try:
                bot.delete_message(m.chat.id, m.id)
            except Exception:
                pass
            st["mode"] = "sum"
            _WAIT[m.from_user.id] = st
            mn = withdraw_min_rub()
            bot.send_message(
                m.chat.id,
                f"Сумма с баланса FunPay. Минимум <code>{mn:.0f}</code> ₽.\n"
                f"Пример: <code>1000</code>",
                parse_mode="HTML",
            )
            return
        if mode == "sum":
            amount = parse_amount(m.text or "")
            mn = withdraw_min_rub()
            if amount is None:
                bot.send_message(m.chat.id, "Напиши число, например <code>1000</code>", parse_mode="HTML")
                return
            if amount < mn:
                bot.send_message(m.chat.id, f"Минимум вывода FunPay: <code>{mn:.0f}</code> ₽.", parse_mode="HTML")
                return
            bal = getattr(cardinal, "balance", None)
            avail = float(getattr(bal, "available_rub", 0) or 0) if bal else 0.0
            if amount > avail + 0.01:
                bot.send_message(
                    m.chat.id,
                    f"Доступно к выводу только <code>{avail:.2f}</code> ₽ (остальное удержано в сделках).",
                    parse_mode="HTML",
                )
                return
            st["amount"] = amount
            st["mode"] = "confirm"
            _WAIT[m.from_user.id] = st
            bot.send_message(m.chat.id, _summary(st), reply_markup=confirm_kb(), parse_mode="HTML")
            return
        clear_wait(m.from_user.id)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("WAL:"))
    def cb_wal(c: CallbackQuery):
        if not _ok(cardinal, c.from_user.id):
            return
        parts = (c.data or "").split(":")
        action = parts[1] if len(parts) > 1 else ""
        try:
            bot.answer_callback_query(c.id)
        except Exception:
            pass
        if action == "x":
            clear_wait(c.from_user.id)
            bot.send_message(c.message.chat.id, "Вывод отменён.")
            return
        if action == "ref":
            try:
                b = cardinal.get_balance(attempts=2)
                cardinal.balance = b
            except Exception as ex:
                logger.debug("[Wallet] refresh: %s", ex)
            send_wallet(bot, c.message.chat.id, cardinal)
            return
        if action == "out":
            if not _is_owner(c.from_user.id):
                bot.send_message(c.message.chat.id, "Вывод подтверждает только владелец.")
                return
            _start_out(c.message.chat.id, c.from_user.id)
            return
        if action == "way" and len(parts) > 2:
            if not _is_owner(c.from_user.id):
                return
            way = parts[2]
            if way not in ("sbp", "card"):
                return
            _WAIT[c.from_user.id] = {"way": way, "mode": "bank" if way == "sbp" else "dest"}
            if way == "card":
                _WAIT[c.from_user.id]["mode"] = "dest"
                bot.send_message(c.message.chat.id, _dest_prompt("card", ""), parse_mode="HTML")
                return
            kb = K()
            row = []
            for key, name in BANKS:
                row.append(B(name, callback_data=f"WAL:bank:{key}"))
                if len(row) == 2:
                    kb.row(*row)
                    row = []
            if row:
                kb.row(*row)
            kb.row(B("❌ Отмена", callback_data="WAL:x"))
            bot.send_message(
                c.message.chat.id,
                "🏦 СБП — выбери банк получателя (РФ):",
                reply_markup=kb,
            )
            return
        if action == "bank" and len(parts) > 2:
            if not _is_owner(c.from_user.id):
                return
            key = parts[2]
            if key not in _BANK:
                return
            st = _WAIT.get(c.from_user.id) or {"way": "sbp"}
            st["way"] = "sbp"
            st["bank"] = key
            st["mode"] = "dest"
            _WAIT[c.from_user.id] = st
            bot.send_message(c.message.chat.id, _dest_prompt("sbp", key), parse_mode="HTML")
            return
        if action == "go":
            if not _is_owner(c.from_user.id):
                bot.send_message(c.message.chat.id, "Подтвердить вывод может только владелец.")
                return
            st = _WAIT.get(c.from_user.id) or {}
            if st.get("mode") != "confirm" or not st.get("dest") or not st.get("amount"):
                bot.send_message(c.message.chat.id, "Сначала пройди шаги вывода заново.")
                clear_wait(c.from_user.id)
                return
            now = time.time()
            if now - _LAST_WD.get(c.from_user.id, 0) < 120:
                bot.send_message(c.message.chat.id, "Подожди пару минут между выводами.")
                return
            if is_panic() or is_frozen():
                bot.send_message(c.message.chat.id, "Сейчас стоп или заморозка сессии — вывод не отправляю.")
                return
            ok, msg = _do_withdraw(cardinal, st)
            mask = mask_dest(st.get("dest") or "", st.get("way") or "card")
            with get_db() as conn:
                conn.execute(
                    """INSERT INTO withdraw_log
                       (amount, fee_est, got, way, bank, dest_mask, ok, error, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        float(st.get("amount") or 0),
                        fee_of(float(st.get("amount") or 0)),
                        0.0,
                        st.get("way") or "",
                        st.get("bank") or "",
                        mask,
                        1 if ok else 0,
                        "" if ok else msg[:300],
                        time.time(),
                    ),
                )
            clear_wait(c.from_user.id)
            if ok:
                _LAST_WD[c.from_user.id] = now
                bot.send_message(c.message.chat.id, "✅ " + msg, parse_mode="HTML")
                notify(cardinal, f"💸 Вывод {st.get('amount'):.0f} ₽ ({st.get('way')}) → {mask}\n{msg}", True)
            else:
                bot.send_message(c.message.chat.id, "❌ FunPay не принял вывод.\n" + msg, parse_mode="HTML")


BIND_TO_PRE_INIT = [init_post]
BIND_TO_POST_INIT = [init_post]
