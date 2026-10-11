# -*- coding: utf-8 -*-
"""Микролоты 5–10 ₽: реальные короткие гайды. Закупка 0, после комиссии FunPay ~97% чистыми."""
from __future__ import annotations

import logging
import os

from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, CallbackQuery, Message

from shop_core.plugin_settings import SettingsPage

logger = logging.getLogger("FPC.MicroLots")

NAME = "Микролоты 5–10 ₽"
VERSION = "1.0.0"
DESCRIPTION = "Готовые текстовые фишки/инструкции. Себестоимость 0. Не просим отзыв в чате."
CREDITS = "nnanserShop"
UUID = "e2f56a91-8c5d-4e3a-ab27-4d9f1c6e7890"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}
_READY = False

CATALOG = {
    "guides_cs2.txt": (
        "CS2 фишки",
        [
            "CS2: перед раундом купи flash+smoke, не весь магазин. Экономика важнее одного фрага.",
            "CS2: звук шагов громче на лестнице — там не беги, если не уверен.",
            "CS2: смоук кидай не в дверь, а на угол, чтобы себе оставить пик.",
            "CS2: AWP на пыли — стой ближе к коробке, не на открытой линии.",
            "CS2: после планта ставь молли не на бомбу, а на выход, откуда идут.",
            "CS2: не стреляй в смоук «на удачу» — отдаёшь позицию.",
            "CS2: в eco раунде один человек с force — остальные сейвят.",
            "CS2: на Mirage palace не стой в одной точке два раунда подряд.",
            "CS2: килл не подтверждай выходом — сначала проверь угол.",
            "CS2: микрофон коротко: позиция, сколько, кто с утилитой.",
        ],
    ),
    "guides_steam.txt": (
        "Steam фишки",
        [
            "Steam: семейный просмотр библиотеки — Steam → Друзья → Семейный доступ.",
            "Steam: оффлайн-режим: Steam → Перейти в автономный режим, потом запускай игру.",
            "Steam: скрыть игры: ПКМ по игре → Управление → Скрыть эту игру.",
            "Steam: код Guard обновляется каждые 30 сек. Не скринь старый.",
            "Steam: регион магазина меняется в аккаунте, не чаще чем раз в несколько месяцев.",
            "Steam: облачные сохранения: настройки игры → Обновления → Steam Cloud.",
            "Steam: если игра не запускается — проверь файлы: свойства → установленные файлы.",
            "Steam: wishlist: ПКМ по игре в магазине → Добавить в список желаемого.",
            "Steam: скриншоты: F12 в оверлее (Shift+Tab).",
            "Steam: не вводи Guard в сторонних сайтах — только в клиенте Steam.",
        ],
    ),
    "guides_roblox.txt": (
        "Roblox фишки",
        [
            "Roblox: не вводи пароль в «бесплатные робуксы» — это фишинг.",
            "Roblox: 2FA в настройках аккаунта сильно режет угон.",
            "Roblox: Game Pass покупается на странице опыта, не с чужих ссылок.",
            "Roblox: пинг высокий — закрой загрузки и VPN, проверь регион сервера.",
            "Roblox: инвентарь ограниченного предмета не дари случайным людям.",
            "Roblox: смена почты только со старого ящика, иначе аккаунт в риск.",
            "Roblox: не шарь .ROBLOSECURITY cookie — это полный вход.",
            "Roblox: графика: Esc → Settings → Graphics Mode Manual.",
            "Roblox: приватный сервер — для друзей без рандома.",
            "Roblox: если робуксы не пришли — проверь History в Creator Hub, не сторонние боты.",
        ],
    ),
    "guides_valorant.txt": (
        "Valorant фишки",
        [
            "Valorant: не стреляй в смоук — отдаёшь позицию и патроны.",
            "Valorant: флеш кидай от стены, не в открытую линию.",
            "Valorant: Jett dash — не в центр сайта, а за укрытие.",
            "Valorant: Sage wall ставь не на вход, а на угол пика.",
            "Valorant: в eco не покупай шилды, если нет винтовки.",
            "Valorant: звук шагов громче по металлу — там не беги.",
            "Valorant: орб на миду не бери один, если тима не прикрывает.",
            "Valorant: ult Sova стреляй после флеша, не до него.",
            "Valorant: не дуэлься с Operator на открытой длинной.",
            "Valorant: комс коротко: сайт, сколько, кто с ультой.",
        ],
    ),
    "guides_dota.txt": (
        "Dota 2 фишки",
        [
            "Dota 2: варды на руны перед 6:00 экономят тонну смертей.",
            "Dota 2: не денай свой лес, если саппорт уже пустой.",
            "Dota 2: TP на тотем не жми в драке — сначала блинк/форс.",
            "Dota 2: байбэк не жми, если твой ульт ещё 40+ сек.",
            "Dota 2: смок не кидай в вижен врага — сначала девард.",
            "Dota 2: рошан с 20:00 — смотри чей аегис важнее, не таймер.",
            "Dota 2: саппорт: таунты не в лицо керри, а на отход.",
            "Dota 2: клик по герою в табе — видишь предметы до файта.",
            "Dota 2: курьер не води через мид после 10 минуты.",
            "Dota 2: стак кемпа в :53–:55, не в :00.",
        ],
    ),
    "guides_minecraft.txt": (
        "Minecraft фишки",
        [
            "Minecraft: кровать не ставь в Незере — взорвёт и тебя.",
            "Minecraft: вода+ведро тушат лаву быстрее ведра пустого.",
            "Minecraft: F3+B — хитбоксы, видно куда бить эндермена.",
            "Minecraft: тотем в левой руке, еда в хотбаре 9 слот.",
            "Minecraft: портал 4×5 минимум, огонь кремнём по низу.",
            "Minecraft: шалкеры подписывай наковальней — не потеряешь.",
            "Minecraft: ночь пережидай в дыре 2×1, не бегай от крипера.",
            "Minecraft: золотая броня в Незере — пиглины не агрятся.",
            "Minecraft: лодка по льду быстрее элитр на короткой.",
            "Minecraft: не копай прямо вниз — сначала два блока рядом.",
        ],
    ),
    "guides_brawl.txt": (
        "Brawl Stars фишки",
        [
            "Brawl Stars: вход только через Supercell ID в самой игре. Код из письма никому не диктуй.",
            "Brawl Stars: «бесплатные гемы» на сайтах и в ботах — фишинг, гемы дают только магазин и Brawl Pass.",
            "Brawl Stars: привяжи Supercell ID к своей почте и включи на ней 2FA — без почты аккаунт не вернуть.",
            "Brawl Stars: не делись входом «для буста»: продавец может сменить почту и не вернуть аккаунт.",
            "Brawl Stars: в шоудауне не лезь в центр в начале — сначала коробки по краю.",
            "Brawl Stars: в «Захвате кристаллов» с 10 кристаллами отходи назад, а не в атаку.",
            "Brawl Stars: прокачивай 2–3 бойцов до 9–11 силы, а не всех понемногу.",
            "Brawl Stars: монеты — в силу бойцов, а не в скины, пока нет гаджетов и звёздных сил.",
            "Brawl Stars: кусты проверяй атакой или гаджетом, прежде чем заходить.",
            "Brawl Stars: покупки — только в магазине игры или через Google Play / App Store.",
        ],
    ),
    "guides_telegram.txt": (
        "Telegram фишки",
        [
            "Telegram: включи облачный пароль — Настройки → Конфиденциальность → Двухэтапная аутентификация.",
            "Telegram: код входа никому не пересылай, даже «поддержке». Telegram его никогда не просит.",
            "Telegram: Настройки → Устройства — проверь сеансы и заверши чужие.",
            "Telegram: скрой номер — Конфиденциальность → Номер телефона → Никто.",
            "Telegram: «Звёзды бесплатно» и «премиум за подписку» в ботах — фишинг аккаунта.",
            "Telegram: папки чатов — Настройки → Папки, работа и личное отдельно.",
            "Telegram: отложенное сообщение — зажми кнопку отправки → «Отправить позже».",
            "Telegram: юзернейм меняется в Настройках, по нему тебя ищут без номера.",
            "Telegram: ссылки на «вход через Telegram» проверяй по домену, не вводи код на чужих сайтах.",
            "Telegram: сохранённые сообщения — личный блокнот, синхронизируется на всех устройствах.",
        ],
    ),
    "guides_funpay.txt": (
        "FunPay покупателю",
        [
            "FunPay: оплачивай только кнопку «Купить» на сайте. Другие реквизиты — стоп.",
            "FunPay: после оплаты не жми «подтвердить», пока не получил товар.",
            "FunPay: спор — через кнопку в заказе, не в личку «дай скидку вне сайта».",
            "FunPay: чат заказа — единственное место, где продавец обязан ответить.",
            "FunPay: если товар автовыдача, данные приходят сюда же, в этот чат.",
            "FunPay: скрин «оплатил» без кнопки Купить не считается оплатой.",
            "FunPay: не переходи по ссылкам из чата на «логин вне FunPay».",
            "FunPay: отзыв ставится после получения. Продавец не имеет права просить звёзды.",
            "FunPay: возврат — через спор, если товар не подошёл по описанию.",
            "FunPay: ник продавца сверяй с карточкой лота, не с копипастой в чате.",
        ],
    ),
}


