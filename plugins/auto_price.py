# -*- coding: utf-8 -*-
"""Автоцена: подгоняет лоты под рынок, чтобы быстрее купили, но только в плюс. Микролоты не трогает."""
from __future__ import annotations

import html
import logging
import os
import time
from threading import Thread

from FunPayAPI.common.enums import SubCategoryTypes
from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, CallbackQuery, Message

from shop_core.bus import freeze, is_frozen, notify
from shop_core.db import get_db
from shop_core.panels import candidates_from_suppliers, min_sale_for_cost, quote_block
from shop_core.pricing import coef_from, seller_price_for  # noqa: F401  (используются и в тестах)
from shop_core.plugin_settings import SettingsPage
from shop_core.settings import ini_bool, is_dry_run, is_panic, load_ini, min_margin_mult, set_ini

logger = logging.getLogger("FPC.AutoPrice")

NAME = "Автоцена"
VERSION = "1.0.0"
DESCRIPTION = "Сам смотрит витрину категории и двигает цену, чтобы купили быстрее. В минус не уходит. Микролоты 1–10 ₽ не трогает."
CREDITS = "nnanserShop"
UUID = "c4e8a012-9b3f-4d27-a81c-6e5f4d3c2b10"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}
CONFIG_FILE = "configs/autoprice.cfg"
_READY = False
_LAST: list[str] = []
_LAST_AT = 0.0
PINNED_DEFAULTS = {
    "pinned_hold": "1",
    "pinned_raise_pct": "0",
    "pinned_max_over_median_pct": "10",
}


def _cfg():
    cfg = load_ini(CONFIG_FILE)
    if not cfg.has_section("AutoPrice"):
        cfg.add_section("AutoPrice")
        cfg.set("AutoPrice", "enabled", "1")
        cfg.set("AutoPrice", "interval_sec", "1800")
        cfg.set("AutoPrice", "undercut", "1")
        cfg.set("AutoPrice", "max_drop_pct", "25")
        cfg.set("AutoPrice", "min_delta", "1")
        cfg.set("AutoPrice", "notify", "1")
        cfg.set("AutoPrice", "skip_seller_ids", "")
    changed = False
    for key, value in PINNED_DEFAULTS.items():
        if not cfg.has_option("AutoPrice", key):
            cfg.set("AutoPrice", key, value)
            changed = True
    if not cfg.has_section("MinPrice"):
        cfg.add_section("MinPrice")
        changed = True
    if changed or not os.path.exists(CONFIG_FILE):
        from shop_core.settings import save_ini
        save_ini(CONFIG_FILE, cfg)
    return cfg["AutoPrice"]


def _ok(cardinal, uid: int) -> bool:
    tg = getattr(cardinal, "telegram", None)
    return bool(tg) and uid in getattr(tg, "authorized_users", {})


def _enabled() -> bool:
    return ini_bool(CONFIG_FILE, "AutoPrice", "enabled", True)


def _lot_text(lot) -> str:
    return " ".join(filter(None, [
        getattr(lot, "description", None) or getattr(lot, "title", None) or "",
        getattr(lot, "server", None) or "",
        getattr(lot, "side", None) or "",
    ]))


def _is_micro(lot) -> bool:
    try:
        from plugins.micro_lots import is_micro_lot
        price = float(getattr(lot, "price", 0) or 0)
        return is_micro_lot(_lot_text(lot), price)
    except Exception:
        title = (_lot_text(lot) or "").lower()
        price = float(getattr(lot, "price", 0) or 0)
        return price <= 12 and any(k in title for k in ("фишки", "гайд", "инструк", "совет", "покупателю"))


def _unit_cost(desc: str) -> float:
    cands = candidates_from_suppliers(desc)
    costs = []
    for c in cands:
        try:
            cost = float(quote_block(c, 1) or 0)
        except Exception:
            cost = float(c.get("cost_per_unit") or 0)
        if cost > 0:
            costs.append(cost)
    return min(costs) if costs else 0.0


def _nice(p: float) -> float:
    if p >= 20:
        return float(max(1, round(p)))
    return round(max(0.01, p), 2)


