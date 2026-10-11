# -*- coding: utf-8 -*-
from __future__ import annotations
import html
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

_UNIT = r"(ч\b|час\w*|h\b|hours?\b|д\b|дн\w*|день|сут\w*|d\b|days?\b|нед\w*|w\b|weeks?\b)"
_TAG_RE = re.compile(r"\[\s*(?:rent|аренда|срок)\s*:?\s*(\d+)\s*" + _UNIT + r"\s*\]", re.IGNORECASE)
_PHRASE_RES = [
    re.compile(r"аренд\w*\s+на\s+(\d+)\s*" + _UNIT, re.IGNORECASE),
    re.compile(r"(\d+)\s*" + _UNIT + r"\s+аренд\w*", re.IGNORECASE),
    re.compile(r"срок\w*\s*(?:аренды)?\s*[:\-—]?\s*(\d+)\s*" + _UNIT, re.IGNORECASE),
    re.compile(r"\bна\s+(\d+)\s*" + _UNIT, re.IGNORECASE),
]
_WORD_RES = [
    (re.compile(r"аренд\w*\s+на\s+сутки|\bна\s+сутки", re.IGNORECASE), 86400),
    (re.compile(r"аренд\w*\s+на\s+недел\w*|\bна\s+недел[юи]", re.IGNORECASE), 604800),
    (re.compile(r"аренд\w*\s+на\s+час\b|\bна\s+час\b|\bна\s+1\s+час\b", re.IGNORECASE), 3600),
]


def _unit_seconds(unit: str) -> int:
    u = unit.lower()
    if u.startswith(("ч", "h")):
        return 3600
    if u.startswith(("н", "w")):
        return 604800
    return 86400


def parse_rent_duration(order_desc: str, order_amount: int = 1, max_hours: int = 336) -> tuple[int | None, str]:
    """Срок аренды в секундах и откуда он взят. None — срок непонятен, автоматически не выдаём.

    Берётся только явный тег [rent: 3h] или фраза про аренду («аренда на 3 часа», «2 дня аренды»).
    Любое «N часов» больше не считается сроком: «2500 часов в игре» давало аренду на 2500 часов.
    """
    text = order_desc or ""
    amount = max(1, int(order_amount or 1))
    base, how = None, ""
    m = _TAG_RE.search(text)
    if m:
        base, how = int(m.group(1)) * _unit_seconds(m.group(2)), f"тег «{m.group(0)}»"
    if base is None:
        for rx in _PHRASE_RES:
            m = rx.search(text)
            if m:
                base, how = int(m.group(1)) * _unit_seconds(m.group(2)), f"фраза «{m.group(0).strip()}»"
                break
    if base is None:
        for rx, seconds in _WORD_RES:
            m = rx.search(text)
            if m:
                base, how = seconds, f"фраза «{m.group(0).strip()}»"
                break
    if not base:
        return None, "в названии лота нет срока аренды (нужен тег вида [rent: 3h] или «аренда на 3 часа»)"
    total = base * amount
    if total > max(1, int(max_hours)) * 3600:
        return None, f"срок {total // 3600} ч больше лимита {max_hours} ч ({how})"
    return total, how


def parse_duration_from_order(order_desc: str, order_amount: int = 1) -> int:
    seconds, _how = parse_rent_duration(order_desc, order_amount, _cfg_int("max_rent_hours", 336))
    return seconds or 0


