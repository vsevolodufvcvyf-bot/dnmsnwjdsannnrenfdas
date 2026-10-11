# -*- coding: utf-8 -*-
"""Склад: считает товар, когда кончается — закупает у поставщика и кладёт обратно в файл."""
from __future__ import annotations

import configparser
import logging
import os
import time
from threading import Thread

from plugins._common.bus import notify, is_frozen
from plugins._common.db import get_db
from plugins._common.finance import supplier_post
from plugins._common.panels import candidates_from_suppliers, pick_cheapest
from plugins._common.plugin_settings import SettingsPage
from plugins._common.settings import is_dry_run, is_panic, ini_bool, set_ini
from Utils.cardinal_tools import count_products

logger = logging.getLogger("FPC.AutoRestock")

NAME = "Склад и автопополнение"
VERSION = "1.0.0"
DESCRIPTION = "Считает товар. Если кончился — закупает у поставщика (API) и кладёт в файл выдачи"
CREDITS = "nnanserShop"
UUID = "e2a11c01-6666-4e22-8f01-000000000021"
SETTINGS_PAGE = True
BIND_TO_DELETE = []
BIND_TO_COMMANDS = {}

CONFIG_FILE = "configs/restock.cfg"
_READY = False
_LAST: dict[str, float] = {}


def load_cfg():
    cfg = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        cfg.read(CONFIG_FILE, encoding="utf-8")
    if not cfg.has_section("Restock"):
        cfg["Restock"] = {
            "enabled": "1",
            "min_stock": "2",
            "buy_qty": "5",
            "check_every_sec": "90",
            "min_funpay_rub": "0",
            "assume_sale_rub": "0",
        }
        os.makedirs("configs", exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)
    return cfg["Restock"]


def _suppliers():
    cfg = configparser.ConfigParser()
    if os.path.exists("configs/suppliers.cfg"):
        cfg.read("configs/suppliers.cfg", encoding="utf-8")
    return cfg


def _extract_keys(data) -> list[str]:
    keys: list[str] = []
    if isinstance(data, dict):
        consumed = set()
        for name in ("key", "pin", "code", "keys", "codes", "value"):
            if name not in data:
                continue
            consumed.add(name)
            v = data.get(name)
            if isinstance(v, str) and v.strip() and v.strip().lower() not in ("n/a", "none", "null"):
                keys.append(v.strip())
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, (dict, list)):
                        keys.extend(_extract_keys(x))
                    else:
                        s = str(x).strip()
                        if s and s.lower() not in ("n/a", "none", "null"):
                            keys.append(s)
        for name, v in data.items():
            if name in consumed:
                continue
            if isinstance(v, (dict, list)):
                keys.extend(_extract_keys(v))
    elif isinstance(data, list):
        for x in data:
            if isinstance(x, (dict, list)):
                keys.extend(_extract_keys(x))
            else:
                s = str(x).strip()
                if s and s.lower() not in ("n/a", "none", "null"):
                    keys.append(s)
    return list(dict.fromkeys(keys))


def _wait_keys(url: str, api_key: str, task_id: str, tries: int = 5) -> tuple[list[str], dict]:
    """Асинхронные панели отдают ключи в action=status, не в add."""
    import requests
    last = {}
    for _ in range(max(1, tries)):
        time.sleep(3)
        try:
            res = supplier_post(
                requests.post, url,
                {"key": api_key, "action": "status", "order": task_id},
                timeout=12.0,
            )
            last = res.json() if res is not None else {}
        except Exception as ex:
            last = {"error": str(ex)[:200]}
            continue
        keys = _extract_keys(last)
        if keys:
            return keys, last
        st = str(last.get("status") or "").lower()
        if st in ("canceled", "cancelled", "fail", "error", "refunded"):
            return [], last
    return [], last


def _append_products(path: str, keys: list[str]) -> int:
    if not keys:
        return 0
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            f.write("\n")
        f.write("\n".join(keys))
        f.write("\n")
    return len(keys)


