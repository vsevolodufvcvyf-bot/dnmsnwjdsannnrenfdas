# -*- coding: utf-8 -*-
from __future__ import annotations

import gzip
import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime
from threading import Thread

from shop_core import logging_redact
from shop_core.bus import (
    MSG_ORIGIN, bind_cardinal, bypass_freeze, drain_digest, freeze, freeze_bypassed, get_flag, hydrate,
    is_frozen, mark_human, notify, quiet_hours_now, release_chat, unfreeze,
)
from shop_core.db import DB_FILE, get_db
from shop_core.settings import is_dry_run, is_panic, load_ops, min_margin_mult, set_flag
from shop_core.plugin_settings import SettingsPage

logger = logging.getLogger("FPC.OpsCore")

NAME = "Операции (стоп / учебный режим)"
VERSION = "1.0.1"
DESCRIPTION = "Шина чатов, аварийный стоп, учебный режим, тихие часы, бэкап БД"
CREDITS = "Cardinal Community"
UUID = "a1c0e001-1111-4b00-9c01-000000000001"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}

_INSTALLED = False
_TG_CMDS = False
_LAST_DIGEST_DAY = ""
_LAST_BACKUP_DAY = ""


def _looks_like_captcha(text: str) -> bool:
    t = (text or "").lower()
    return any(x in t for x in ("cf-turnstile", "challenges.cloudflare", "attention required", "checking your browser"))


def _install_watchdog(cardinal) -> None:
    account = cardinal.account
    orig = account.method

    def wrapped(*args, **kwargs):
        from FunPayAPI.common.exceptions import UnauthorizedError
        if is_frozen() and not freeze_bypassed():
            time.sleep(20)
            raise RuntimeError("FunPay session frozen")
        try:
            resp = orig(*args, **kwargs)
        except UnauthorizedError:
            freeze("FunPay 401/403 — проверь golden_key", cardinal)
            raise
        try:
            body = ""
            try:
                body = resp.text[:4000]
            except Exception:
                body = ""
            if _looks_like_captcha(body):
                freeze("капча / Cloudflare на FunPay", cardinal)
                raise RuntimeError("Captcha freeze")
        except RuntimeError:
            raise
        except Exception:
            pass
        return resp

    account.method = wrapped

    orig_send = cardinal.send_message

    def send_wrapped(chat_id, message_text, chat_name=None, interlocutor_id=None, attempts=3, watermark=False):
        origin = MSG_ORIGIN.get()
        if origin == "human" and chat_id is not None:
            try:
                mark_human(chat_id)
            except Exception:
                pass
        if origin == "bot":
            watermark = False
        return orig_send(chat_id, message_text, chat_name, interlocutor_id, attempts, watermark)

    cardinal.send_message = send_wrapped


BACKUP_KEEP_DAYS = 14
LOG_KEEP_DAYS = 30
_LAST_PROBE = 0.0
_LAST_UPSTREAM_DAY = ""


def _upstream_daily(cardinal) -> None:
    global _LAST_UPSTREAM_DAY
    day = datetime.now().strftime("%Y-%m-%d")
    if day == _LAST_UPSTREAM_DAY:
        return
    _LAST_UPSTREAM_DAY = day
    if not load_ops().getboolean("Ops", "upstream_check", fallback=True):
        return
    from shop_core.upstream import check_and_notify
    check_and_notify(cardinal)


def backup_db(db_file: str, dest: str) -> None:
    """Снимок через sqlite backup API: в копию попадают и транзакции из -wal файла."""
    tmp_db = dest + ".snapshot"
    src = sqlite3.connect(db_file, timeout=30)
    dst = sqlite3.connect(tmp_db)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    try:
        with open(tmp_db, "rb") as raw, gzip.open(dest + ".tmp", "wb") as gz:
            shutil.copyfileobj(raw, gz)
        os.replace(dest + ".tmp", dest)
    finally:
        try:
            os.remove(tmp_db)
        except OSError:
            pass


def _remove_older_than(folder: str, days: int, prefix: str = "") -> None:
    cutoff = time.time() - days * 86400
    if not os.path.isdir(folder):
        return
    for name in os.listdir(folder):
        if prefix and not name.startswith(prefix):
            continue
        path = os.path.join(folder, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


def _backup_once():
    global _LAST_BACKUP_DAY
    day = datetime.now().strftime("%Y-%m-%d")
    if day == _LAST_BACKUP_DAY:
        return
    if not os.path.exists(DB_FILE):
        return
    dest_dir = os.path.join("storage", "backups")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"cardinal_storage_{day}.db.gz")
    if not os.path.exists(dest):
        backup_db(DB_FILE, dest)
    _LAST_BACKUP_DAY = day
    _remove_older_than(dest_dir, BACKUP_KEEP_DAYS, prefix="cardinal_storage_")
    _remove_older_than("logs", LOG_KEEP_DAYS)