def _cfg_int(key: str, default: int) -> int:
    from shop_core.settings import load_ini
    cfg = load_ini(CONFIG_FILE)
    try:
        return int(cfg.get("AutoRent", key, fallback=str(default)) or default)
    except ValueError:
        return default


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
            SELECT account_id, account_name, login, password, shared_secret, bound_lots, lot_keywords, is_rented, expire_time,
                   COALESCE(needs_reset, 0) AS needs_reset
            FROM mafile_rentals ORDER BY account_id ASC
        """).fetchall()
    ranked: list[dict] = []
    rest: list[dict] = []
    for r in rows:
        is_free = (not r["is_rented"]) or (r["expire_time"] and r["expire_time"] <= now)
        pwd = str(r["password"] or "").strip()
        if not is_free or len(pwd) < 2 or r["needs_reset"]:
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
            SET is_rented = 1, renter_chat_id = ?, renter_name = ?, order_id = ?, duration_seconds = ?, start_time = ?, expire_time = ?, warned_15m = 0, renter_node = ?, codes_given = 0
            WHERE account_id = ? AND (is_rented = 0 OR expire_time <= ?) AND COALESCE(needs_reset, 0) = 0
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

        duration_sec, duration_how = parse_rent_duration(desc, amount, _cfg_int("max_rent_hours", 336))
        if not duration_sec:
            if buyer_chat:
                bot_send(cardinal, buyer_chat,
                         f"Здравствуйте, {buyer_name}! Заказ #{order_id} принят, продавец сейчас подключится и выдаст аккаунт.")
            notify(
                cardinal,
                f"⚠️ <b>AutoRent #{html.escape(str(order_id))}: выдаю вручную</b>\n"
                f"Причина: {html.escape(duration_how)}.\n"
                f"Лот: <i>{html.escape(desc[:200])}</i>\n"
                f"Добавь в название лота тег <code>[rent: 3h]</code> (или «аренда на 3 часа») — тогда выдача пойдёт сама.",
                True,
            )
            return
        duration_readable = format_duration_readable(duration_sec)

        acc = get_free_account_for_order(desc)
        if not acc:
            warn_msg = f"Здравствуйте, {buyer_name}! Заказ #{order_id} принят. Свободных слотов сейчас нет, продавец подключится вручную."
            if buyer_chat:
                bot_send(cardinal, buyer_chat, warn_msg)
            notify(
                cardinal,
                f"⚠️ <b>[AutoRent] Нет свободных аккаунтов!</b>\nЗаказ: <code>#{html.escape(str(order_id))}</code> "
                f"от <b>{html.escape(str(buyer_name))}</b>\n{_slots_summary()}",
                True,
            )
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
                    f"""SELECT account_id, account_name, login, shared_secret, expire_time, COALESCE(codes_given, 0) AS codes_given, order_id
                        FROM mafile_rentals
                        WHERE is_rented = 1 AND expire_time > ?
                          AND (renter_chat_id IN ({q}) OR lower(renter_name) = lower(?))""",
                    (now, *ids, name),
                )
            elif ids:
                q = ",".join("?" * len(ids))
                c.execute(
                    f"""SELECT account_id, account_name, login, shared_secret, expire_time, COALESCE(codes_given, 0) AS codes_given, order_id
                        FROM mafile_rentals
                        WHERE is_rented = 1 AND expire_time > ? AND renter_chat_id IN ({q})""",
                    (now, *ids),
                )
            else:
                c.execute(
                    """SELECT account_id, account_name, login, shared_secret, expire_time, COALESCE(codes_given, 0) AS codes_given, order_id
                       FROM mafile_rentals
                       WHERE is_rented = 1 AND expire_time > ? AND lower(renter_name) = lower(?)""",
                    (now, name),
                )
            row = c.fetchone()

        if not row:
            return

        limit = _cfg_int("max_codes_per_rent", 10)
        given = int(row["codes_given"] or 0)
        if limit > 0 and given >= limit:
            if given == limit:
                with get_db() as conn:
                    conn.execute("UPDATE mafile_rentals SET codes_given = codes_given + 1 WHERE account_id = ?",
                                 (row["account_id"],))
                notify(cardinal, f"🛡️ AutoRent #{html.escape(str(row['order_id'] or '—'))}: арендатор "
                                 f"{html.escape(name or '—')} исчерпал лимит кодов ({limit}) для "
                                 f"{html.escape(str(row['account_name']))}. Проверь, не пытается ли он сменить пароль.", True)
            bot_send(cardinal, chat_id, "Лимит кодов на эту аренду исчерпан. Если не получается войти — напиши продавцу.",
                     msg.chat_name)
            return
        with get_db() as conn:
            conn.execute("UPDATE mafile_rentals SET codes_given = COALESCE(codes_given, 0) + 1 WHERE account_id = ?",
                         (row["account_id"],))

        fresh_code = generate_steam_guard_code(row["shared_secret"])
        rem_sec = int(row["expire_time"] - now)
        rem_str = f"{rem_sec // 3600} ч. {(rem_sec % 3600) // 60} мин." if rem_sec >= 3600 else f"{rem_sec // 60} мин."

        reply = f"🛡️ Ваш свежий код Steam Guard: {fresh_code}\n⏳ Действует 30 секунд. До конца аренды: ~{rem_str}."
        bot_send(cardinal, chat_id, reply, msg.chat_name)

    except Exception as ex:
        logger.error(f"[Steam AutoRent] Ошибка выдачи кода в чате: {ex}")

def _reset_kb(account_id) -> K:
    kb = K()
    kb.row(B("✅ Пароль сменил, сессии сбросил — открыть слот", callback_data=f"{CBT_PREFIX}:reset:{account_id}"))
    return kb


def _slots_summary() -> str:
    now = time.time()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT is_rented, expire_time, COALESCE(needs_reset, 0) AS needs_reset, password FROM mafile_rentals"
        ).fetchall()
    total = len(rows)
    busy = sum(1 for r in rows if r["is_rented"] and (r["expire_time"] or 0) > now)
    reset = sum(1 for r in rows if r["needs_reset"])
    nopass = sum(1 for r in rows if len(str(r["password"] or "").strip()) < 2)
    free = max(0, total - busy - reset - nopass)
    return (f"Слотов: <b>{total}</b> | занято: <b>{busy}</b> | свободно: <b>{free}</b> | "
            f"ждут смены пароля: <b>{reset}</b> | без пароля: <b>{nopass}</b>")


def release_expired(cardinal, now: float | None = None) -> list[dict]:
    """Закрывает истёкшие аренды. Слот остаётся закрытым до смены пароля (require_reset=1)."""
    now = time.time() if now is None else now
    need_reset = 1 if _cfg_int("require_reset", 1) else 0
    with get_db() as conn:
        expired = [dict(r) for r in conn.execute(
            """SELECT account_id, account_name, login, renter_chat_id, renter_name, renter_node, order_id
               FROM mafile_rentals WHERE is_rented = 1 AND expire_time <= ?""", (now,),
        ).fetchall()]
        for r in expired:
            conn.execute(
                """UPDATE mafile_rentals
                   SET is_rented = 0, renter_chat_id = NULL, renter_name = NULL, order_id = NULL, renter_node = NULL,
                       needs_reset = ?, codes_given = 0, last_renter = ?
                   WHERE account_id = ?""",
                (need_reset, r["renter_name"], r["account_id"]),
            )
    for r in expired:
        dest = (r["renter_node"] or "").strip() or r["renter_chat_id"]
        if dest:
            bot_send(cardinal, dest, f"Время аренды ({r['account_name']}) вышло. Если всё ок — зайди в покупки. Удачи.")
        logger.info("[Steam AutoRent] Аккаунт #%s освобожден по таймеру.", r["account_id"])
        if need_reset:
            notify(
                cardinal,
                f"🔐 <b>Аренда закончилась: {html.escape(str(r['account_name']))}</b> (слот {r['account_id']}, "
                f"арендатор {html.escape(str(r['renter_name'] or '—'))}).\n"
                f"Слот закрыт, пока не сменишь пароль: прошлый арендатор знает пароль и мог остаться в аккаунте.\n"
                f"1. Смени пароль Steam и нажми «Выйти на всех устройствах» в Steam Guard.\n"
                f"2. Пришли боту <code>/rentpass {r['account_id']} новый_пароль</code> — слот откроется сам.\n"
                f"Или нажми кнопку, если пароль уже сменён другим способом.",
                True,
                keyboard=_reset_kb(r["account_id"]),
            )
    return expired


def _timer_loop(cardinal):
    while True:
        try:
            expired = release_expired(cardinal)
            if expired:
                sync_lots_visibility(cardinal)
        except Exception as ex:
            logger.error(f"[Steam AutoRent Timer] Ошибка таймера: {ex}")
        time.sleep(15)


def seed_from_mafiles(folder: str = "mafiles") -> int:
    """Каждый .maFile — слот аренды. Пароля в maFile нет: слот откроется после /rentpass."""
    if not os.path.isdir(folder):
        return 0
    added = 0
    with get_db() as conn:
        known = conn.execute("SELECT account_id, lower(COALESCE(login, '')) AS login, "
                             "lower(COALESCE(account_name, '')) AS name, COALESCE(steamid, '') AS steamid "
                             "FROM mafile_rentals").fetchall()
        logins = {r["login"] for r in known} | {r["name"] for r in known}
        steamids = {str(r["steamid"]) for r in known if r["steamid"]}
        next_id = max([int(r["account_id"]) for r in known] + [0]) + 1
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith(".mafile"):
                continue
            try:
                data = json.loads(open(os.path.join(folder, name), encoding="utf-8").read())
            except Exception as ex:
                logger.warning("[AutoRent] %s: не читается (%s)", name, ex)
                continue
            login = str(data.get("account_name") or "").strip()
            secret = str(data.get("shared_secret") or "").strip()
            steamid = str((data.get("Session") or {}).get("SteamID") or "").strip()
            if not login or not secret:
                continue
            if login.lower() in logins or (steamid and steamid in steamids):
                continue
            conn.execute(
                """INSERT INTO mafile_rentals
                   (account_id, account_name, login, password, shared_secret, identity_secret, steamid, lot_keywords)
                   VALUES (?, ?, ?, '', ?, ?, ?, '[]')""",
                (next_id, login, login, secret, str(data.get("identity_secret") or ""), steamid),
            )
            logins.add(login.lower())
            if steamid:
                steamids.add(steamid)
            next_id += 1
            added += 1
    if added:
        logger.info("[AutoRent] из mafiles добавлено слотов: %s (задай пароль: /rentpass <id> <пароль>)", added)
    return added


def set_rent_password(account_id: int, password: str) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE mafile_rentals SET password = ?, needs_reset = 0 WHERE account_id = ?",
            (password, int(account_id)),
        )
        return cur.rowcount == 1


def reopen_slot(account_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("UPDATE mafile_rentals SET needs_reset = 0 WHERE account_id = ?", (int(account_id),))
        return cur.rowcount == 1


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

_TG_READY = False


def _can_manage(cardinal, uid: int) -> bool:
    tg = getattr(cardinal, "telegram", None)
    return bool(tg) and uid in getattr(tg, "authorized_users", {})


def init_settings(cardinal):
    global _TG_READY
    from shop_core import hooks
    hooks.subscribe("on_unfreeze", resume_parked_rentals)
    seed_accounts_if_empty()
    seed_from_mafiles()

    SettingsPage(UUID, NAME, "Выдача Steam + Guard-код по слову «код». maFile в папке mafiles.") \
        .add_toggle("enabled", "Автоаренда",
                    lambda: ini_bool(CONFIG_FILE, "AutoRent", "enabled", True),
                    lambda _v: flip_ini(CONFIG_FILE, "AutoRent", "enabled", True)) \
        .add_toggle("reset", "После аренды закрывать слот до смены пароля",
                    lambda: ini_bool(CONFIG_FILE, "AutoRent", "require_reset", True),
                    lambda _v: flip_ini(CONFIG_FILE, "AutoRent", "require_reset", True)) \
        .set_status(_slots_summary) \
        .attach(cardinal)

    tg = getattr(cardinal, "telegram", None)
    if _TG_READY or not tg or not getattr(tg, "bot", None):
        return
    _TG_READY = True
    bot = tg.bot

    def cmd_rentpass(m):
        if not _can_manage(cardinal, m.from_user.id):
            return
        try:
            bot.delete_message(m.chat.id, m.id)
        except Exception:
            pass
        parts = (m.text or "").split(maxsplit=2)
        if len(parts) < 3 or not parts[1].isdigit() or len(parts[2].strip()) < 2:
            bot.send_message(m.chat.id, "Формат: <code>/rentpass ID_слота новый_пароль</code>\n" + _slots_summary(),
                             parse_mode="HTML")
            return
        if set_rent_password(int(parts[1]), parts[2].strip()):
            bot.send_message(m.chat.id, f"✅ Пароль слота {parts[1]} обновлён, слот открыт. Сообщение с паролем удалил.")
            Thread(target=sync_lots_visibility, args=(cardinal,), daemon=True).start()
        else:
            bot.send_message(m.chat.id, f"Слота {parts[1]} нет.\n" + _slots_summary(), parse_mode="HTML")

    def cb_reset(c):
        if not _can_manage(cardinal, c.from_user.id):
            return
        parts = (c.data or "").split(":")
        if len(parts) != 3 or not parts[2].isdigit():
            bot.answer_callback_query(c.id)
            return
        ok = reopen_slot(int(parts[2]))
        bot.answer_callback_query(c.id, "Слот открыт." if ok else "Слот не найден.")
        if ok:
            try:
                bot.edit_message_text(f"✅ Слот {parts[2]} снова свободен для аренды.", c.message.chat.id, c.message.id)
            except Exception:
                pass
            Thread(target=sync_lots_visibility, args=(cardinal,), daemon=True).start()

    tg.msg_handler(cmd_rentpass, commands=["rentpass"])
    tg.cbq_handler(cb_reset, lambda c: (c.data or "").startswith(f"{CBT_PREFIX}:reset:"))
    cardinal.add_telegram_commands(UUID, [("rentpass", "пароль слота аренды Steam", True)])


BIND_TO_PRE_INIT = [init_settings]
BIND_TO_POST_INIT = [init_post]
BIND_TO_NEW_ORDER = [on_order_rent]
BIND_TO_NEW_MESSAGE = [on_msg_guard]
