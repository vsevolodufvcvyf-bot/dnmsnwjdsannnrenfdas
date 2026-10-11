# -*- coding: utf-8 -*-
"""Панели поставщиков, которые продавец сам прописал. Чужие сайты и ТГ-боты не ищем."""
from __future__ import annotations

import configparser
import logging
import os
import time
from html import escape
from typing import Any

import requests

from shop_core.finance import supplier_post
from shop_core.settings import commission, min_margin_mult, usd_rub

logger = logging.getLogger("FPC.Panels")
SUPPLIERS_FILE = os.path.join("configs", "suppliers.cfg")
PRESETS: dict[str, dict[str, str]] = {
    "smm": {
        "plugin_name": "autosmm",
        "keywords": "накрут, подписчик, лайк, просмотр, smm",
        "field_link": "link",
    },
    "stars": {
        "plugin_name": "autostars",
        "keywords": "telegram stars, звезды телеграм, tg stars, телеграм стар",
        "field_link": "link",
    },
    "gifts": {
        "plugin_name": "autogift",
        "keywords": "подарок, gift, teddy, медведь, trophy",
        "field_link": "link",
    },
    "steam_wallet": {
        "plugin_name": "steam_wallet",
        "keywords": "steam wallet, стим кошелек, пополнен стим, пополнение steam",
        "field_link": "link",
    },
    "robux": {
        "plugin_name": "robux",
        "keywords": "робукс, robux, gamepass",
        "field_link": "link",
    },
    "other": {
        "plugin_name": "digital",
        "keywords": "",
        "field_link": "link",
    },
}


def net_from_sale(sale: float) -> float:
    return float(sale or 0) * (1.0 - commission())


def max_cost_allowed(sale: float) -> float:
    m = min_margin_mult()
    net = net_from_sale(sale)
    if m <= 0:
        return net
    return net / m


_LIVE_CACHE: dict[tuple[str, str], tuple[float, float]] = {}
_LIVE_TTL = 12 * 60


def live_unit_cost_rub(url: str, key: str, service_id: str, fetch: bool = True) -> float | None:
    """Цена 1 шт. в рублях по action=services (rate обычно $ за 1000)."""
    if not url or not key or not service_id:
        return None
    cache_key = (url.rstrip("/"), str(service_id).strip())
    hit = _LIVE_CACHE.get(cache_key)
    if hit and time.time() - hit[0] < _LIVE_TTL:
        return hit[1]
    if not fetch:
        return None
    try:
        res = supplier_post(
            requests.post, url,
            {"key": key, "action": "services"},
            timeout=10.0,
        )
        items = res.json()
        if not isinstance(items, list):
            return None
        sid = str(service_id).strip()
        fx = usd_rub()
        for it in items:
            if not isinstance(it, dict):
                continue
            if str(it.get("service", "")).strip() != sid:
                continue
            rate = float(it.get("rate") or 0)
            if rate <= 0:
                return None
            value = (rate / 1000.0) * fx
            _LIVE_CACHE[cache_key] = (time.time(), value)
            return value
    except Exception as ex:
        logger.debug("[Panels] services %s: %s", url, ex)
        return None
    return None


def quote_block(block, quantity: int, fetch_live: bool = True) -> float:
    qty = max(1, int(quantity or 1))
    fallback = float(block.get("cost_per_unit", 0) or 0) * qty
    live = live_unit_cost_rub(
        block.get("api_url", ""),
        block.get("api_key", ""),
        str(block.get("service_id", "") or ""),
        fetch=fetch_live,
    )
    if live is not None and live > 0:
        live_total = live * qty
        if fallback > 0:
            return max(live_total, fallback)
        return live_total
    return fallback