def _anchor(lot_id, current: float) -> float:
    """Первая увиденная цена лота. Пол 50% считается от неё, а не от уже сниженной."""
    try:
        lid = int(lot_id)
    except (TypeError, ValueError):
        return current
    if current <= 0:
        return current
    with get_db() as conn:
        row = conn.execute(
            "SELECT base_price FROM lot_price_anchor WHERE lot_id = ?", (lid,)
        ).fetchone()
        if row and float(row["base_price"] or 0) > 0:
            base = float(row["base_price"])
            if current > base + 0.009:
                conn.execute(
                    "UPDATE lot_price_anchor SET base_price = ? WHERE lot_id = ?",
                    (current, lid),
                )
                return current
            return base
        conn.execute(
            "INSERT INTO lot_price_anchor (lot_id, base_price, created_at) VALUES (?, ?, ?)",
            (lid, current, time.time()),
        )
    return current


def _min_price(lot_id) -> float:
    cfg = load_ini(CONFIG_FILE)
    if not cfg.has_section("MinPrice"):
        return 0.0
    try:
        return float(cfg.get("MinPrice", str(lot_id), fallback="0") or 0)
    except ValueError:
        return 0.0


def _floor(lot) -> tuple[float, str]:
    """Минимум цены для покупателя, ниже которого продажа уже не в плюс.

    Раньше сюда подмешивалась min_price_with_commission из calc(): это цена покупателя
    за лот в 1000 ₽, а не минимум раздела, и дешёвые лоты «поднимались» до ~1000 ₽.
    """
    desc = _lot_text(lot)
    cost = _unit_cost(desc)
    notes = []
    if cost > 0:
        floor = min_sale_for_cost(cost)
        notes.append(f"закупка {cost:.2f} → пол x{min_margin_mult():.1f} = {floor:.2f}")
    else:
        cur = float(getattr(lot, "price", 0) or 0)
        anchor = _anchor(getattr(lot, "id", None), cur)
        floor = anchor * 0.5 if anchor else 0.0
        notes.append("себестоимости нет — не ниже 50% первой цены")
    explicit = _min_price(getattr(lot, "id", ""))
    if explicit > 0:
        floor = max(floor, explicit)
        notes.append(f"минимум из [MinPrice] = {explicit:.2f}")
    return max(0.01, floor), "; ".join(notes)


def is_pinned(public_lots, lot_id) -> bool:
    lid = str(lot_id)
    for item in public_lots or []:
        if str(getattr(item, "id", "")) == lid:
            return bool(getattr(item, "promo", False))
    return False


def _target(current: float, stats: dict, floor: float, undercut: float, max_drop_pct: float,
            pinned: bool = False, raise_pct: float = 0.0, max_over_med_pct: float = 10.0,
            min_delta: float = 1.0) -> tuple[float, str]:
    cheapest = float(stats.get("cheapest") or 0)
    live_med = float(stats.get("live_med") or stats.get("med") or 0)
    q1 = float(stats.get("q1") or 0)
    n = int(stats.get("n") or 0)
    if pinned:
        if raise_pct > 0 and live_med > 0:
            cap = live_med * (1.0 + max(0.0, max_over_med_pct) / 100.0)
            aim = min(current * (1.0 + raise_pct / 100.0), cap)
            if aim - current >= min_delta:
                return _nice(aim), f"лот в закрепе — поднимаю к рынку (не выше {cap:.0f})"
        return current, "лот в закрепе — цену не снижаю"
    if n <= 0:
        return current, "на витрине нет чужих цен — не трогаю"

    aim = cheapest - undercut if cheapest > 0 else live_med
    if live_med and aim > live_med:
        aim = live_med
    if q1 and aim < q1 * 0.85:
        aim = q1 * 0.85
    if aim <= 0:
        aim = current

    cap_drop = current * (1.0 - max(0.0, min(max_drop_pct, 80.0)) / 100.0)
    if aim < cap_drop:
        aim = cap_drop

    if aim < floor:
        aim = floor
        why = f"рынок {cheapest:.0f}, но пол плюса {floor:.0f}"
    elif current <= cheapest and current >= floor:
        return current, f"уже среди самых дешёвых ({cheapest:.0f}), в плюсе"
    else:
        why = f"рынок от {cheapest:.0f}, живые ~ {live_med:.0f}"

    aim = _nice(aim)
    if aim < floor:
        aim = _nice(floor)
    return aim, why


