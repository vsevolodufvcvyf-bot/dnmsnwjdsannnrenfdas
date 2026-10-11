# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import re
import time
import json
import base64
import hmac
import hashlib
import struct
import urllib.request
import logging
from threading import Thread
from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B

from shop_core.bus import as_chat_id, bind_order_chat, bot_send, is_frozen, notify
from shop_core.db import get_db
from shop_core.finance import claim_delivery, claim_order, release_delivery
from shop_core.settings import is_dry_run, is_panic, ini_bool, flip_ini
from shop_core.plugin_settings import SettingsPage

logger = logging.getLogger("FPC.AutoRent")

NAME = "Steam AutoRent (MaFile Ultra Edition)"
VERSION = "2.0.0"
DESCRIPTION = "Автоаренда Steam с синхронизацией лотов FunPay, дедупликацией и 2FA"
CREDITS = "Cardinal Community"
UUID = "f72b9a41-3e5d-4f11-9c8a-7b3d2e1a5f99"
SETTINGS_PAGE = True

BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}
CBT_PREFIX = "MA_RENT"
CONFIG_FILE = "configs/autorent.cfg"

RENT_DELIVERY_TEMPLATE = """🎮 Ваши данные для аренды аккаунта ({lot_name}):
🔑 Логин: {login}
🔒 Пароль: {password}
🛡️ Текущий Steam Guard: {guard_code} (действует 30 сек)
⏱️ Срок аренды: {duration_str} (до {expire_str})

ℹ️ ВАЖНО:
1. Чтобы получить новый код Guard в любой момент, просто отправьте слово «код» прямо в этот диалог.
2. Не привязывайте свои телефоны и не используйте читы/софт!
3. Когда время выйдет — зайди в покупки и закрой сделку. Удачи."""

GUARD_TRIGGER_WORDS = ["код", "гвард", "guard", "2fa", "где код", "дай код", "код стим", "!code", "code"]


def render_rent_message(**fields) -> str:
    return re.sub(
        r"\{(\w+)\}",
        lambda m: str(fields[m.group(1)]) if m.group(1) in fields else m.group(0),
        RENT_DELIVERY_TEMPLATE,
    )

_STEAM_TIME_OFFSET = 0
_LAST_STEAM_TIME_SYNC = 0