def iter_stock(cardinal) -> list[dict]:
    rows = []
    ad = getattr(cardinal, "AD_CFG", None)
    if not ad:
        return rows
    for section in ad.sections():
        fname = (ad[section].get("productsFileName") or "").strip()
        if not fname:
            rows.append({"lot": section, "file": None, "count": None, "infinite": True})
            continue
        path = os.path.join("storage", "products", fname)
        n = count_products(path) if os.path.exists(path) else 0
        rows.append({"lot": section, "file": fname, "path": path, "count": n, "infinite": False})
    return rows


def stock_text(cardinal) -> str:
    cfg = load_cfg()
    rows = iter_stock(cardinal)
    lines = ["📦 <b>Склад</b>\n"]
    if not rows:
        lines.append("Автовыдача ещё не настроена. /menu → Автовыдача — привяжи лот к файлу с товаром.")
    empty = 0
    for r in rows:
        if r.get("infinite"):
            lines.append(f"♾️ {r['lot']}\n   без файла — считается бесконечным")
            continue
        n = int(r["count"] or 0)
        mark = "🟢" if n >= int(cfg.get("min_stock", 2) or 2) else ("🟡" if n else "🔴")
        if n == 0:
            empty += 1
        lines.append(f"{mark} <b>{n}</b> шт. — {r['lot']}\n   файл: <code>{r['file']}</code>")
    now = time.time()
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM mafile_rentals")
            total = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM mafile_rentals WHERE is_rented = 1 AND expire_time > ?", (now,))
            busy = c.fetchone()[0]
        free = total - busy
        lines.append(f"\n🎮 Steam-аренда: свободно <b>{free}</b> · занято <b>{busy}</b> · всего {total}")
    except Exception:
        pass
    on = cfg.get("enabled", "1") in ("1", "true", "yes", "on")
    lines.append("")
    lines.append("🔁 Автопополнение: <b>вкл</b>" if on else "🔁 Автопополнение: выкл")
    lines.append("Когда товар кончится, бот смотрит цену твоего лота на FunPay и закупает у панели с запасом x2.")
    lines.append("Банковский счёт не подключается — только FunPay и API-панель, которую ты сам добавил.")
    if empty:
        lines.append(f"\n⚠️ Пустых позиций: <b>{empty}</b>. Если API ключ поставщика пустой — положи товар в файл руками.")
    if is_dry_run():
        lines.append("🧪 Учебный режим: закупка у поставщика не уйдёт.")
    if is_panic():
        lines.append("🛑 Аварийный стоп: автопополнение стоит.")
    return "\n".join(lines)


def _match_supplier(lot_name: str):
    cfg = _suppliers()
    hay = (lot_name or "").lower()
    for section in cfg.sections():
        block = cfg[section]
        if not block.getboolean("enabled", fallback=False):
            continue
        kws = [k.strip().lower() for k in block.get("keywords", "").split(",") if k.strip()]
        if kws and any(k in hay for k in kws):
            return section, block
    return None, None