def candidates_from_suppliers(desc: str, kinds: set[str] | None = None) -> list[dict[str, Any]]:
    import configparser
    import os
    path = "configs/suppliers.cfg"
    cfg = configparser.ConfigParser()
    if os.path.exists(path):
        cfg.read(path, encoding="utf-8")
    hay = (desc or "").lower()
    kinds_l = {k.lower() for k in (kinds or set())}
    out: list[dict[str, Any]] = []
    for section in cfg.sections():
        block = cfg[section]
        if not block.getboolean("enabled", fallback=False):
            continue
        pname = (block.get("plugin_name") or section).strip()
        blob = f"{section} {pname}".lower()
        if kinds_l and not any(k in blob for k in kinds_l):
            continue
        kws = [k.strip().lower() for k in block.get("keywords", "").split(",") if k.strip()]
        if hay and kws and not any(k in hay for k in kws):
            continue
        cand = {
            "name": section,
            "api_url": block.get("api_url", "").strip(),
            "api_key": block.get("api_key", "").strip(),
            "service_id": block.get("service_id", "").strip(),
            "cost_per_unit": block.get("cost_per_unit", "0"),
            "fallback_api_url": block.get("fallback_api_url", "").strip(),
            "fallback_api_key": block.get("fallback_api_key", "").strip(),
            "plugin_name": pname,
            "section": section,
            "field_link": (block.get("field_link") or "link").strip() or "link",
            "keywords": block.get("keywords", ""),
            "services": block.get("services", ""),
        }
        if not cand["api_url"] or not cand["api_key"]:
            continue
        out.append(cand)
        if cand["fallback_api_url"] and cand["fallback_api_key"]:
            d2 = dict(cand)
            d2["name"] = section + "/запас"
            d2["api_url"] = cand["fallback_api_url"]
            d2["api_key"] = cand["fallback_api_key"]
            d2["fallback_api_url"] = ""
            out.append(d2)
    return out


def _priced(candidates: list[dict[str, Any]], sale: float, quantity: int = 1,
            fetch_live: bool = True) -> tuple[list[tuple[float, dict]], list[str], float, float]:
    qty = max(1, int(quantity or 1))
    net = net_from_sale(sale)
    cap = max_cost_allowed(sale)
    priced: list[tuple[float, dict]] = []
    notes = []
    for c in candidates:
        name = c.get("name") or "панель"
        try:
            cost = quote_block(c, qty, fetch_live=fetch_live)
        except Exception:
            cost = float(c.get("cost_per_unit", 0) or 0) * qty
        if cost <= 0:
            notes.append(f"{name}: нет цены (пропиши cost_per_unit или service_id)")
            continue
        mult = (net / cost) if cost else 0
        priced.append((cost, c | {"_cost": cost, "_mult": mult}))
        notes.append(f"{name}: закупка {cost:.2f} ₽ → x{mult:.2f}")
    priced.sort(key=lambda x: x[0])
    return priced, notes, net, cap


def pick_cheapest(candidates: list[dict[str, Any]], sale: float, quantity: int = 1,
                  fetch_live: bool = True) -> tuple[dict | None, str]:
    """
    Из списка панелей (каждая — dict с url/key/service_id/cost_per_unit/name)
    берёт самую дешёвую, которая оставляет запас min_margin_mult.
    Меню Telegram вызывает с fetch_live=False, чтобы не ждать панель.
    """
    priced, notes, net, cap = _priced(candidates, sale, quantity, fetch_live=fetch_live)
    need_mult = min_margin_mult()
    if not priced:
        return None, "Нет панелей с ценой. Пропиши api_url, api_key, service_id и cost_per_unit в configs/suppliers.cfg."
    for cost, c in priced:
        if cost <= cap + 1e-9:
            return c, (
                f"Взял {c.get('name')}: закупка {cost:.2f} ₽, "
                f"ты получишь {net:.2f} ₽ (x{c.get('_mult', 0):.2f}, минимум x{need_mult:.1f}).\n"
                + "\n".join(notes)
            )
    cheapest = priced[0][1]
    return None, (
        f"Ни одна панель не даёт x{need_mult:.1f}. "
        f"С продажи останется {net:.2f} ₽, закупка должна быть ≤ {cap:.2f} ₽.\n"
        + "\n".join(notes)
        + f"\nСамая дешёвая сейчас: {cheapest.get('name')} за {cheapest.get('_cost', 0):.2f} ₽."
    )