def get_steam_time_offset() -> int:
    global _STEAM_TIME_OFFSET, _LAST_STEAM_TIME_SYNC
    now = time.time()
    if now - _LAST_STEAM_TIME_SYNC < 1800:
        return _STEAM_TIME_OFFSET
    try:
        req = urllib.request.Request('https://api.steampowered.com/ITwoFactorService/QueryTime/v0001/', data=b'', headers={'User-Agent': 'Valve/Steam'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            server_time = int(data['response']['server_time'])
            _STEAM_TIME_OFFSET = server_time - int(time.time())
            _LAST_STEAM_TIME_SYNC = now
    except Exception:
        pass
    return _STEAM_TIME_OFFSET

def generate_steam_guard_code(shared_secret: str, offset: int = 0) -> str:
    try:
        secret_bytes = base64.b64decode(shared_secret.strip())
        current_time = int(time.time()) + get_steam_time_offset() + offset
        time_buffer = struct.pack('>Q', current_time // 30)
        hmac_hash = hmac.new(secret_bytes, time_buffer, hashlib.sha1).digest()
        start = hmac_hash[19] & 0x0F
        full_code = struct.unpack('>I', hmac_hash[start:start+4])[0] & 0x7FFFFFFF
        chars = "23456789BCDFGHJKMNPQRTVWXY"
        code = ""
        for _ in range(5):
            code += chars[full_code % len(chars)]
            full_code //= len(chars)
        return code
    except Exception as e:
        return f"ERR:{e}"

def format_duration_readable(seconds: int) -> str:
    if seconds >= 604800:
        weeks = seconds // 604800
        return f"{weeks} нед." if weeks > 1 else "1 неделя"
    if seconds >= 86400:
        days = seconds // 86400
        return f"{days} дн." if days > 1 else "1 день (24ч)"
    hours = seconds // 3600
    rem_mins = (seconds % 3600) // 60
    return f"{hours} ч. {rem_mins} мин." if rem_mins > 0 else f"{hours} ч."

def parse_duration_from_order(order_desc: str, order_amount: int = 1) -> int:
    text = (order_desc or "").lower()
    amount = max(1, int(order_amount or 1))
    base_sec = None

    tag_m = re.search(r'\[(?:rent|аренда|срок):\s*(\d+)\s*(h|ч|hour|d|д|day|w|нед)\]', text)
    if tag_m:
        val, u = int(tag_m.group(1)), tag_m.group(2)
        if u in ['h', 'ч', 'hour']: base_sec = val * 3600
        elif u in ['d', 'д', 'day']: base_sec = val * 86400
        elif u in ['w', 'нед']: base_sec = val * 604800

    if not base_sec:
        h_m = re.search(r'(\d+)\s*(?:час\w*|ч\b|h\b|hours?\b)', text)
        if h_m: base_sec = int(h_m.group(1)) * 3600

    if not base_sec:
        d_m = re.search(r'(\d+)\s*(?:день|дня|дней|дн\b|сут\w*|days?\b)', text)
        if d_m: base_sec = int(d_m.group(1)) * 86400

    if not base_sec:
        w_m = re.search(r'(\d+)\s*(?:недел\w*|нед\b|weeks?\b)', text)
        if w_m: base_sec = int(w_m.group(1)) * 604800

    if not base_sec:
        if re.search(r'\bсутк\w*', text):
            base_sec = 86400
        elif re.search(r'\bнедел[яюи]\b|\bweek\b', text):
            base_sec = 604800

    if not base_sec:
        base_sec = 2 * 3600

    return base_sec * amount

def sync_lots_visibility(cardinal):
    try:
        if not hasattr(cardinal, "profile") or not cardinal.profile:
            return

        for lot in cardinal.profile.get_common_lots():
            desc_lower = (lot.description or "").lower()
            if any(k in desc_lower for k in ["аренд", "rent", "почасов"]):
                try:
                    lot_fields = cardinal.account.get_lot_fields(lot.id)
                    should_be_active = bool(free_accounts_for_order(lot.description or ""))
                    if lot_fields.active != should_be_active:
                        lot_fields.active = should_be_active
                        cardinal.account.save_lot(lot_fields)
                        status_str = "🟢 АКТИВИРОВАН" if should_be_active else "🔴 ДЕАКТИВИРОВАН (нет свободного слота под этот лот)"
                        logger.info(f"[Steam AutoRent] Лот {lot.id} ({lot.description}): {status_str}")
                except Exception as ex:
                    logger.debug(f"[Steam AutoRent] Ошибка синхронизации лота {lot.id}: {ex}")
    except Exception as ex:
        logger.error(f"[Steam AutoRent] Ошибка в sync_lots_visibility: {ex}")

def free_accounts_for_order(order_text: str = "") -> list[dict]:
    now = time.time()
    order_lower = (order_text or "").lower()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT account_id, account_name, login, password, shared_secret, bound_lots, lot_keywords, is_rented, expire_time
            FROM mafile_rentals ORDER BY account_id ASC
        """).fetchall()
    ranked: list[dict] = []
    rest: list[dict] = []
    for r in rows:
        is_free = (not r["is_rented"]) or (r["expire_time"] and r["expire_time"] <= now)
        pwd = str(r["password"] or "").strip()
        if not is_free or len(pwd) < 2:
            continue
        keywords = []
        if r["lot_keywords"]:
            try:
                keywords = json.loads(r["lot_keywords"])
            except Exception:
                keywords = [s.strip() for s in r["lot_keywords"].split(",") if s.strip()]
        hit = any(str(kw).lower() in order_lower for kw in keywords if str(kw).strip())
        if hit:
            ranked.append(dict(r))
        elif not [k for k in keywords if str(k).strip()]:
            rest.append(dict(r))
    return ranked + rest


def get_free_account_for_order(order_text: str = ""):
    rows = free_accounts_for_order(order_text)
    return rows[0] if rows else None

def seed_accounts_if_empty() -> int:
    """Файл → база. Пустой пароль в базе обновляется, если в JSON пароль уже есть.
    Уже записанный пароль файлом не затираем. Базу удалять не нужно.
    """
    path = "rental_accounts.json"
    if not os.path.exists(path):
        return 0
    try:
        rows = json.loads(open(path, encoding="utf-8").read())
    except Exception as ex:
        logger.warning("[AutoRent] rental_accounts.json: %s", ex)
        return 0
    if not isinstance(rows, list):
        return 0
    added = 0
    refreshed = 0
    with get_db() as conn:
        for r in rows:
            if not isinstance(r, dict) or r.get("id") is None:
                continue
            aid = int(r["id"])
            pwd = str(r.get("password") or "")
            kws = json.dumps(r.get("lot_keywords") or [], ensure_ascii=False)
            cur = conn.execute(
                "SELECT password FROM mafile_rentals WHERE account_id = ?", (aid,)
            ).fetchone()
            if cur is None:
                conn.execute(
                    """INSERT INTO mafile_rentals
                       (account_id, account_name, login, password, shared_secret, identity_secret, steamid, lot_keywords)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        aid,
                        r.get("name") or r.get("login") or "",
                        r.get("login") or "",
                        pwd,
                        r.get("shared_secret") or "",
                        r.get("identity_secret") or "",
                        str(r.get("steamid") or ""),
                        kws,
                    ),
                )
                added += 1
                continue
            have = str(cur["password"] or "").strip()
            if len(have) < 2 and len(pwd.strip()) >= 2:
                conn.execute(
                    "UPDATE mafile_rentals SET password = ? WHERE account_id = ?",
                    (pwd, aid),
                )
                refreshed += 1
    if added or refreshed:
        logger.info("[AutoRent] база аренды: новых %s, паролей подтянуто %s", added, refreshed)
    return added + refreshed


def reserve_account(account_id, duration_sec, renter_chat_id, renter_name, order_id, renter_node: str = "") -> bool:
    """True только если слот ещё был свободен. Второй поток получит False."""
    now = time.time()
    exp = now + duration_sec
    with get_db() as conn:
        cur = conn.execute("""
            UPDATE mafile_rentals
            SET is_rented = 1, renter_chat_id = ?, renter_name = ?, order_id = ?, duration_seconds = ?, start_time = ?, expire_time = ?, warned_15m = 0, renter_node = ?
            WHERE account_id = ? AND (is_rented = 0 OR expire_time <= ?)
        """, (renter_chat_id, renter_name, order_id, duration_sec, now, exp, (renter_node or "")[:80], account_id, now))
        if cur.rowcount == 1:
            return True
        if cur.rowcount == 0:
            return False
        row = conn.execute(
            "SELECT order_id, is_rented FROM mafile_rentals WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        return bool(row and row["is_rented"] and str(row["order_id"] or "") == str(order_id))

def is_order_processed(order_id: str) -> bool:
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM processed_orders WHERE order_id = ? AND plugin_name = 'autorent'", (order_id,))
        return bool(c.fetchone())

def mark_order_processed(order_id: str):
    claim_order(str(order_id), "autorent")

_PARK_KEY = "autorent_paused"


def _parked() -> dict:
    from shop_core.bus import get_flag
    try:
        data = json.loads(get_flag(_PARK_KEY, "{}") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _park_rental(order, desc: str) -> None:
    from shop_core.bus import set_flag
    data = _parked()
    data[str(getattr(order, "id", ""))] = {
        "description": desc,
        "buyer_username": getattr(order, "buyer_username", None),
        "buyer_id": getattr(order, "buyer_id", None),
        "chat_id": str(getattr(order, "chat_id", "") or ""),
        "amount": int(getattr(order, "amount", 1) or 1),
        "price": float(getattr(order, "price", 0) or getattr(order, "sum", 0) or 0),
    }
    set_flag(_PARK_KEY, json.dumps(data, ensure_ascii=False))


def resume_parked_rentals(cardinal) -> int:
    """После снятия стопа: только оплаченные заказы идут в обычную выдачу, остальные — продавцу."""
    from types import SimpleNamespace
    from shop_core.bus import set_flag
    from shop_core.finance import order_pay_state
    if is_frozen() or is_panic():
        return 0
    data = _parked()
    if not data:
        return 0
    set_flag(_PARK_KEY, "{}")
    keep, done = {}, 0
    for oid, meta in data.items():
        state, detail = order_pay_state(cardinal, oid)
        if state == "network":
            keep[oid] = meta
            continue
        if state != "paid":
            notify(cardinal, f"⛔ AutoRent #{oid}: после стопа заказ уже не оплачен ({detail}), слот не выдаю.", True)
            continue
        chat = meta.get("chat_id") or None
        if chat and str(chat).lstrip("-").isdigit():
            chat = int(chat)
        order = SimpleNamespace(
            id=oid, description=meta.get("description") or "", title=meta.get("description") or "",
            buyer_username=meta.get("buyer_username") or "клиент", buyer_id=meta.get("buyer_id"),
            chat_id=chat, amount=meta.get("amount") or 1, price=meta.get("price") or 0,
        )
        _handle_new_rental_order(cardinal, SimpleNamespace(order=order))
        done += 1
    if keep:
        merged = {**keep, **_parked()}
        set_flag(_PARK_KEY, json.dumps(merged, ensure_ascii=False))
        notify(cardinal, f"⚠️ AutoRent: FunPay не ответил по {len(keep)} заказам, повторю на следующем снятии стопа.", True)
    return done


def _handle_new_rental_order(cardinal, event):
    try:
        order = getattr(event, "order", None)
        if not order:
            return

        order_id = getattr(order, "id", "")
        desc = getattr(order, "description", "") or getattr(order, "title", "") or ""
        desc_lower = desc.lower()

        if not ini_bool(CONFIG_FILE, "AutoRent", "enabled", True):
            return
        if not any(k in desc_lower for k in ["аренд", "rent", "почасов"]):
            return
        if any(k in desc_lower for k in ("wallet", "кошел", "пополн", "робукс", "robux", "stars", "накрут", "gamepass")):
            return

        if is_order_processed(order_id):
            return
        if is_frozen() or is_panic():
            _park_rental(order, desc)
            notify(
                cardinal,
                f"⏸ AutoRent #{order_id}: заказ пришёл на стопе (freeze/panic). Слот не трогал, "
                f"после снятия стопа проверю оплату и выдам сам.",
                True,
            )
            return
        if is_dry_run():
            notify(cardinal, f"🧪 DRY-RUN AutoRent #{order_id}: аккаунт не выдавался.", False)
            return

        buyer_name = getattr(order, "buyer_username", "клиент")
        buyer_chat = getattr(order, "chat_id", None)
        amount = getattr(order, "amount", 1) or 1

        duration_sec = parse_duration_from_order(desc, amount)
        duration_readable = format_duration_readable(duration_sec)

        acc = get_free_account_for_order(desc)
        if not acc:
            warn_msg = f"Здравствуйте, {buyer_name}! Заказ #{order_id} принят. Свободных слотов сейчас нет, продавец подключится вручную."
            if buyer_chat:
                bot_send(cardinal, buyer_chat, warn_msg)
            if cardinal.telegram:
                cardinal.telegram.send_notification(f"⚠️ <b>[AutoRent] Нет свободных аккаунтов!</b>\nЗаказ: <code>#{order_id}</code> от <b>{buyer_name}</b>")
            return

        if not claim_delivery(str(order_id), "autorent"):
            return
        aid = getattr(getattr(cardinal, "account", None), "id", None)
        peer = bind_order_chat(buyer_chat, account_id=aid, peer_id=getattr(order, "buyer_id", None))
        node = str(buyer_chat) if buyer_chat is not None else ""
        acc = None
        for cand in free_accounts_for_order(desc):
            if reserve_account(
                cand["account_id"], duration_sec, peer if peer is not None else 0,
                buyer_name, order_id, renter_node=node,
            ):
                acc = cand
                break
        if not acc:
            release_delivery(str(order_id), "autorent")
            warn_msg = f"Здравствуйте, {buyer_name}! Заказ #{order_id} принят. Свободных слотов сейчас нет, продавец подключится вручную."
            if buyer_chat:
                bot_send(cardinal, buyer_chat, warn_msg)
            notify(cardinal, f"⚠️ AutoRent #{order_id}: слот успели занять, выдача не пошла.", True)
            return
        def rollback(reason: str) -> None:
            with get_db() as conn:
                conn.execute(
                    """UPDATE mafile_rentals
                       SET is_rented = 0, renter_chat_id = NULL, renter_name = NULL,
                           order_id = NULL, renter_node = NULL
                       WHERE account_id = ?""",
                    (acc["account_id"],),
                )
            release_delivery(str(order_id), "autorent")
            notify(cardinal, f"❌ AutoRent #{order_id}: слот {acc['account_name']} вернул — {reason}.", True)

        try:
            guard_code = generate_steam_guard_code(acc["shared_secret"])
            expire_str = time.strftime("%H:%M", time.localtime(time.time() + duration_sec))
            msg = render_rent_message(
                lot_name=acc["account_name"],
                login=acc["login"],
                password=acc["password"],
                guard_code=guard_code,
                duration_str=duration_readable,
                expire_str=expire_str,
            )
        except Exception as ex:
            logger.warning("[Steam AutoRent] текст выдачи #%s: %s", order_id, ex)
            rollback("не собрал текст выдачи")
            return

        if buyer_chat:
            try:
                sent = bot_send(cardinal, buyer_chat, msg, buyer_name)
            except Exception as ex:
                sent = None
                logger.warning("[Steam AutoRent] чат не принял выдачу #%s: %s", order_id, ex)
        else:
            sent = None
        if not sent:
            rollback("покупатель сообщение не получил")
            return

        try:
            from shop_core.finance import log_finance
            from shop_core.settings import commission
            sale = float(getattr(order, "price", 0) or getattr(order, "sum", 0) or 0)
            log_finance(str(order_id), "autorent", sale, sale * commission())
        except Exception as ex:
            logger.debug("[Steam AutoRent] finance: %s", ex)

        logger.info(f"[Steam AutoRent] Выдан #{acc['account_id']} ({acc['login']}) покупателю {buyer_name} на {duration_readable}")

        if cardinal.telegram:
            cardinal.telegram.send_notification(
                f"🚀 Steam аренда #{order_id}: {buyer_name} · {acc['login']} · {duration_readable}. "
                f"Пароль ушёл только в чат FunPay."
            )

        sync_lots_visibility(cardinal)

    except Exception as ex:
        logger.error(f"[Steam AutoRent] Ошибка обработки заказа: {ex}", exc_info=True)

def _handle_guard_msg(cardinal, event):
    try:
        msg = getattr(event, "message", None)
        if not msg or msg.author_id == cardinal.account.id or getattr(msg, "by_bot", False):
            return

        text = (msg.text or "").strip().lower()
        words = set(re.findall(r"[a-zа-яё0-9]+", text))
        singles = {w for w in GUARD_TRIGGER_WORDS if " " not in w and not w.startswith("!")}
        phrases = [w for w in GUARD_TRIGGER_WORDS if " " in w]
        if not (text.lstrip("!") in singles or words & singles or any(p in text for p in phrases)):
            return

        chat_id = msg.chat_id
        now = time.time()
        aid = getattr(getattr(cardinal, "account", None), "id", None)
        ids = []
        for cand in (chat_id, getattr(msg, "author_id", None), getattr(msg, "interlocutor_id", None)):
            n = as_chat_id(cand, account_id=aid)
            if n is not None and n not in ids and n != int(aid or -1):
                ids.append(n)
        name = (getattr(msg, "chat_name", None) or "").strip()
        if not ids and not name:
            return
        with get_db() as conn:
            c = conn.cursor()
            if ids and name:
                q = ",".join("?" * len(ids))
                c.execute(
                    f"""SELECT account_id, account_name, login, shared_secret, expire_time
                        FROM mafile_rentals
                        WHERE is_rented = 1 AND expire_time > ?
                          AND (renter_chat_id IN ({q}) OR lower(renter_name) = lower(?))""",
                    (now, *ids, name),
                )
            elif ids:
                q = ",".join("?" * len(ids))
                c.execute(
                    f"""SELECT account_id, account_name, login, shared_secret, expire_time
                        FROM mafile_rentals
                        WHERE is_rented = 1 AND expire_time > ? AND renter_chat_id IN ({q})""",
                    (now, *ids),
                )
            else:
                c.execute(
                    """SELECT account_id, account_name, login, shared_secret, expire_time
                       FROM mafile_rentals
                       WHERE is_rented = 1 AND expire_time > ? AND lower(renter_name) = lower(?)""",
                    (now, name),
                )
            row = c.fetchone()

        if not row:
            return

        fresh_code = generate_steam_guard_code(row["shared_secret"])
        rem_sec = int(row["expire_time"] - now)
        rem_str = f"{rem_sec // 3600} ч. {(rem_sec % 3600) // 60} мин." if rem_sec >= 3600 else f"{rem_sec // 60} мин."

        reply = f"🛡️ Ваш свежий код Steam Guard: {fresh_code}\n⏳ Действует 30 секунд. До конца аренды: ~{rem_str}."
        bot_send(cardinal, chat_id, reply, msg.chat_name)

    except Exception as ex:
        logger.error(f"[Steam AutoRent] Ошибка выдачи кода в чате: {ex}")

def _timer_loop(cardinal):
    while True:
        try:
            now = time.time()
            with get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT account_id, account_name, renter_chat_id, renter_name, renter_node FROM mafile_rentals WHERE is_rented = 1 AND expire_time <= ?", (now,))
                expired = c.fetchall()

                for r in expired:
                    c.execute(
                        "UPDATE mafile_rentals SET is_rented = 0, renter_chat_id = NULL, renter_name = NULL, order_id = NULL, renter_node = NULL WHERE account_id = ?",
                        (r["account_id"],),
                    )
                    dest = (r["renter_node"] or "").strip() or r["renter_chat_id"]
                    if dest:
                        bot_send(cardinal, dest, f"Время аренды ({r['account_name']}) вышло. Если всё ок — зайди в покупки. Удачи.")
                    logger.info(f"[Steam AutoRent] Аккаунт #{r['account_id']} освобожден по таймеру.")

            if expired:
                sync_lots_visibility(cardinal)

        except Exception as ex:
            logger.error(f"[Steam AutoRent Timer] Ошибка таймера: {ex}")
        time.sleep(15)

_TIMER_STARTED = False

def init_post(cardinal):
    global _TIMER_STARTED
    if not _TIMER_STARTED:
        _TIMER_STARTED = True
        Thread(target=_timer_loop, args=(cardinal,), daemon=True).start()

    Thread(target=sync_lots_visibility, args=(cardinal,), daemon=True).start()

def on_order_rent(cardinal, event):
    Thread(target=_handle_new_rental_order, args=(cardinal, event), daemon=True).start()

def on_msg_guard(cardinal, event):
    Thread(target=_handle_guard_msg, args=(cardinal, event), daemon=True).start()

def init_settings(cardinal):
    from shop_core import hooks
    hooks.subscribe("on_unfreeze", resume_parked_rentals)
    seed_accounts_if_empty()
    def status():
        now = time.time()
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM mafile_rentals")
            total = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM mafile_rentals WHERE is_rented = 1 AND expire_time > ?", (now,))
            busy = c.fetchone()[0]
        return f"Слотов: <b>{total}</b> | занято: <b>{busy}</b> | свободно: <b>{total - busy}</b>"

    SettingsPage(UUID, NAME, "Выдача Steam + Guard-код по слову «код». maFile в папке mafiles.") \
        .add_toggle("enabled", "Автоаренда",
                    lambda: ini_bool(CONFIG_FILE, "AutoRent", "enabled", True),
                    lambda _v: flip_ini(CONFIG_FILE, "AutoRent", "enabled", True)) \
        .set_status(status) \
        .attach(cardinal)


BIND_TO_PRE_INIT = [init_settings]
BIND_TO_POST_INIT = [init_post]
BIND_TO_NEW_ORDER = [on_order_rent]
BIND_TO_NEW_MESSAGE = [on_msg_guard]