def _try_buy(cardinal, row: dict, cfg) -> None:
    path = row["path"]
    lot = row["lot"]
    key = f"{lot}:{path}"
    now = time.time()
    if now - _LAST.get(key, 0) < 7200:
        return
    _LAST[key] = now
    qty = max(1, int(cfg.get("buy_qty", 5) or 5))
    if is_panic() or is_frozen():
        _LAST[key] = now - 7200 + 120
        return
    try:
        task = _open_task(key)
    except Exception as ex:
        logger.debug("[Restock] task lookup: %s", ex)
        task = None
    if task:
        try:
            _poll_task(cardinal, row, key, task)
        except Exception as ex:
            logger.warning("[Restock] status %s: %s", lot, ex)
            _LAST[key] = time.time() - 7200 + 120
        return
    min_rub = float(cfg.get("min_funpay_rub", 0) or 0)
    bal = getattr(getattr(cardinal, "balance", None), "total_rub", 0) or 0
    if min_rub and float(bal) < min_rub:
        notify(cardinal, f"📦 Склад «{lot}» пуст, но на FunPay мало денег ({bal} ₽). Пополни баланс.", True)
        return
    cands = candidates_from_suppliers(lot)
    unit = float(cfg.get("assume_sale_rub", 0) or 0)
    if unit <= 0:
        try:
            from plugins.shop_desk import infer_sale_price
            unit = float(infer_sale_price(cardinal, lot) or 0)
        except Exception:
            unit = 0.0
    if not cands:
        notify(
            cardinal,
            f"📦 Товар кончился: <b>{lot}</b>\n"
            f"Файл <code>{row['file']}</code> пуст.\n"
            f"Положи ключи в файл или включи поставщика кнопкой «🔌 Панель».",
            True,
        )
        return
    if unit <= 0:
        notify(
            cardinal,
            f"📦 «{lot}» кончился. Не вижу цену лота на FunPay — либо выставь лот, "
            f"либо пропиши <code>assume_sale_rub</code> в configs/restock.cfg "
            f"(сколько берёшь с покупателя за 1 шт.).",
            True,
        )
        return
    sale_total = unit * qty
    best, why = pick_cheapest(cands, sale_total, qty)
    if not best:
        notify(cardinal, f"📉 Склад «{lot}»: {why}", True)
        return
    url, api_key = best.get("api_url", ""), best.get("api_key", "")
    service_id = str(best.get("service_id") or "").strip()
    section = best.get("section") or best.get("name")
    if not url or not api_key:
        notify(cardinal, f"📦 «{lot}» кончился, но у поставщика [{section}] нет api_url/api_key.", True)
        return
    if is_dry_run():
        notify(cardinal, f"🧪 Учебный режим: «{lot}» кончился, закупку {qty} шт. не отправлял.\n{why}", True)
        return
    payload = {
        "key": api_key,
        "action": "add",
        "service": service_id,
        "quantity": qty,
        "link": "restock",
    }
    task_id = ""
    try:
        import requests
        res = supplier_post(requests.post, url, payload, timeout=15.0)
        data = {}
        try:
            data = res.json()
        except Exception:
            data = {"raw": (res.text or "")[:500]}
        task_id = str((data or {}).get("order") or "") if isinstance(data, dict) else ""
        if task_id:
            _remember_task(key, section, task_id)
        keys = _extract_keys(data)
        if not keys and task_id:
            keys, data = _wait_keys(url, api_key, task_id)
        added = _append_products(path, keys) if keys else 0
        if added and task_id:
            _forget_task(key)
        with get_db() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS restock_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lot TEXT, qty INTEGER, added INTEGER, provider TEXT, created_at REAL
                )"""
            )
            conn.execute(
                "INSERT INTO restock_log (lot, qty, added, provider, created_at) VALUES (?, ?, ?, ?, ?)",
                (lot, qty, added, section, time.time()),
            )
        if added:
            logger.info("[Restock] «%s»: дописал %s шт. от [%s]", lot, added, section)
        elif task_id:
            _LAST[key] = time.time() - 7200 + 120
            notify(
                cardinal,
                f"🛒 «{lot}»: у [{section}] создана задача #{task_id}, ключей пока нет.\n"
                f"Новую закупку не шлю — каждые 2 минуты спрашиваю статус этой задачи.",
                True,
            )
        else:
            _LAST[key] = time.time() - 7200 + 120
            notify(
                cardinal,
                f"🛒 Закупка «{lot}» у [{section}]: панель не создала заказ.\n"
                f"Ответ поставщика: <code>{str(data)[:300]}</code>\n"
                f"Повтор через 2 минуты.",
                True,
            )
    except Exception as ex:
        logger.warning("[Restock] %s: %s", lot, ex)
        if task_id:
            notify(cardinal, f"⚠️ «{lot}»: задача #{task_id} создана, дальше только проверка статуса. Ошибка: {ex}", True)
        else:
            notify(cardinal, f"❌ Не смог закупить «{lot}»: {ex}", True)
        _LAST[key] = time.time() - 7200 + 120


_TASK_PLUGIN = "restock"
_TASK_TTL = 24 * 3600


def _remember_task(key: str, section, task_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO supplier_orders
               (order_id, plugin_name, provider, task_id, status, created_at)
               VALUES (?, ?, ?, ?, 'waiting', ?)""",
            (key, _TASK_PLUGIN, str(section or ""), task_id, time.time()),
        )


def _forget_task(key: str, status: str = "done") -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE supplier_orders SET status = ? WHERE order_id = ? AND plugin_name = ?",
            (status, key, _TASK_PLUGIN),
        )


