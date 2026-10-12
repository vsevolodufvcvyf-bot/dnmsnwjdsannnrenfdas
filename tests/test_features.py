import time
from types import SimpleNamespace

def _insert_finance(order_id, profit, dry_run, created_at, sale=None):
    from shop_core.db import get_db
    sale = profit if sale is None else sale
    with get_db() as conn:
        conn.execute(
            """INSERT INTO finance_log
               (order_id, plugin_name, sale_price, cost, profit, currency, dry_run, created_at)
               VALUES (?, 't', ?, 0, ?, 'RUB', ?, ?)""",
            (order_id, sale, profit, dry_run, created_at),
        )


def test_goal_ignores_dry_run_and_yesterday():
    from shop_core.goals import bar, goal_line, parse_goal, set_daily_target, today_totals
    now = time.time()
    _insert_finance("real", 300, 0, now)
    _insert_finance("lesson", 9000, 1, now)
    _insert_finance("old", 777, 0, now - 90000)
    sales, _cost, profit, n = today_totals(now)
    assert n == 1
    assert profit == 300
    assert sales == 300
    assert parse_goal("/goal") == ("show", None)
    assert parse_goal("/goal abc") == ("bad", None)
    assert parse_goal("/goal нет") == ("set", 0.0)
    assert parse_goal("/goal 3000") == ("set", 3000.0)
    set_daily_target(1000)
    text = goal_line(profit)
    assert "300" in text and "1000" in text
    assert "9000" not in text and "777" not in text
    assert bar(300, 1000) == "███░░░░░░░"
    set_daily_target(0)
    assert "цель не задана" in goal_line(0)


def test_demand_chart_marks_peak():
    from shop_core.db import get_db
    from plugins.raise_clock import chart_lines, demand_text, note_order
    now = time.time()
    for i, hour in enumerate((18, 18, 18, 3)):
        moment = time.localtime(now)
        # пишем напрямую, чтобы час не зависел от текущего времени
        with get_db() as conn:
            conn.execute(
                "INSERT INTO sale_clock (order_id, hour, created_at, weekday) VALUES (?, ?, ?, ?)",
                (f"o{i}", hour, now, moment.tm_wday),
            )
    lines = chart_lines({18: 3, 3: 1}, active={18})
    assert len(lines) == 24
    hot = next(line for line in lines if line.startswith("●18"))
    assert hot.endswith(" 3")
    assert "█" * 10 in hot
    quiet = next(line for line in lines if "03 " in line[:4])
    assert "░" in quiet
    text = demand_text()
    assert "Когда покупают" in text
    assert "<pre>" in text
    note_order("ADTEST")
    with get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sale_clock WHERE order_id = 'ADTEST'").fetchone()[0] == 0


def test_dossier_counts_orders_and_refunds():
    from shop_core.db import get_db
    from shop_core.dossier import dossier_block, note_seen
    assert "ещё не было" in dossier_block("Buyer")
    note_seen("A1", "Buyer", 100, "лот", time.time() - 7200, "RUB")
    assert "Первый заказ" in dossier_block("Buyer")
    note_seen("A1", "Buyer", 999, "повтор того же id", time.time(), "RUB")
    note_seen("A2", "buyer", 50, "второй", time.time(), "USD")
    text = dossier_block("Buyer")
    assert "2" in text
    assert "на <b>" not in text
    assert "назад" in text
    with get_db() as conn:
        conn.execute(
            """INSERT INTO autoback_log (order_id, buyer_name, stars, price, currency, review_text, refunded_at)
               VALUES ('R1', 'Buyer', 1, 100, 'RUB', '', ?)""",
            (time.time(),),
        )
    assert "Возвратов" in dossier_block("Buyer")


def test_lot_draft_rejects_promises_and_ignores_dirty_llm():
    from shop_core.lotcopy import LotDraftError, format_lot_message, lot_text, parse_lot_args, template_lot
    product, hint = parse_lot_args("/lottext@bot 1000 робуксов | выдача по логину")
    draft = template_lot(product, hint)
    assert draft["source"] == "template"
    assert "робуксов" in draft["title"]
    assert "логину" in draft["body"]
    assert "отзыв" not in draft["body"].lower()
    shown = format_lot_message(draft)
    assert "<code>" in shown
    try:
        template_lot("звёзды бесплатно")
        raise AssertionError("обещание должно остановить черновик")
    except LotDraftError:
        pass

    def dirty(_product, _hint):
        return "НАЗВАНИЕ: Звёзды\nОПИСАНИЕ:\nПоставь отзыв и будет скидка"

    clean = lot_text("100 звёзд", llm=dirty)
    assert clean["source"] == "template"
    assert "скидка" not in clean["body"]

    def nice(_product, _hint):
        return "НАЗВАНИЕ: 100 звёзд Telegram\nОПИСАНИЕ:\nПосле оплаты напишите логин в чат заказа."

    polished = lot_text("100 звёзд", llm=nice)
    assert polished["source"] == "llm"
    assert "Telegram" in polished["title"]


def test_forget_secret_only_drops_api_key():
    from plugins.shop_desk import forget_secret
    deleted = []

    class Bot:
        def delete_message(self, chat_id, message_id):
            deleted.append((chat_id, message_id))

    msg = SimpleNamespace(chat=SimpleNamespace(id=7), id=3)
    assert forget_secret(Bot(), msg, "url") is False
    assert deleted == []
    assert forget_secret(Bot(), msg, "key") is True
    assert deleted == [(7, 3)]


def test_home_shows_real_profit_not_lesson():
    from shop_core.goals import set_daily_target
    from tg_bot.panel_ui import home_kb, home_text
    now = time.time()
    _insert_finance("real", 300, 0, now, sale=500)
    _insert_finance("lesson", 9000, 1, now, sale=9000)
    set_daily_target(1000)
    cardinal = SimpleNamespace(
        account=SimpleNamespace(username="shop", id=5, active_sales=1),
        balance=SimpleNamespace(total_rub=100, available_rub=80, source="exact"),
        profile=None,
    )
    text = home_text(cardinal)
    assert "300" in text
    assert "1000" in text
    assert "9000" not in text
    assert "/lottext" in text
    data = []
    kb = home_kb(cardinal)
    for row in kb.keyboard:
        for button in row:
            data.append(button.callback_data)
    assert "PANEL:hours" in data and "PANEL:goal" in data and "SHOP:day" in data


def test_splash_mentions_cached_deps_and_crash_stop(capsys):
    import os
    from conftest import ROOT
    from Utils.console_ui import print_splash
    print_splash("go", "cached")
    out = capsys.readouterr().out
    assert "S H O P" in out
    assert "пакеты уже стоят" in out
    print_splash("down", "1", "3")
    stopped = capsys.readouterr().out
    assert "три сбоя" in stopped
    raw = open(os.path.join(ROOT, "Start.bat"), "rb").read()
    assert b"\r\n" in raw
    assert b"splash.py deps" in raw
    assert b"FAILS" in raw