MICRO_KEYS = ("фишки", "инструкц", "совет", "гайд", "покупателю", "tips", "guide")


def catalog_titles() -> set[str]:
    return {title.strip().lower() for _fname, (title, _lines) in CATALOG.items()}


def is_micro_lot(description: str, price: float | None = None) -> bool:
    """Микролоты 1–12 ₽ (гайды/фишки): автоцена их не двигает."""
    desc = (description or "").strip().lower().replace("ё", "е")
    titles = catalog_titles()
    if desc in titles:
        return True
    if any(t and t in desc for t in titles):
        return True
    keyed = any(k in desc for k in MICRO_KEYS)
    if keyed:
        return price is None or float(price or 0) <= 12
    return False


def _ok(cardinal, uid: int) -> bool:
    tg = getattr(cardinal, "telegram", None)
    return bool(tg) and uid in getattr(tg, "authorized_users", {})


def delivery_text(title: str, lines: list[str]) -> str:
    body = "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1))
    return f"📘 {title}\n{body}\nСохрани сообщение — текст остаётся в этом чате."


def bind_delivery(cardinal) -> int:
    """Весь текст в response, без productsFileName: Cardinal считает остаток бесконечным, файл не тратится."""
    ad = getattr(cardinal, "AD_CFG", None)
    if ad is None:
        return 0
    changed = 0
    for fname, (title, lines) in CATALOG.items():
        if ad.has_section(title):
            sec = ad[title]
            ours = sec.get("response", "").strip() == "$product" and sec.get("productsFileName", "") == fname
            if not ours:
                continue
            ad.remove_option(title, "productsFileName")
        else:
            ad.add_section(title)
            ad.set(title, "disable", "0")
            ad.set(title, "disableAutoRestore", "0")
            ad.set(title, "disableAutoDisable", "0")
            ad.set(title, "disableAutoDelivery", "0")
        ad.set(title, "response", delivery_text(title, lines))
        changed += 1
    if changed:
        try:
            from shop_core.fileio import write_config
            write_config("configs/auto_delivery.cfg", ad)
        except Exception as ex:
            logger.debug("[MicroLots] save AD: %s", ex)
    return changed