def _open_task(key: str):
    with get_db() as conn:
        return conn.execute(
            """SELECT provider, task_id, created_at FROM supplier_orders
               WHERE order_id = ? AND plugin_name = ? AND status = 'waiting'""",
            (key, _TASK_PLUGIN),
        ).fetchone()


def _poll_task(cardinal, row: dict, key: str, task) -> None:
    """Задача у панели уже есть: только action=status, новый add не шлём."""
    lot, path = row["lot"], row["path"]
    section = str(task["provider"] or "")
    cfg = _suppliers()
    block = cfg[section.split("/")[0]] if cfg.has_section(section.split("/")[0]) else {}
    url, api_key = block.get("api_url", ""), block.get("api_key", "")
    task_id = str(task["task_id"])
    if not url or not api_key:
        notify(cardinal, f"⚠️ «{lot}»: задача #{task_id} у [{section}], но ключ панели пропал. Проверь вручную.", True)
        _forget_task(key, "lost")
        return
    keys, data = _wait_keys(url, api_key, task_id, tries=2)
    if keys:
        added = _append_products(path, keys)
        _forget_task(key)
        logger.info("[Restock] «%s»: задача #%s отдала %s шт.", lot, task_id, added)
        return
    st = str((data or {}).get("status") or "").lower() if isinstance(data, dict) else ""
    if st in ("canceled", "cancelled", "fail", "error", "refunded"):
        _forget_task(key, st)
        notify(cardinal, f"❌ «{lot}»: панель отменила задачу #{task_id} ({st}). Следующий круг закупит заново.", True)
        return
    if time.time() - float(task["created_at"] or 0) > _TASK_TTL:
        _forget_task(key, "stale")
        notify(
            cardinal,
            f"⌛ «{lot}»: задача #{task_id} у [{section}] сутки без ключей. Проверь её в панели — "
            f"новую закупку бот теперь разрешит.",
            True,
        )
        return
    _LAST[key] = time.time() - 7200 + 120


def check_once(cardinal) -> None:
    cfg = load_cfg()
    if cfg.get("enabled", "1") not in ("1", "true", "yes", "on"):
        return
    min_stock = int(cfg.get("min_stock", 2) or 2)
    for row in iter_stock(cardinal):
        if row.get("infinite"):
            continue
        if int(row.get("count") or 0) < min_stock:
            _try_buy(cardinal, row, cfg)


def _loop(cardinal):
    while True:
        try:
            sec = int(load_cfg().get("check_every_sec", 90) or 90)
            check_once(cardinal)
        except Exception as ex:
            logger.debug("[Restock] loop: %s", ex)
            sec = 90
        time.sleep(max(30, sec))


def init_settings(cardinal):
    SettingsPage(UUID, NAME, "Склад. Если товар кончился — закупка у поставщика (не банк).") \
        .add_toggle("enabled", "Автопополнение склада",
                    lambda: ini_bool(CONFIG_FILE, "Restock", "enabled", True),
                    lambda v: set_ini(CONFIG_FILE, "Restock", "enabled", "1" if v else "0")) \
        .set_status(lambda: stock_text(cardinal)) \
        .attach(cardinal)
    cardinal.add_telegram_commands(UUID, [("stock", "склад и автопополнение", True)])


def init_pre(cardinal):
    global _READY
    init_settings(cardinal)
    tg = getattr(cardinal, "telegram", None)
    if not tg or not getattr(tg, "bot", None) or _READY:
        return
    _READY = True

    @tg.bot.message_handler(commands=["stock", "склад", "остатки"])
    def cmd_stock(m):
        if m.from_user.id not in getattr(tg, "authorized_users", {}):
            return
        tg.bot.send_message(m.chat.id, stock_text(cardinal), parse_mode="HTML")


def init_post(cardinal):
    Thread(target=_loop, args=(cardinal,), daemon=True).start()


def on_new_order(cardinal, event):
    try:
        check_once(cardinal)
    except Exception as ex:
        logger.debug("[Restock] after order: %s", ex)


BIND_TO_PRE_INIT = [init_pre]
BIND_TO_POST_START = [init_post]
BIND_TO_NEW_ORDER = [on_new_order]