def _apply(cardinal, lot, new_price: float, coef: float | None = None) -> float:
    """new_price — цена для покупателя. В форму лота пишется цена без комиссии."""
    acc = cardinal.account
    fields = acc.get_lot_fields(int(lot.id))
    k = coef or coef_from(getattr(fields, "calc_result", None))
    if not k:
        raise ValueError("не знаю комиссию раздела — цену не трогаю")
    fields.price = seller_price_for(new_price, k)
    acc.save_lot(fields)
    return fields.price


def _log_row(lot_id, title, old, new, floor, market_min, reason, dry: int) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO autoprice_log
               (lot_id, title, old_price, new_price, floor_price, market_min, reason, dry_run, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (int(lot_id), title[:120], old, new, floor, market_min, reason[:240], dry, time.time()),
        )


_PINNED_SEEN: dict[str, str] = {}


def _note_pinned(cardinal, lot) -> None:
    """Раз в день сообщает, что лот попал в закреп: тут выгоднее держать или поднимать цену."""
    from datetime import datetime
    day = datetime.now().strftime("%Y-%m-%d")
    key = str(getattr(lot, "id", ""))
    if _PINNED_SEEN.get(key) == day:
        return
    _PINNED_SEEN[key] = day
    title = html.escape((getattr(lot, "description", None) or f"#{key}")[:60])
    notify(cardinal, f"🔝 Лот «{title}» в закрепе. Автоцена его не снижает "
                     f"(поднимать понемногу: pinned_raise_pct в configs/autoprice.cfg).", False)


