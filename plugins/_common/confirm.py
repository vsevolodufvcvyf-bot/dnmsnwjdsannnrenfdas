# -*- coding: utf-8 -*-
"""Подтверждение ника/ссылки в чате FunPay — как в ролике: спросил, сверил, выдал."""
from __future__ import annotations

import json
import logging
import re
import time

from plugins._common.bus import (
    STATE_WAITING_INPUT, bind_order_chat, bot_send, notify, peer_ids, release_chat,
    set_chat_mute, set_chat_state,
)
from plugins._common.db import get_db
from plugins._common.finance import claim_delivery, log_finance, preflight_or_abort, release_delivery, supplier_post
from plugins._common.panels import budget_panels, candidates_from_suppliers
from plugins._common.settings import is_dry_run

logger = logging.getLogger("FPC.Confirm")

_RESERVED_USERS = {
    "http", "https", "www", "funpay", "telegram", "stars", "gift", "admin",
    "support", "channel", "joinchat", "share", "addstickers", "proxy", "smm",
}
_STRICT_USER_RE = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{4,31})$")
_IN_TEXT_USER_RE = re.compile(r"(?:^|[\s(,;])@([A-Za-z][A-Za-z0-9_]{4,31})\b")
_TME_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z][A-Za-z0-9_]{4,31})\b", re.I)
_LINK_RE = re.compile(r"(https?://[^\s]+|t\.me/[^\s]+|@[A-Za-z][A-Za-z0-9_]{4,31})", re.I)
_YES = {
    "да", "yes", "верно", "ок", "ага", "точно", "подтверждаю", "+", "ok", "lf",
    "конечно", "согласен", "правильно", "угу", "даа",
}
_NO = {"нет", "no", "неверно", "не то", "ошибка", "-", "неправильно"}
_QTY_RE = re.compile(r"(\d{1,7})")


def _clean_username(name: str | None) -> str | None:
    if not name:
        return None
    if name.lower() in _RESERVED_USERS:
        return None
    return name


