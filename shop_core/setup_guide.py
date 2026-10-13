# -*- coding: utf-8 -*-
"""Пошаговый мастер Steam и Robux в Telegram.

Лот на FunPay бот не публикует и автовыдачу не включает. Контракт чужой панели не выдумывается:
продавец сам пишет, что у него считается одной единицей.
"""
from __future__ import annotations

import time

from shop_core.db import get_db
from shop_core.panels import min_sale_for_cost, normalize_supplier_url
from shop_core.settings import commission, min_margin_mult

PANEL_STEPS = ("intro", "where", "url", "key", "service", "unit", "cost", "floor", "lot", "enable", "done")
FILE_STEPS = ("file", "bind", "done")
TEXT_STEPS = {"url", "key", "service", "cost", "floor"}
GUIDED = {("steam", "panel"), ("robux", "gamepass")}
FILED = {("steam", "file"), ("robux", "file")}
UNITS = {
    "unit_rub": "1 ₽ номинала",
    "unit_usd": "1 $ номинала",
    "unit_piece": "1 штука (1 робукс или 1 единица услуги)",
    "unit_pack": "весь пакет одной услугой, в лоте количество 1",
}


def preset_for(kind: str, method: str) -> str | None:
    if (kind, method) == ("steam", "panel"):
        return "steam_wallet"
    if (kind, method) == ("robux", "gamepass"):
        return "robux"
    return None