def probe_session(cardinal, now: float | None = None) -> bool:
    """Заморозку из-за 401 / капчи снимает сама, если сессия FunPay снова отвечает.

    Аварийный стоп (panic) не трогает. True — заморозка снята.
    """
    global _LAST_PROBE
    if is_panic() or not is_frozen():
        return False
    cfg = load_ops()
    if not cfg.getboolean("Watchdog", "auto_unfreeze", fallback=True):
        return False
    every = max(5, cfg.getint("Watchdog", "probe_every_min", fallback=15)) * 60
    now = time.time() if now is None else now
    if now - _LAST_PROBE < every:
        return False
    _LAST_PROBE = now
    reason = get_flag("freeze_reason", "") or "—"
    account = getattr(cardinal, "account", None)
    if account is None:
        return False
    try:
        with bypass_freeze():
            account.get()
    except Exception as ex:
        logger.info("[OpsCore] проба сессии FunPay: всё ещё не работает (%s)", ex)
        return False
    unfreeze()
    notify(cardinal, f"▶️ Сессия FunPay снова отвечает — заморозка снята автоматически.\nПричина была: {reason}", True)
    return True


def _loop(cardinal):
    global _LAST_DIGEST_DAY
    while True:
        try:
            _backup_once()
            probe_session(cardinal)
            _upstream_daily(cardinal)
            now = datetime.now()
            cfg = load_ops()
            to = cfg.get("Ops", "quiet_to", fallback="09:00")
            try:
                hh, mm = [int(x) for x in to.split(":", 1)]
            except ValueError:
                hh, mm = 9, 0
            day = now.strftime("%Y-%m-%d")
            if (now.hour, now.minute) >= (hh, mm) and _LAST_DIGEST_DAY != day:
                _LAST_DIGEST_DAY = day
                drain_digest(cardinal)
        except Exception as ex:
            logger.debug("[OpsCore] loop: %s", ex)
        time.sleep(50)