def stock_counts() -> dict[str, int]:
    return {title: len(lines) for _fname, (title, lines) in CATALOG.items()}


def hub_text(cardinal) -> str:
    counts = stock_counts()
    ad_on = False
    try:
        ad_on = cardinal.MAIN_CFG.getboolean("FunPay", "autoDelivery")
    except Exception:
        pass
    lines = [
        "📝 <b>Микролоты 5–10 ₽</b>",
        "Реальные короткие фишки/инструкции. Закупка 0 ₽.",
        "Комиссия FunPay ~3% → с лота за 10 ₽ чистыми ≈ <b>9.7 ₽</b>.",
        "100 продаж по 10 ₽ ≈ 970 ₽. Просить отзыв в чате нельзя — правила FunPay.",
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
        "Автовыдача в FunPay: <b>" + ("вкл" if ad_on else "выкл") + "</b>",
        "",
        "<b>Что положить на витрину</b> (название лота = как здесь, цена 5–10 ₽):",
    ]
    for title, n in counts.items():
        lines.append(f"• <code>{title}</code> — {n} советов одним сообщением, ♾ без склада")
    lines.append("")
    lines.append("1. На FunPay создай лот с <b>точным</b> названием из списка.")
    lines.append("2. Цена 5–10 ₽, категория «Прочее» / гайды / услуги — как удобно.")
    lines.append("3. Автовыдачу Cardinal включает владелец в общих настройках — она касается всех лотов, не только гайдов.")
    lines.append("4. Описание лота: «текстовая фишка в чат сразу после оплаты».")
    return "\n".join(lines)


def hub_kb(cardinal) -> K:
    kb = K()
    kb.row(B("🔄 Обновить тексты", callback_data="MICRO:fill"), B("🔍 Проверка", callback_data="CHECK:run"))
    kb.row(B("🏠 Главная", callback_data="PANEL:home"))
    return kb


def init_settings(cardinal):
    SettingsPage(UUID, NAME, "Гайды 5–10 ₽, закупка 0. Название лота FunPay = название в списке.") \
        .set_status(lambda: "\n".join(f"{t}: {n} советов, без склада" for t, n in stock_counts().items())) \
        .attach(cardinal)
    cardinal.add_telegram_commands(UUID, [("microlots", "микролоты 5–10 ₽", True)])


def init_pre(cardinal):
    global _READY
    try:
        bind_delivery(cardinal)
    except Exception as ex:
        logger.debug("[MicroLots] bind: %s", ex)
    init_settings(cardinal)
    tg = getattr(cardinal, "telegram", None)
    if not tg or not getattr(tg, "bot", None) or _READY:
        return
    _READY = True
    bot = tg.bot

    @bot.message_handler(commands=["microlots", "микролоты", "гайды"])
    def cmd_m(m: Message):
        if not _ok(cardinal, m.from_user.id):
            return
        bot.send_message(m.chat.id, hub_text(cardinal), reply_markup=hub_kb(cardinal), parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("MICRO:"))
    def cb_m(c: CallbackQuery):
        if not _ok(cardinal, c.from_user.id):
            return
        try:
            bot.answer_callback_query(c.id)
        except Exception:
            pass
        action = (c.data or "").split(":")[1] if ":" in (c.data or "") else "hub"
        if action == "fill":
            bind_delivery(cardinal)
        bot.send_message(c.message.chat.id, hub_text(cardinal), reply_markup=hub_kb(cardinal), parse_mode="HTML")


BIND_TO_PRE_INIT = [init_pre]
BIND_TO_POST_INIT = [init_pre]