def begin(user_id: int, kind: str, method: str) -> dict:
    """Начинает или продолжает мастер за последние сутки. Панель создаётся выключенной."""
    if (kind, method) not in GUIDED and (kind, method) not in FILED:
        raise ValueError("эту схему мастер не ведёт")
    now = time.time()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM setup_wizard WHERE user_id = ?", (int(user_id),)).fetchone()
        if row and row["kind"] == kind and row["method"] == method and row["step"] != "done":
            if now - float(row["updated_at"] or 0) < 86400:
                return dict(row)
        section = None
        step = "file" if (kind, method) in FILED else "intro"
        if (kind, method) in GUIDED:
            from shop_core.panels import apply_preset, next_section_name
            preset = preset_for(kind, method) or "other"
            section = next_section_name(preset)
            apply_preset(section, preset)
        conn.execute(
            """INSERT OR REPLACE INTO setup_wizard (user_id, kind, method, section, step, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (int(user_id), kind, method, section, step, now),
        )
    return load(user_id) or {}


def load(user_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM setup_wizard WHERE user_id = ?", (int(user_id),)).fetchone()
    return dict(row) if row else None


def stop(user_id: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM setup_wizard WHERE user_id = ?", (int(user_id),))


def _save_step(user_id: int, step: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE setup_wizard SET step = ?, updated_at = ? WHERE user_id = ?",
            (step, time.time(), int(user_id)),
        )


def _steps(run: dict) -> tuple[str, ...]:
    if (run["kind"], run["method"]) in FILED:
        return FILE_STEPS
    return PANEL_STEPS


def _goto(run: dict, step: str) -> str:
    steps = _steps(run)
    if step not in steps:
        return run["step"]
    return step


def _next_step(run: dict) -> str:
    steps = _steps(run)
    try:
        i = steps.index(run["step"])
    except ValueError:
        return steps[0]
    if i + 1 >= len(steps):
        return steps[-1]
    return steps[i + 1]


def price_advice(unit_cost: float, buyer_price: float | None = None) -> tuple[bool, str]:
    """True — цена покупателя не ниже пола либо цены ещё нет."""
    cost = float(unit_cost or 0)
    if cost <= 0:
        return False, "Себестоимость не задана."
    floor = min_sale_for_cost(cost)
    fee = commission() * 100
    need = min_margin_mult()
    lines = [
        f"Закупка 1 единицы: <code>{cost:.2f}</code> ₽.",
        f"Комиссия в расчёте: <code>{fee:.1f}%</code> из настроек магазина. "
        "Если у раздела FunPay комиссия другая, пол будет выше — живой коэффициент бот здесь не угадывает.",
        f"Чтобы запас был x{need:.1f}, покупатель платит не меньше <b>{floor:.2f}</b> ₽ за эту единицу.",
    ]
    if buyer_price is None:
        lines.append("Пришли свою цену для покупателя числом — проверю. Или нажми «Дальше», если пол уже понятен.")
        return True, "\n".join(lines)
    buyer = float(buyer_price)
    if buyer + 1e-9 < floor:
        lines.append(
            f"Цена <code>{buyer:.2f}</code> ₽ ниже пола. При ней закупка <b>не уйдёт</b>."
        )
        return False, "\n".join(lines)
    net = buyer * (1.0 - commission())
    mult = net / cost if cost else 0
    lines.append(
        f"При цене <code>{buyer:.2f}</code> ₽ на руки около <code>{net:.2f}</code> ₽, запас x{mult:.2f}."
    )
    return True, "\n".join(lines)


def apply_text(user_id: int, text: str) -> tuple[bool, str, bool]:
    """Принимает ответ продавца. Возвращает ok, текст экрана, нужно ли удалить сообщение (ключ)."""
    run = load(user_id)
    if not run:
        return False, "Мастер не запущен. Открой «Схемы» и нажми «Шаги».", False
    step = run["step"]
    raw = (text or "").strip()
    section = run.get("section") or ""
    if step == "url":
        url = normalize_supplier_url(raw)
        if not url:
            return False, "Нужен адрес API своей панели, например <code>https://домен/api/v2</code>. Это не FunPay и не store.steampowered.com.", False
        from shop_core.panels import save_supplier_section
        save_supplier_section(section, {"api_url": url}, create=False)
        _save_step(user_id, "key")
        return True, screen(load(user_id)), False
    if step == "key":
        if len(raw) < 8 or any(ch.isspace() for ch in raw):
            return False, "Ключ пришли одним словом из кабинета панели, без пробелов.", False
        from shop_core.panels import mask_secret, save_supplier_section
        save_supplier_section(section, {"api_key": raw}, create=False)
        _save_step(user_id, "service")
        return True, "Ключ записал, в чате его больше не показываю.\n\n" + screen(load(user_id)), True
    if step == "service":
        if not raw.isdigit() or len(raw) > 12:
            return False, "service_id — число из прайса твоей панели. Я не знаю, какой номер у какой услуги: его видно только в твоём кабинете.", False
        from shop_core.panels import save_supplier_section
        save_supplier_section(section, {"service_id": raw}, create=False)
        _save_step(user_id, "unit")
        return True, screen(load(user_id)), False
    if step == "cost":
        try:
            cost = float(raw.replace(",", ".").replace(" ", ""))
        except ValueError:
            return False, "Напиши себестоимость 1 единицы в рублях, например <code>1.35</code>.", False
        if cost <= 0:
            return False, "Себестоимость должна быть больше нуля, иначе плюс не посчитать.", False
        from shop_core.panels import save_supplier_section
        save_supplier_section(section, {"cost_per_unit": f"{cost:.4f}".rstrip("0").rstrip(".")}, create=False)
        _save_step(user_id, "floor")
        return True, screen(load(user_id)), False
    if step == "floor":
        try:
            buyer = float(raw.replace(",", ".").replace(" ", "").replace("₽", ""))
        except ValueError:
            return False, "Пришли цену для покупателя числом или нажми «Дальше».", False
        from shop_core.panels import load_suppliers_cfg
        cfg = load_suppliers_cfg()
        cost = float(cfg[section].get("cost_per_unit", "0") or 0) if cfg.has_section(section) else 0
        ok, advice = price_advice(cost, buyer)
        if not ok:
            return False, advice, False
        _save_step(user_id, "lot")
        return True, advice + "\n\n" + screen(load(user_id)), False
    return False, "Сейчас жду кнопку, не текст.", False


def apply_action(user_id: int, action: str) -> tuple[bool, str]:
    run = load(user_id)
    if not run:
        return False, "Мастер не запущен."
    if action == "stop":
        stop(user_id)
        return True, "Мастер закрыт. Черновик панели, если он уже создан, остаётся выключенным. Автовыдачу я не трогал."
    if action in UNITS:
        if run["step"] != "unit":
            return False, screen(run)
        from shop_core.panels import save_supplier_section
        save_supplier_section(run["section"], {"unit_meaning": UNITS[action]}, create=False)
        _save_step(user_id, "cost")
        return True, screen(load(user_id))
    if action == "enable":
        if run["step"] != "enable" or not run.get("section"):
            return False, screen(run)
        from shop_core.panels import save_supplier_section
        save_supplier_section(run["section"], {"enabled": "1"}, create=False)
        _save_step(user_id, "done")
        return True, screen(load(user_id))
    if action == "leave":
        if run["step"] != "enable":
            return False, screen(run)
        _save_step(user_id, "done")
        return True, "Панель оставил выключенной.\n\n" + screen(load(user_id))
    if action == "next":
        step = run["step"]
        if step in TEXT_STEPS and step != "floor":
            return False, "Сначала пришли то, что просит этот шаг."
        if step == "floor":
            nxt = "lot"
        else:
            nxt = _next_step(run)
        _save_step(user_id, nxt)
        return True, screen(load(user_id))
    return False, screen(run)


def expects_text(run: dict | None) -> bool:
    return bool(run and run.get("step") in TEXT_STEPS)


def screen(run: dict | None) -> str:
    if not run:
        return "Мастер не запущен."
    step = run["step"]
    kind = run["kind"]
    title = "Steam — пополнение" if kind == "steam" else "Robux — Game Pass"
    if step == "file":
        return (
            f"▶️ <b>{title}, ключи в файле</b>\n"
            "1. Один код — одна строка в файле <code>storage/products/имя.txt</code>.\n"
            "2. Это твои коды, не чужие аккаунты.\n"
            "3. Панель и закупка тут не нужны: когда строки кончатся, бот сам ничего не купит.\n"
            "Дальше — как связать файл с лотом. Автовыдачу я сам не включаю."
        )
    if step == "bind":
        return (
            "▶️ <b>Связать файл с лотом</b>\n"
            "1. На FunPay создай лот сам, в своей категории.\n"
            "2. В пульте Cardinal открой «Автовыдача» и привяжи этот лот к файлу. Тумблер автовыдачи включаешь ты.\n"
            "3. В описании не проси отзыв, не обещай скидку и не оставляй телеграм.\n"
            "4. Цену поставь выше того, за сколько ты купил коды, с запасом на комиссию."
        )
    if step == "intro":
        ban = (
            "Steam Store картой из бота не оплачиваем."
            if kind == "steam"
            else "Чужие аккаунты Roblox не продаём и не выдаём."
        )
        return (
            f"▶️ <b>{title}</b>\n"
            "Шаг 1 из мастера. Я веду по твоей панели, лот на FunPay сам не создаю.\n"
            f"{ban}\n"
            "Закупка уйдёт только после «да» покупателя и только если цена даёт запас x"
            f"{min_margin_mult():.1f}."
        )
    if step == "where":
        return (
            "▶️ <b>Где взять панель</b>\n"
            "1. Открой кабинет своей панели-посредника (не сайт FunPay и не магазин Steam/Roblox).\n"
            "2. Раздел API или Developers.\n"
            "3. Скопируй адрес API, обычно он кончается на <code>/api/v2</code>, и ключ.\n"
            "Чужие витрины я не ищу. Если панели нет — мастер дальше не пройдёт, закупать будет некуда."
        )
    if step == "url":
        return (
            "▶️ <b>Адрес API</b>\n"
            "Пришли URL одним сообщением.\n"
            "Пример вида: <code>https://домен-твоей-панели/api/v2</code>."
        )
    if step == "key":
        return (
            "▶️ <b>Ключ API</b>\n"
            "Пришли ключ одним сообщением. Я удалю это сообщение и в переписке оставлю только маску."
        )
    if step == "service":
        what = "пополнения Steam" if kind == "steam" else "Game Pass / Robux"
        return (
            f"▶️ <b>Номер услуги {what}</b>\n"
            "В прайсе панели найди услугу и пришли её <code>service_id</code> — это число.\n"
            "Какой номер к какой игре относится, знает только прайс твоей панели. Я его не угадываю."
        )
    if step == "unit":
        return (
            "▶️ <b>Что такое 1 единица</b>\n"
            "Панели считают по-разному. Выбери, что означает один вызов этой услуги.\n"
            "От этого зависит, с какой ценой лот будет в плюсе."
        )
    if step == "cost":
        unit = _unit(run)
        return (
            "▶️ <b>Себестоимость</b>\n"
            f"Сколько рублей ты платишь панели за одну единицу ({unit})?\n"
            "Пример: <code>1.35</code>"
        )
    if step == "floor":
        from shop_core.panels import load_suppliers_cfg
        cfg = load_suppliers_cfg()
        section = run.get("section") or ""
        cost = float(cfg[section].get("cost_per_unit", "0") or 0) if cfg.has_section(section) else 0
        _ok, advice = price_advice(cost, None)
        return "▶️ <b>Пол цены</b>\n" + advice
    if step == "lot":
        return _lot_text(run)
    if step == "enable":
        return (
            "▶️ <b>Включить панель</b>\n"
            "Пока она выключена, заказы на неё не уходят.\n"
            "Автовыдача FunPay при этом не включается. Её по-прежнему переключаешь только ты."
        )
    if step == "done":
        from shop_core.panels import load_suppliers_cfg, mask_secret
        cfg = load_suppliers_cfg()
        section = run.get("section") or ""
        on = "включена" if cfg.has_section(section) and cfg[section].getboolean("enabled", fallback=False) else "выключена"
        key = mask_secret(cfg[section].get("api_key", "") if cfg.has_section(section) else "")
        return (
            f"✅ <b>Мастер закончен</b>\n"
            f"Панель <code>{section or '—'}</code> {on}. Ключ: {key}.\n"
            "Дальше жди заказ: бот спросит данные у покупателя и закупит только после «да» и проверки запаса."
        )
    return "Неизвестный шаг. Нажми «Схемы» и начни снова."


def buttons(run: dict | None) -> list[tuple[str, str]]:
    if not run:
        return [("К схемам", "stop")]
    step = run["step"]
    if step in ("intro", "where", "file", "bind"):
        return [("Дальше", "next"), ("Закрыть", "stop")]
    if step == "unit":
        return [
            ("1 ₽ номинала", "unit_rub"),
            ("1 $ номинала", "unit_usd"),
            ("1 штука", "unit_piece"),
            ("Весь пакет", "unit_pack"),
            ("Закрыть", "stop"),
        ]
    if step == "floor":
        return [("Дальше", "next"), ("Закрыть", "stop")]
    if step == "lot":
        return [("Лот создал сам", "next"), ("Закрыть", "stop")]
    if step == "enable":
        return [("Включить панель", "enable"), ("Оставить выключенной", "leave")]
    if step == "done":
        return [("К схемам", "stop")]
    if step in TEXT_STEPS:
        return [("Закрыть", "stop")]
    return [("Дальше", "next"), ("Закрыть", "stop")]


def _unit(run: dict) -> str:
    from shop_core.panels import load_suppliers_cfg
    cfg = load_suppliers_cfg()
    section = run.get("section") or ""
    if cfg.has_section(section):
        meaning = (cfg[section].get("unit_meaning") or "").strip()
        if meaning:
            return meaning
    return "как ты выберешь на следующем шаге" if run.get("step") == "unit" else "единица услуги"


def _lot_text(run: dict) -> str:
    from shop_core.panels import load_suppliers_cfg
    cfg = load_suppliers_cfg()
    section = run.get("section") or ""
    words = cfg[section].get("keywords", "") if cfg.has_section(section) else ""
    if run["kind"] == "steam":
        buyer = "после оплаты покупатель пишет логин Steam в чат заказа. Пароль не проси."
    else:
        buyer = (
            "после оплаты покупатель пишет ник Roblox. Пароль не проси. "
            "Если твоя панель требует, чтобы у покупателя уже был создан Game Pass на нужную цену, "
            "напиши это в описании своими словами. Сам Game Pass бот не создаёт: контракт панели этого шага не описывает."
        )
    return (
        "▶️ <b>Лот на FunPay — руками</b>\n"
        "1. Открой FunPay → свои лоты → добавить лот в ту категорию, которая у тебя реально открыта. Номер категории я не подставляю.\n"
        f"2. В названии должны быть слова: <code>{words or '—'}</code>\n"
        f"3. В описании: {buyer} Отзыв, скидку и «пиши в телеграм» не пиши.\n"
        "4. Цена для покупателя — не ниже пола с прошлого шага. В форму лота FunPay пишется цена без комиссии раздела; точный коэффициент раздела бот подставит только там, где уже вызывает calc().\n"
        "5. Автовыдачу на этот лот не включай: заказ заберёт бот в чате после слова «да»."
    )