def run_once(cardinal) -> list[str]:
    """Возвращает строки изменений. Пусто — молчим."""
    global _LAST, _LAST_AT
    out: list[str] = []
    if not _enabled() or is_panic() or is_frozen():
        return out
    profile = getattr(cardinal, "profile", None) or getattr(cardinal, "curr_profile", None)
    acc = getattr(cardinal, "account", None)
    if not profile or not acc:
        return out
    try:
        ours = list((profile.get_sorted_lots(1) or {}).values())
    except Exception as ex:
        logger.debug("[AutoPrice] lots: %s", ex)
        return out

    cfg = _cfg()
    undercut = float(cfg.get("undercut", 1) or 1)
    max_drop = float(cfg.get("max_drop_pct", 25) or 25)
    min_delta = float(cfg.get("min_delta", 1) or 1)
    our_id = getattr(acc, "id", None)
    skip_ids = set()
    if our_id:
        skip_ids.add(int(our_id))
    for part in str(cfg.get("skip_seller_ids", "") or "").replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            skip_ids.add(int(part))
    dry = is_dry_run()
    pinned_hold = str(cfg.get("pinned_hold", "1")).strip() not in ("0", "false", "False")
    raise_pct = float(cfg.get("pinned_raise_pct", 0) or 0)
    max_over_med = float(cfg.get("pinned_max_over_median_pct", 10) or 10)
    public: dict[int, list] = {}
    coefs: dict[int, float | None] = {}

    from plugins.market_analyzer import market_stats

    skipped_micro = 0
    for lot in ours:
        if is_frozen() or is_panic():
            break
        sub = getattr(lot, "subcategory", None)
        if not sub or getattr(sub, "type", None) is SubCategoryTypes.CURRENCY:
            continue
        if _is_micro(lot):
            skipped_micro += 1
            continue
        try:
            current = float(getattr(lot, "price", 0) or 0)
        except (TypeError, ValueError):
            continue
        if current <= 0:
            continue
        sub_id = int(sub.id)
        query = _lot_text(lot)
        try:
            if sub_id not in public:
                public[sub_id] = acc.get_subcategory_public_lots(SubCategoryTypes.COMMON, sub_id) or []
                time.sleep(1.2)
            stats = market_stats(
                cardinal, sub_id, query, exclude_seller_id=our_id,
                lots=public[sub_id], exclude_seller_ids=skip_ids,
            )
        except Exception as ex:
            logger.debug("[AutoPrice] market %s: %s", sub_id, ex)
            continue

        if sub_id not in coefs:
            try:
                coefs[sub_id] = coef_from(acc.calc(SubCategoryTypes.COMMON, sub_id))
                time.sleep(0.4)
            except Exception as ex:
                err = str(ex).lower()
                if "401" in err or "403" in err or "captcha" in err or "unauthorized" in err:
                    freeze(f"автоцена calc: {ex}", cardinal)
                    break
                logger.debug("[AutoPrice] calc %s: %s", sub_id, ex)
                coefs[sub_id] = None

        pinned = pinned_hold and is_pinned(public.get(sub_id), lot.id)
        if pinned:
            _note_pinned(cardinal, lot)
        floor, floor_why = _floor(lot)
        target, why = _target(current, stats, floor, undercut, max_drop, pinned=pinned,
                              raise_pct=raise_pct, max_over_med_pct=max_over_med, min_delta=min_delta)
        title = html.escape((getattr(lot, "description", None) or f"#{lot.id}")[:48])
        if abs(target - current) < min_delta:
            continue
        if dry:
            out.append(f"🧪 {title}: {current:.0f} → {target:.0f} ₽ ({html.escape(why)})")
            _log_row(lot.id, getattr(lot, "description", "") or "", current, target, floor, stats.get("cheapest") or 0, why, 1)
            continue
        try:
            written = _apply(cardinal, lot, target, coefs.get(sub_id))
            lot.price = target
            out.append(f"• {title}: <code>{current:.0f}</code> → <b>{target:.0f}</b> ₽ · {html.escape(why)}")
            _log_row(lot.id, getattr(lot, "description", "") or "", current, target, floor, stats.get("cheapest") or 0, why, 0)
            logger.info("[AutoPrice] #%s %s → %s (в форме %s; %s / %s)", lot.id, current, target, written, why, floor_why)
            time.sleep(3.5)
        except Exception as ex:
            err = str(ex).lower()
            if "401" in err or "403" in err or "captcha" in err or "unauthorized" in err:
                freeze(f"автоцена save: {ex}", cardinal)
                break
            logger.warning("[AutoPrice] save #%s: %s", lot.id, ex)
            out.append(f"• {title}: не сохранил ({html.escape(str(ex)[:80])})")

    if skipped_micro and out:
        out.append(f"Микролоты не трогал: {skipped_micro} шт.")
    _LAST = out
    _LAST_AT = time.time()
    return out


def hub_text(cardinal) -> str:
    on = _enabled()
    cfg = _cfg()
    lines = [
        "⚖️ <b>Автоцена</b>",
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
        "Смотрит чужие лоты в той же категории и двигает твою цену, чтобы купили быстрее.",
        "Ниже пола плюса (закупка × запас после комиссии FunPay) не опустит.",
        "Микролоты 1–10 ₽ (фишки / гайды / инструкции) <b>не трогает</b>.",
        "Лот в закрепе не снижает (поднимать понемногу — <code>pinned_raise_pct</code>).",
        "Свой минимум на лот: секция <code>[MinPrice]</code>, строка <code>ID_лота = цена</code>.",
        "",
        f"Сейчас: <b>{'вкл' if on else 'выкл'}</b>",
        f"Шаг вниз к рынку: <code>{cfg.get('undercut', '1')}</code> ₽ · макс. −{cfg.get('max_drop_pct', '25')}% за раз",
        f"Интервал: {int(float(cfg.get('interval_sec', 1800) or 1800) / 60)} мин.",
    ]
    if is_dry_run():
        lines.append("🧪 Учебный режим: цены на FunPay не меняются, только отчёт.")
    if _LAST:
        ago = int(time.time() - _LAST_AT) // 60 if _LAST_AT else 0
        lines.append("")
        lines.append(f"<b>Последний проход</b> ({ago} мин назад)")
        lines.extend(_LAST[:12])
    else:
        lines.append("")
        lines.append("Проходов с изменениями ещё не было. Нажми «Прогнать сейчас» после того, как лоты висят на FunPay.")
    return "\n".join(lines)