def parse_username(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    tme = _TME_RE.search(raw)
    if tme:
        cleaned = _clean_username(tme.group(1))
        if cleaned:
            return cleaned
    first = raw.split()[0]
    whole = _STRICT_USER_RE.match(first)
    if whole and (len(raw.split()) == 1 or first.startswith("@")):
        cleaned = _clean_username(whole.group(1))
        if cleaned:
            return cleaned
    in_text = _IN_TEXT_USER_RE.search(raw)
    if in_text:
        return _clean_username(in_text.group(1))
    return None


def parse_link(text: str) -> str | None:
    m = _LINK_RE.search(text or "")
    return m.group(0).rstrip(".,);") if m else None


_UNIT_QTY_RE = re.compile(
    r"(\d{1,6})\s*(?:зв[её]зд\w*|stars?|шт\b|штук\w*|подар\w*|gifts?|⭐)",
    re.IGNORECASE,
)
_AMOUNT_TAIL_RE = re.compile(r",\s*\d{1,6}\s*(?:шт|pcs)\.?\s*$", re.IGNORECASE)


def parse_qty(text: str, default: int = 1) -> int:
    amount = max(1, int(default or 1))
    text = _AMOUNT_TAIL_RE.sub("", (text or "").strip())
    unit = [int(x) for x in _UNIT_QTY_RE.findall(text or "") if int(x) > 0]
    if unit:
        return unit[0] * amount
    nums = [int(x) for x in _QTY_RE.findall(text or "") if int(x) > 0]
    if not nums:
        return amount
    nums.sort(reverse=True)
    for n in nums:
        if n not in (1,) or len(nums) == 1:
            return n
    return amount


def _reply_words(text: str) -> list[str]:
    raw = (text or "").strip().lower().replace("ё", "е")
    return re.findall(r"[a-zа-я0-9+]+", raw)


def is_yes(text: str) -> bool:
    words = _reply_words(text)
    if not words:
        return False
    if words[0] in _YES or "".join(words) in _YES:
        return True
    return False


def is_no(text: str) -> bool:
    words = _reply_words(text)
    if not words:
        return False
    if words[0] in _NO or "".join(words) in _NO:
        return True
    if len(words) >= 2 and words[0] == "не" and words[1] in {"то", "тот", "верно", "правильно", "надо"}:
        return True
    return False


def event_message(event):
    return getattr(event, "message", None)


def is_system_message(msg) -> bool:
    """Уведомления FunPay (оплата, отзыв) — не реплика покупателя."""
    if not msg:
        return True
    if getattr(msg, "author_id", None) == 0:
        return True
    mtype = getattr(msg, "type", None)
    if mtype is None:
        return False
    try:
        from FunPayAPI.common.enums import MessageTypes
        return mtype != MessageTypes.NON_SYSTEM
    except Exception:
        return False


def is_self_message(cardinal, msg) -> bool:
    if not msg:
        return True
    if is_system_message(msg):
        return True
    acc = getattr(cardinal, "account", None)
    my = getattr(acc, "id", None)
    if getattr(msg, "by_bot", False):
        return True
    if my and getattr(msg, "author_id", None) == my:
        return True
    return False


def _row_pending(row) -> dict:
    extra = {}
    try:
        extra = json.loads(row["extra"] or "{}")
    except Exception:
        extra = {}
    return {
        "chat_id": int(row["chat_id"]),
        "order_id": row["order_id"],
        "kind": row["kind"],
        "step": row["step"],
        "payload": row["payload"] or "",
        "qty": int(row["qty"] or 1),
        "sale": float(row["sale"] or 0),
        "extra": extra,
        "created_at": float(row["created_at"] or 0),
    }


def _pending_keys(chat_id, cardinal=None, msg=None, peer_id=None) -> list[int]:
    acc = getattr(cardinal, "account", None) if cardinal is not None else None
    aid = getattr(acc, "id", None)
    return peer_ids(
        peer_id,
        chat_id,
        getattr(msg, "chat_id", None) if msg is not None else None,
        getattr(msg, "author_id", None) if msg is not None else None,
        getattr(msg, "interlocutor_id", None) if msg is not None else None,
        account_id=aid,
    )


def put_pending(chat_id, order_id: str, kind: str, step: str, payload: str = "",
                qty: int = 1, sale: float = 0.0, extra: dict | None = None,
                cardinal=None, peer_id=None) -> str:
    """fail — чат не разобрали; active — этот заказ спрашиваем сейчас; queued — ждёт предыдущий."""
    acc = getattr(cardinal, "account", None) if cardinal is not None else None
    aid = getattr(acc, "id", None)
    extra = dict(extra or {})
    if chat_id is not None:
        extra.setdefault("node", str(chat_id))
    cid = bind_order_chat(chat_id, account_id=aid, peer_id=peer_id)
    if cid is None:
        logger.error("[Confirm] put_pending: chat_id=%r peer=%r", chat_id, peer_id)
        return "fail"
    oid = str(order_id)
    now = time.time()
    with get_db() as conn:
        prev = conn.execute(
            "SELECT created_at FROM pending_confirms WHERE chat_id = ? AND order_id = ?",
            (cid, oid),
        ).fetchone()
        created = float(prev["created_at"]) if prev and prev["created_at"] else now
        conn.execute(
            """INSERT OR REPLACE INTO pending_confirms
               (chat_id, order_id, kind, step, payload, qty, sale, extra, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cid, oid, kind, step, payload or "", int(qty), float(sale or 0),
             json.dumps(extra, ensure_ascii=False), created),
        )
        head = conn.execute(
            """SELECT order_id FROM pending_confirms
               WHERE chat_id = ? ORDER BY created_at ASC, order_id ASC LIMIT 1""",
            (cid,),
        ).fetchone()
    set_chat_state(cid, STATE_WAITING_INPUT, str(head["order_id"]) if head else oid, waiting=True)
    return "active" if head and head["order_id"] == oid else "queued"


def get_pending(chat_id, cardinal=None, msg=None, peer_id=None) -> dict | None:
    keys = _pending_keys(chat_id, cardinal=cardinal, msg=msg, peer_id=peer_id)
    if not keys:
        return None
    with get_db() as conn:
        q = ",".join("?" * len(keys))
        row = conn.execute(
            f"""SELECT * FROM pending_confirms WHERE chat_id IN ({q})
                ORDER BY created_at ASC, order_id ASC LIMIT 1""",
            tuple(keys),
        ).fetchone()
    return _row_pending(row) if row else None


def pop_pending(chat_id, cardinal=None, order_id: str | None = None) -> dict | None:
    """Снимает один заказ. Если в чате остался следующий — возвращает его и не отпускает диалог."""
    keys = _pending_keys(chat_id, cardinal=cardinal)
    if not keys:
        return None
    with get_db() as conn:
        q = ",".join("?" * len(keys))
        if order_id:
            conn.execute(
                f"DELETE FROM pending_confirms WHERE chat_id IN ({q}) AND order_id = ?",
                (*keys, str(order_id)),
            )
        else:
            row = conn.execute(
                f"""SELECT chat_id, order_id FROM pending_confirms WHERE chat_id IN ({q})
                    ORDER BY created_at ASC, order_id ASC LIMIT 1""",
                tuple(keys),
            ).fetchone()
            if row:
                conn.execute(
                    "DELETE FROM pending_confirms WHERE chat_id = ? AND order_id = ?",
                    (row["chat_id"], row["order_id"]),
                )
    nxt = get_pending(chat_id, cardinal=cardinal)
    if nxt:
        set_chat_state(nxt["chat_id"], STATE_WAITING_INPUT, nxt["order_id"], waiting=True)
        return nxt
    for key in keys:
        try:
            release_chat(key)
        except Exception:
            pass
    return None


def ask_queued(cardinal, chat_id, chat_name: str | None = None) -> None:
    bot_send(
        cardinal, chat_id,
        "Принял ещё один заказ. Сначала закроем предыдущий — ответь на него.",
        chat_name,
    )


def _ask_next(cardinal, chat_id, pending: dict, chat_name: str | None = None) -> None:
    kind = pending.get("kind") or ""
    payload = pending.get("payload") or ""
    if pending.get("step") == "confirm" and payload:
        ask_confirm(cardinal, chat_id, kind, payload, chat_name)
    else:
        ask_target(cardinal, chat_id, kind, chat_name)


def resume_pending(cardinal) -> int:
    """После снятия стопа: по каждому чату снова задаём вопрос по самому старому заказу."""
    from plugins._common.bus import is_frozen
    if cardinal is None or is_frozen():
        return 0
    now = time.time()
    with get_db() as conn:
        paused = conn.execute(
            "SELECT DISTINCT chat_id FROM pending_confirms WHERE extra LIKE '%\"paused\": 1%'"
        ).fetchall()
        chats = [int(r["chat_id"]) for r in paused]
        rows = []
        for cid in chats:
            row = conn.execute(
                """SELECT * FROM pending_confirms WHERE chat_id = ?
                   ORDER BY created_at ASC, order_id ASC LIMIT 1""",
                (cid,),
            ).fetchone()
            if row:
                rows.append(row)
            for r in conn.execute("SELECT order_id, extra FROM pending_confirms WHERE chat_id = ?", (cid,)).fetchall():
                try:
                    ex = json.loads(r["extra"] or "{}")
                except Exception:
                    ex = {}
                ex.pop("paused", None)
                ex["resumed_at"] = now
                conn.execute(
                    "UPDATE pending_confirms SET extra = ? WHERE chat_id = ? AND order_id = ?",
                    (json.dumps(ex, ensure_ascii=False), cid, r["order_id"]),
                )
    sent = 0
    for row in rows:
        pending = _row_pending(row)
        node = str((pending.get("extra") or {}).get("node") or "")
        target = int(node) if node.lstrip("-").isdigit() else (node or pending["chat_id"])
        try:
            bot_send(cardinal, target, "Продавец снова на связи, продолжаем заказ.")
            _ask_next(cardinal, target, pending)
            sent += 1
        except Exception as ex:
            logger.warning("[Confirm] resume #%s: %s", pending.get("order_id"), ex)
    if rows:
        notify(cardinal, f"▶️ Стоп снят: повторил вопрос покупателям в {sent} из {len(rows)} чатах.", True)
    return sent


def _panel_no_funds(res, data) -> bool:
    code = int(getattr(res, "status_code", 0) or 0)
    if code == 402:
        return True
    if not isinstance(data, dict):
        return False
    blob = str(data.get("error") or data.get("message") or "").lower()
    return any(part in blob for part in ("not enough", "insufficient", "no fund", "недостаточно"))


def ask_target(cardinal, chat_id, kind: str, chat_name: str | None = None) -> None:
    if kind == "stars":
        text = "Напиши Telegram-юзернейм, куда отправить звёзды. Например: @username"
    elif kind == "gift":
        text = "Напиши Telegram-юзернейм, кому отправить подарок. Например: @username"
    elif kind == "smm":
        text = "Напиши ссылку на цель (канал, пост или @username) — без неё накрутку не запускаем."
    elif kind == "steam":
        text = "Напиши логин Steam, который нужно пополнить."
    elif kind == "digital":
        text = "Напиши ссылку, логин или @username для выдачи — без этого закупку не запускаем."
    else:
        text = "Напиши данные для выдачи одним сообщением."
    bot_send(cardinal, chat_id, text, chat_name)


def ask_confirm(cardinal, chat_id, kind: str, payload: str, chat_name: str | None = None) -> None:
    if kind == "stars":
        text = f"Звёзды уйдут на @{payload.lstrip('@')}. Верно? Напиши да или нет."
    elif kind == "gift":
        text = f"Подарок уйдёт на @{payload.lstrip('@')}. Верно? Напиши да или нет."
    elif kind == "smm":
        text = f"Накрутка пойдёт на {payload}. Верно? Напиши да или нет."
    elif kind == "steam":
        text = f"Пополняю Steam-логин «{payload}». Верно? Напиши да или нет."
    elif kind == "digital":
        text = f"Выдача пойдёт на {payload}. Верно? Напиши да или нет."
    else:
        text = f"Данные: {payload}. Верно? Напиши да или нет."
    bot_send(cardinal, chat_id, text, chat_name)


def _panel_retryable(ex: Exception) -> bool:
    """Сеть оборвалась до ответа. Таймаут чтения не повторяем: заказ на первой панели уже мог создаться."""
    try:
        import requests
    except Exception:
        return False
    return isinstance(ex, requests.ConnectionError)


def deliver_via_panel(cardinal, kind: str, order_id: str, chat_id, payload: str,
                      qty: int, sale: float, query: str, chat_name: str | None = None,
                      section: str | None = None, service_id: str | None = None) -> str:
    plugin = {
        "stars": "autostars", "gift": "autogift", "smm": "autosmm",
        "steam": "steam_wallet", "digital": "digital",
    }.get(kind, kind)
    cands = candidates_from_suppliers(query)
    if kind == "smm":
        cands = [c for c in cands if "smm" in (c.get("section") or "").lower() or c.get("plugin_name") == "autosmm"]
        try:
            from plugins.autosmm import smm_panel_candidates
            cands.extend(smm_panel_candidates(service_id))
        except Exception as ex:
            logger.debug("[Confirm] autosmm.cfg: %s", ex)
    elif kind == "stars":
        cands = [c for c in cands if "star" in (c.get("section") or "").lower() or "звезд" in (c.get("keywords") or "").lower()]
        if not cands:
            cands = candidates_from_suppliers("telegram stars")
    elif kind == "gift":
        cands = [c for c in cands if "gift" in (c.get("section") or "").lower() or "подар" in (c.get("keywords") or "").lower()]
        if not cands:
            cands = candidates_from_suppliers("telegram gift подарок")
    if section:
        wanted = str(section).split("/")[0]
        narrowed = [c for c in cands if str(c.get("section") or "").split("/")[0] == wanted]
        if narrowed:
            cands = narrowed
    fitting, why = budget_panels(cands, sale, qty) if cands else ([], "Нет панели с ключом.")
    if not fitting:
        return "hold"
    best = fitting[0]
    if not claim_delivery(str(order_id), plugin):
        bot_send(cardinal, chat_id, "Этот заказ уже закупается, подожди немного.", chat_name)
        return "busy"
    cost = float(best.get("_cost") or 0)
    ok, pre = preflight_or_abort(cardinal, order_id, plugin)
    if not ok and pre != "dry_run":
        release_delivery(str(order_id), plugin)
        if pre in ("freeze", "panic"):
            bot_send(cardinal, chat_id, "Выдача на паузе. Продавец на связи и доделает заказ, данные сохранены.", chat_name)
            notify(cardinal, f"⏸ {plugin} #{order_id}: покупатель подтвердил, но стоит {pre}. Цель: <code>{payload}</code>", True)
            return "paused"
        if pre == "network":
            bot_send(cardinal, chat_id, "FunPay не ответил при проверке оплаты. Напиши да ещё раз через минуту.", chat_name)
        else:
            bot_send(cardinal, chat_id, "Заказ пока не в статусе «оплачен». Напиши да ещё раз через минуту.", chat_name)
        return "fail"
    if is_dry_run() or pre == "dry_run":
        log_finance(order_id, plugin, sale, cost)
        bot_send(
            cardinal, chat_id,
            "Заказ записан. Сейчас учебный режим — поставщику ничего не уходило. Продавец выдаст вручную.",
            chat_name,
        )
        notify(cardinal, f"🧪 {plugin} #{order_id} → {payload} qty={qty}\n{why}", False)
        return "ok"
    import requests
    last_error = "поставщик не ответил"
    for idx, panel in enumerate(fitting):
        service_id = str(panel.get("service_id") or "").strip()
        if not service_id:
            last_error = f"нет service_id в [{panel.get('name')}]"
            continue
        link_field = str(panel.get("field_link") or "link").strip() or "link"
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", link_field):
            link_field = "link"
        payload_req = {
            "key": panel["api_key"], "action": "add",
            "service": service_id, "quantity": int(qty),
            link_field: payload,
        }
        try:
            res = supplier_post(requests.post, panel["api_url"], payload_req, timeout=15.0)
            try:
                data = res.json()
            except Exception:
                data = {}
            code = int(getattr(res, "status_code", 0) or 0)
            if code in (502, 503, 504):
                last_error = f"HTTP {code}"
                logger.warning("[%s] panel %s HTTP %s", plugin, panel.get("name"), code)
                if idx + 1 < len(fitting):
                    notify(
                        cardinal,
                        f"↪️ {plugin} #{order_id}: «{panel.get('name')}» ответила {code}, пробую следующую панель.",
                        True,
                    )
                    continue
                break
        except Exception as ex:
            last_error = str(ex)[:240]
            logger.warning("[%s] panel add: %s", plugin, ex)
            if _panel_retryable(ex) and idx + 1 < len(fitting):
                notify(
                    cardinal,
                    f"↪️ {plugin} #{order_id}: «{panel.get('name')}» недоступна, пробую следующую панель.",
                    True,
                )
                continue
            break
        task = str((data or {}).get("order") or "") if isinstance(data, dict) else ""
        if task:
            with get_db() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO supplier_orders
                       (order_id, plugin_name, provider, task_id, status, created_at)
                       VALUES (?, ?, ?, ?, 'success', ?)""",
                    (str(order_id), plugin, panel.get("section"), task, time.time()),
                )
            log_finance(order_id, plugin, sale, float(panel.get("_cost") or cost))
            bot_send(cardinal, chat_id, f"Готово, заказ у поставщика. Номер задачи: #{task}", chat_name)
            notify(cardinal, f"✅ {plugin} #{order_id} → <code>{payload}</code> qty={qty} task #{task}", False)
            return "ok"
        if _panel_no_funds(res, data):
            last_error = str(data)[:240]
            logger.warning("[%s] no funds on %s", plugin, panel.get("name"))
            if idx + 1 < len(fitting):
                notify(
                    cardinal,
                    f"↪️ {plugin} #{order_id}: на «{panel.get('name')}» нет баланса, пробую следующую панель.",
                    True,
                )
                continue
            break
        last_error = str(data)[:240]
        break
    release_delivery(str(order_id), plugin)
    notify(cardinal, f"❌ {plugin} #{order_id}: {last_error}", True)
    bot_send(cardinal, chat_id, "Поставщик не принял заказ. Напиши да ещё раз или подожди продавца.", chat_name)
    return "fail"


_TOKEN_USER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


def parse_username_reply(text: str) -> str | None:
    """Ответ покупателя: «мой ник super_seller» — одно слово-ник, без @.
    В названии лота так не ищем, там остаётся строгий parse_username.
    """
    found = parse_username(text)
    if found:
        return found
    got = []
    for raw in re.split(r"[\s,;:]+", text or ""):
        token = raw.strip(".,!?()[]«»\"'@")
        if not _TOKEN_USER.fullmatch(token):
            continue
        if token.lower() in _RESERVED_USERS:
            continue
        if token.lower() not in {x.lower() for x in got}:
            got.append(token)
    return got[0] if len(got) == 1 else None


def _explicit_correction(kind: str, text: str) -> str | None:
    """Новая цель только если покупатель явно прислал @ник, t.me или ссылку."""
    raw = (text or "").strip()
    if not raw:
        return None
    if kind in ("stars", "gift"):
        tme = _TME_RE.search(raw)
        if tme:
            return _clean_username(tme.group(1))
        mentioned = _IN_TEXT_USER_RE.search(raw)
        if mentioned:
            return _clean_username(mentioned.group(1))
        if raw.startswith("@"):
            return parse_username(raw)
        return None
    if kind == "steam":
        named = re.search(r"(?:логин|login)\s*[:=]?\s*(\S+)", raw, re.I)
        return named.group(1).strip(".,)") if named else None
    return parse_link(raw)


def _parse_target(kind: str, text: str):
    if kind in ("stars", "gift"):
        return parse_username_reply(text)
    if kind == "steam":
        tok = (text or "").strip().split()
        return tok[0] if tok else None
    if kind in ("digital", "smm"):
        return parse_link(text) or parse_username(text)
    return parse_link(text)


def handle_pending_message(cardinal, event, kinds: set[str]) -> bool:
    msg = event_message(event)
    if is_self_message(cardinal, msg):
        return False
    chat_id = getattr(msg, "chat_id", None)
    if chat_id is None:
        return False
    pending = get_pending(chat_id, cardinal=cardinal, msg=msg)
    if not pending or pending.get("kind") not in kinds:
        return False
    bind_order_chat(chat_id, peer_id=pending.get("chat_id"))
    bind_order_chat(getattr(msg, "author_id", None), peer_id=pending.get("chat_id"))
    started = max(
        float(pending.get("created_at") or 0),
        float((pending.get("extra") or {}).get("resumed_at") or 0),
    )
    if time.time() - started > 3600 * 6:
        nxt = pop_pending(chat_id, cardinal, pending.get("order_id"))
        notify(
            cardinal,
            f"⌛ {pending.get('kind')} #{pending.get('order_id')}: подтверждение висело больше 6 часов, снял очередь.\n"
            f"Цель: <code>{pending.get('payload') or '—'}</code>. Выдай вручную или напиши покупателю.",
            True,
        )
        bot_send(
            cardinal, chat_id,
            f"Запрос по заказу #{pending.get('order_id')} закрыт по времени. Напиши продавцу — он доделает вручную.",
            getattr(msg, "chat_name", None),
        )
        if nxt:
            _ask_next(cardinal, chat_id, nxt, getattr(msg, "chat_name", None))
        return True
    text = (getattr(msg, "text", None) or "").strip()
    if not text:
        return True
    kind = pending["kind"]
    name = getattr(msg, "chat_name", None)
    extra = pending.get("extra") or {}
    owner = pending["chat_id"]

    def keep(step: str, value: str = "") -> None:
        put_pending(
            chat_id, pending["order_id"], kind, step, value,
            pending["qty"], pending["sale"], extra, cardinal=cardinal, peer_id=owner,
        )

    if pending["step"] == "need_target":
        parsed = _parse_target(kind, text)
        if not parsed:
            ask_target(cardinal, chat_id, kind, name)
            return True
        keep("confirm", parsed)
        ask_confirm(cardinal, chat_id, kind, parsed, name)
        return True
    if pending["step"] == "confirm":
        if is_no(text):
            keep("need_target")
            ask_target(cardinal, chat_id, kind, name)
            return True
        corrected = _explicit_correction(kind, text)
        current = str(pending.get("payload") or "").lstrip("@").lower()
        if corrected and corrected.lstrip("@").lower() != current:
            keep("confirm", corrected)
            ask_confirm(cardinal, chat_id, kind, corrected, name)
            return True
        if is_yes(text):
            payload = pending["payload"]
        else:
            bot_send(cardinal, chat_id, "Напиши да или нет. Если ник другой — пришли его с @.", name)
            return True
        query = extra.get("query") or kind
        result = deliver_via_panel(
            cardinal, kind, pending["order_id"], chat_id, str(payload).lstrip("@"),
            pending["qty"], pending["sale"], query, name,
            section=extra.get("target_section"),
            service_id=extra.get("service_id"),
        )
        if result == "ok":
            nxt = pop_pending(chat_id, cardinal, pending["order_id"])
            try:
                set_chat_mute(chat_id, 90)
            except Exception:
                pass
            if nxt:
                _ask_next(cardinal, chat_id, nxt, name)
        elif result == "hold":
            last = float(extra.get("hold_at") or 0)
            if time.time() - last > 900:
                extra["hold_at"] = time.time()
                notify(
                    cardinal,
                    f"⚠️ {kind} #{pending['order_id']}: панель не готова (нет ключа или себестоимости).\n"
                    f"Цель: <code>{payload}</code>",
                    True,
                )
                bot_send(
                    cardinal, chat_id,
                    "Заказ принят. Продавец сейчас подключит выдачу — данные уже есть.",
                    name,
                )
            keep("confirm", str(payload))
        elif result == "paused":
            extra["paused"] = 1
            keep("confirm", str(payload))
        elif result == "fail":
            keep("confirm", str(payload))
        return True
    return False