def budget_panels(candidates: list[dict[str, Any]], sale: float, quantity: int = 1) -> tuple[list[dict], str]:
    """Панели в запасе маржи, от дешёвой к дорогой. Пустой список — hold."""
    priced, notes, _net, cap = _priced(candidates, sale, quantity, fetch_live=True)
    fit = [c for cost, c in priced if cost <= cap + 1e-9]
    return fit, "\n".join(notes)


def min_sale_for_cost(cost: float) -> float:
    """Минимальная цена лота на FunPay, чтобы после комиссии остался запас x min_margin_mult."""
    cost = float(cost or 0)
    if cost <= 0:
        return 0.0
    comm = commission()
    if comm >= 1:
        return cost * min_margin_mult()
    return (cost * min_margin_mult()) / (1.0 - comm)


def normalize_supplier_url(raw: str) -> str | None:
    text = (raw or "").strip().strip("`\"'")
    if not text or any(ch.isspace() for ch in text):
        return None
    if "://" not in text:
        text = "https://" + text
    scheme, _, rest = text.partition("://")
    if scheme.lower() not in ("http", "https") or not rest or "." not in rest.split("/")[0]:
        return None
    return text.rstrip("/")


def mask_secret(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "нет"
    if len(raw) <= 6:
        return "••••"
    return f"{raw[:3]}…{raw[-2:]}"


def load_suppliers_cfg() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if os.path.exists(SUPPLIERS_FILE):
        cfg.read(SUPPLIERS_FILE, encoding="utf-8")
    return cfg


def save_suppliers_cfg(cfg: configparser.ConfigParser) -> None:
    os.makedirs(os.path.dirname(SUPPLIERS_FILE) or ".", exist_ok=True)
    with open(SUPPLIERS_FILE, "w", encoding="utf-8") as f:
        cfg.write(f)


def save_supplier_section(section: str, updates: dict[str, Any], create: bool = True) -> None:
    name = (section or "").strip()
    if not name:
        raise ValueError("пустое имя панели")
    cfg = load_suppliers_cfg()
    if not cfg.has_section(name):
        if not create:
            raise KeyError(name)
        cfg.add_section(name)
        cfg.set(name, "enabled", "0")
        cfg.set(name, "plugin_name", "digital")
        cfg.set(name, "keywords", "")
        cfg.set(name, "api_url", "")
        cfg.set(name, "api_key", "")
        cfg.set(name, "fallback_api_url", "")
        cfg.set(name, "fallback_api_key", "")
        cfg.set(name, "service_id", "")
        cfg.set(name, "cost_per_unit", "0")
        cfg.set(name, "field_link", "link")
    for key, value in (updates or {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            cfg.set(name, key, "1" if value else "0")
        else:
            cfg.set(name, key, str(value).strip())
    save_suppliers_cfg(cfg)


def next_section_name(kind: str) -> str:
    kind = (kind or "other").strip() or "other"
    cfg = load_suppliers_cfg()
    names = [kind] + [f"{kind}_{i}" for i in range(2, 31)]
    for name in names:
        if not cfg.has_section(name):
            return name
        if not (cfg[name].get("api_key") or "").strip():
            return name
    return f"{kind}_new"


def apply_preset(section: str, kind: str) -> None:
    preset = PRESETS.get(kind) or PRESETS["other"]
    save_supplier_section(section, {
        "plugin_name": preset["plugin_name"],
        "keywords": preset["keywords"],
        "field_link": preset.get("field_link", "link"),
        "enabled": "0",
    }, create=True)


def panel_has_key(section: str) -> bool:
    cfg = load_suppliers_cfg()
    if not cfg.has_section(section):
        return False
    return bool((cfg[section].get("api_key") or "").strip())


def panels_overview() -> str:
    cfg = load_suppliers_cfg()
    if not cfg.sections():
        return "Пока ни одной панели. Нажми «добавить» и вставь URL + ключ."
    lines = []
    for section in cfg.sections():
        b = cfg[section]
        on = b.getboolean("enabled", fallback=False)
        key = (b.get("api_key") or "").strip()
        url = (b.get("api_url") or "").strip()
        sid = (b.get("service_id") or "").strip()
        mark = "🟢" if on and key else ("🟡" if key else "⚪")
        host = url.split("/")[2] if "://" in url else (url or "нет URL")
        lines.append(
            f"{mark} <b>{escape(section)}</b> · ключ {mask_secret(key)}"
            f" · {escape(host[:40])} · id {escape(sid or '—')}"
        )
    return "\n".join(lines)


def test_panel(section: str) -> str:
    cfg = load_suppliers_cfg()
    if not cfg.has_section(section):
        return "Такой панели нет."
    b = cfg[section]
    url = (b.get("api_url") or "").strip()
    key = (b.get("api_key") or "").strip()
    if not url or not key:
        return "Сначала пропиши URL и ключ."
    try:
        res = supplier_post(
            requests.post, url,
            {"key": key, "action": "balance"},
            timeout=8.0,
        )
        try:
            data = res.json()
        except Exception:
            return f"Ответ не JSON (HTTP {getattr(res, 'status_code', '?')}). Проверь URL."
        if isinstance(data, dict):
            bal = data.get("balance", data.get("Balance"))
            cur = data.get("currency") or data.get("Currency") or ""
            err = data.get("error") or data.get("message")
            if bal is not None:
                return f"Панель ответила. Баланс: <code>{escape(str(bal))}</code> {escape(str(cur))}"
            if err:
                return f"Панель ответила ошибкой: {escape(str(err)[:180])}"
            keys = ", ".join(escape(str(k)) for k in list(data.keys())[:8])
            return f"Панель ответила (поля: {keys}). Ключ, похоже, принят."
        return f"Странный ответ, HTTP {getattr(res, 'status_code', '?')}."
    except Exception as ex:
        return f"Не достучался: {escape(str(ex)[:180])}"


def margin_report(query: str, sale: float, qty: int = 1) -> str:
    """Блок «твои панели vs цена FunPay» — без ключей, только цифры."""
    cands = candidates_from_suppliers(query)
    lines = ["", "💼 <b>Твои панели</b>"]
    if not cands:
        lines.append(
            "Под этот товар нет включённой панели с URL и ключом.\n"
            "На главной: «🔌 Панель» — мастер спросит адрес и ключ. Сайты и чужие ТГ-боты сам не ищу."
        )
        return "\n".join(lines)
    best, why = pick_cheapest(cands, sale, qty)
    lines.append(escape(why))
    if best:
        cost = float(best.get("_cost") or 0)
        floor = min_sale_for_cost(cost / max(1, qty)) if qty else min_sale_for_cost(cost)
        if qty:
            floor_pack = min_sale_for_cost(cost)
            if sale + 1e-9 < floor_pack:
                lines.append(
                    f"\n⚠️ При цене рынка <code>{sale:.2f}</code> запас меньше x{min_margin_mult():.1f}. "
                    f"Чтобы закупка ушла, лот должен быть от <code>{floor_pack:.2f}</code> "
                    f"(или найди панель дешевле)."
                )
            else:
                lines.append(
                    f"\n✅ При ставке <code>{sale:.2f}</code> запас проходит "
                    f"(минимум лота для x{min_margin_mult():.1f}: ≈ <code>{floor_pack:.2f}</code>)."
                )
        _ = floor
    return "\n".join(lines)