def hub_kb() -> K:
    kb = K()
    on = _enabled()
    kb.row(
        B("⏸ Выкл" if on else "▶️ Вкл", callback_data="APR:tog"),
        B("🔄 Прогнать сейчас", callback_data="APR:run"),
    )
    kb.row(B("📈 Цена вручную", callback_data="PANEL:price"), B("📝 Микролоты", callback_data="MICRO:hub"))
    kb.row(B("🏠 Главная", callback_data="PANEL:home"))
    return kb


def init_settings(cardinal):
    SettingsPage(UUID, NAME, "Автоподгон цены под рынок. Микролоты не трогает. В минус не уходит.") \
        .add_toggle("enabled", "Автоцена", _enabled, lambda _v: set_ini(CONFIG_FILE, "AutoPrice", "enabled", "0" if _enabled() else "1")) \
        .set_status(lambda: hub_text(cardinal)[:1500]) \
        .attach(cardinal)
    cardinal.add_telegram_commands(UUID, [("aprice", "автоцена рынка", True)])


def init_pre(cardinal):
    global _READY
    _cfg()
    init_settings(cardinal)
    tg = getattr(cardinal, "telegram", None)
    if not tg or not getattr(tg, "bot", None) or _READY:
        return
    _READY = True
    bot = tg.bot

    @bot.message_handler(commands=["aprice", "автоцена"])
    def cmd(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        bot.send_message(m.chat.id, hub_text(cardinal), reply_markup=hub_kb(), parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("APR:"))
    def cb(c: CallbackQuery):
        if not _ok(cardinal, c.from_user.id):
            return
        action = (c.data or "").split(":")[1] if ":" in (c.data or "") else "hub"
        try:
            bot.answer_callback_query(c.id)
        except Exception:
            logger.debug("TRACEBACK", exc_info=True)
        if action == "tog":
            set_ini(CONFIG_FILE, "AutoPrice", "enabled", "0" if _enabled() else "1")
        elif action == "run":
            if is_panic() or is_frozen():
                bot.send_message(c.message.chat.id, "Сначала сними стоп / заморозку.")
                return
            bot.send_message(c.message.chat.id, "⚖️ Смотрю витрину, это минута…")
            try:
                rows = run_once(cardinal)
            except Exception as ex:
                bot.send_message(c.message.chat.id, f"Не смог: {html.escape(str(ex)[:200])}")
                return
            if not rows:
                bot.send_message(c.message.chat.id, "Цены уже ок или лотов нет. Микролоты не трогал.")
                return
            if _cfg().get("notify", "1") not in ("0", "false", "False") and len(rows) > 1:
                notify(cardinal, "⚖️ <b>Автоцена</b>\n" + "\n".join(rows[:15]), False)
            bot.send_message(c.message.chat.id, hub_text(cardinal), reply_markup=hub_kb(), parse_mode="HTML")
            return
        bot.send_message(c.message.chat.id, hub_text(cardinal), reply_markup=hub_kb(), parse_mode="HTML")


def _loop(cardinal):
    time.sleep(80)
    while True:
        try:
            cfg = _cfg()
            interval = max(300, int(float(cfg.get("interval_sec", 1800) or 1800)))
            if _enabled() and not is_panic() and not is_frozen():
                rows = run_once(cardinal)
                if rows and cfg.get("notify", "1") not in ("0", "false", "False") and not is_dry_run():
                    notify(cardinal, "⚖️ <b>Автоцена</b>\n" + "\n".join(rows[:15]), False)
        except Exception as ex:
            logger.debug("[AutoPrice] loop: %s", ex)
        try:
            interval = max(300, int(float(_cfg().get("interval_sec", 1800) or 1800)))
        except Exception:
            interval = 1800
        time.sleep(interval)


def init_post(cardinal):
    Thread(target=_loop, args=(cardinal,), daemon=True).start()


BIND_TO_PRE_INIT = [init_pre]
BIND_TO_POST_START = [init_post]