def _stats_text(cardinal) -> str:
    with get_db() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(sale_price),0), COALESCE(SUM(cost),0), COALESCE(SUM(profit),0), COUNT(*)
               FROM finance_log WHERE created_at > ?""",
            (time.time() - 86400 * 30,),
        ).fetchone()
        sales, cost, profit, n = row
        dry = conn.execute("SELECT COUNT(*) FROM finance_log WHERE dry_run = 1").fetchone()[0]
        frozen = "ДА" if is_frozen() else "нет"
        panic = "ДА" if is_panic() else "нет"
        dry_run = "ДА" if is_dry_run() else "нет"
        quiet = "сейчас" if quiet_hours_now() else "выкл"
    bal = getattr(cardinal, "balance", None)
    fp = getattr(bal, "total_rub", 0) if bal else 0
    return (
        f"📊 <b>/stats 30 дней</b>\n"
        f"Сделок в журнале: <b>{n}</b>\n"
        f"Оборот (FunPay): <code>{sales:.2f}</code>\n"
        f"Закупка: <code>{cost:.2f}</code>\n"
        f"Чистыми (журнал): <code>{profit:.2f}</code>\n"
        f"Учебных (без закупки) записей: {dry}\n"
        f"Баланс FunPay: <code>{fp}</code>\n"
        f"Аварийный стоп: <b>{panic}</b> | Заморозка сессии: <b>{frozen}</b> | Учебный режим: <b>{dry_run}</b>\n"
        f"Тихий час: {quiet}\n"
        f"Комиссия FunPay: {load_ops().get('Ops', 'funpay_commission', fallback='0.03')}\n"
        f"Минимальный запас к закупке: <b>x{min_margin_mult():.1f}</b> (команда /margin)"
    )


def _auth_ok(cardinal, message) -> bool:
    tg = cardinal.telegram
    uid = message.from_user.id
    return uid in getattr(tg, "authorized_users", {}) or uid in getattr(tg, "authorized_users", [])


def init_post(cardinal):
    global _INSTALLED, _TG_CMDS
    bind_cardinal(cardinal)
    hydrate()
    logging_redact.install()
    if not _INSTALLED:
        if getattr(cardinal, "account", None) is not None:
            _install_watchdog(cardinal)
            Thread(target=_loop, args=(cardinal,), daemon=True).start()
            _INSTALLED = True

    tg = getattr(cardinal, "telegram", None)
    if not tg or not getattr(tg, "bot", None) or _TG_CMDS:
        return
    _TG_CMDS = True
    from shop_core.confirm import register_tg as register_confirm_buttons
    register_confirm_buttons(cardinal)

    def guard(m):
        return _auth_ok(cardinal, m)

    @tg.bot.message_handler(commands=["panic", "kill"])
    def cmd_panic(m):
        if not guard(m):
            return
        set_flag("Ops", "panic", "1")
        freeze("аварийный стоп", cardinal)
        tg.bot.send_message(
            m.chat.id,
            "🛑 Аварийный стоп: автозакупки и выдача остановлены.",
        )

    @tg.bot.message_handler(commands=["unpanic", "unkill"])
    def cmd_unpanic(m):
        if not guard(m):
            return
        set_flag("Ops", "panic", "0")
        unfreeze()
        tg.bot.send_message(m.chat.id, "▶️ Стоп снят. Бот снова в работе.")

    @tg.bot.message_handler(commands=["unfreeze"])
    def cmd_unfreeze(m):
        if not guard(m):
            return
        unfreeze()
        tg.bot.send_message(
            m.chat.id,
            "▶️ Заморозка сессии снята. Перед нагрузкой проверь golden_key.",
        )

    @tg.bot.message_handler(commands=["margin", "запас"])
    def cmd_margin(m):
        if not guard(m):
            return
        parts = (m.text or "").split()
        if len(parts) < 2:
            tg.bot.send_message(
                m.chat.id,
                f"Сейчас запас <b>x{min_margin_mult():.1f}</b>.\n"
                f"Поставщику заказ уйдёт, только если после комиссии FunPay "
                f"ты получишь минимум в столько раз больше, чем закупка.\n\n"
                f"Поставь: <code>/margin 2</code> … <code>/margin 10</code>\n"
                f"Панели — configs/suppliers.cfg. Сайты и чужие ТГ-боты бот сам не ищет.",
                parse_mode="HTML",
            )
            return
        try:
            v = float(parts[1].replace(",", "."))
        except ValueError:
            tg.bot.send_message(m.chat.id, "Напиши число. Пример: /margin 2")
            return
        v = min(10.0, max(1.0, v))
        set_flag("Ops", "min_margin_mult", str(v))
        tg.bot.send_message(m.chat.id, f"✅ Запас поставлен: <b>x{v:.1f}</b>", parse_mode="HTML")

    @tg.bot.message_handler(commands=["stats"])
    def cmd_stats(m):
        if not guard(m):
            return
        tg.bot.send_message(m.chat.id, _stats_text(cardinal), parse_mode="HTML")

    @tg.bot.message_handler(commands=["dryrun", "dry"])
    def cmd_dry(m):
        if not guard(m):
            return
        new = "0" if is_dry_run() else "1"
        set_flag("Ops", "dry_run", new)
        tg.bot.send_message(
            m.chat.id,
            "🧪 Учебный режим ВКЛ: поставщику ничего не уходит." if new == "1"
            else "🧪 Учебный режим ВЫКЛ: закупки настоящие.",
        )

    @tg.bot.message_handler(commands=["quiet"])
    def cmd_quiet(m):
        if not guard(m):
            return
        cfg = load_ops()
        cur = cfg.getboolean("Ops", "quiet_enabled", fallback=True)
        set_flag("Ops", "quiet_enabled", "0" if cur else "1")
        tg.bot.send_message(
            m.chat.id,
            "🌙 Тихие часы включены." if not cur else "🌙 Тихие часы выключены.",
        )

    SettingsPage(UUID, NAME, "Аварийный стоп, учебный режим, тихие часы.") \
        .add_toggle("dry_run", "Учебный режим (без закупок)", is_dry_run,
                    lambda v: set_flag("Ops", "dry_run", "1" if v else "0")) \
        .add_toggle("panic", "Аварийный стоп", is_panic,
                    lambda v: set_flag("Ops", "panic", "1" if v else "0")) \
        .add_toggle("quiet", "Тихие часы",
                    lambda: load_ops().getboolean("Ops", "quiet_enabled", fallback=True),
                    lambda v: set_flag("Ops", "quiet_enabled", "1" if v else "0")) \
        .set_status(lambda: _stats_text(cardinal)) \
        .attach(cardinal)

    @tg.bot.callback_query_handler(func=lambda c: (c.data or "").startswith("OPS:"))
    def cb_ops(c):
        if c.from_user.id not in getattr(tg, "authorized_users", {}):
            return
        parts = c.data.split(":")
        action, chat_id = parts[1], parts[2]
        if action == "human":
            mark_human(int(chat_id))
            tg.bot.answer_callback_query(c.id, "Чат у ИИ отобран")
        elif action == "ai":
            release_chat(int(chat_id))
            tg.bot.answer_callback_query(c.id, "ИИ снова может отвечать после закрытия заказа")


def on_new_message(cardinal, event):
    msg = getattr(event, "message", None)
    if not msg:
        return
    if getattr(msg, "author_id", None) == getattr(cardinal.account, "id", None) and not getattr(msg, "by_bot", False):
        if msg.chat_id:
            mark_human(msg.chat_id)


def on_order_status(cardinal, event):
    order = getattr(event, "order", None)
    if not order:
        return
    status = getattr(order, "status", None)
    chat_id = getattr(order, "chat_id", None)
    name = str(status).lower() if status is not None else ""
    if chat_id and any(x in name for x in ("closed", "refund", "CLOSED", "REFUNDED")):
        release_chat(chat_id)


BIND_TO_PRE_INIT = [init_post]
BIND_TO_POST_INIT = [init_post]
BIND_TO_NEW_MESSAGE = [on_new_message]
BIND_TO_ORDER_STATUS_CHANGED = [on_order_status]
