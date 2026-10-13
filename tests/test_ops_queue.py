import time
from datetime import datetime
from types import SimpleNamespace


def test_operator_queue_dedupes_and_resolves():
    from shop_core.operator_queue import enqueue, open_items, queue_text, resolve_item
    first = enqueue("users-5-99", "A1", "supplier", "timeout", account_id=5)
    second = enqueue(99, "A1", "supplier", "api_key=secret ещё раз")
    assert first == second
    rows = open_items()
    assert len(rows) == 1
    assert rows[0]["chat_id"] == 99
    assert "secret" not in (rows[0]["detail"] or "")
    assert "•••" in rows[0]["detail"]
    text = queue_text(rows)
    assert "заказ #A1" in text
    assert resolve_item(first) is True
    assert open_items() == []
    assert resolve_item(first) is False


def test_breaker_moves_panel_to_the_end():
    from shop_core.breaker import is_open, note_failure, note_success, prefer_healthy
    assert note_failure("https://a") is False
    assert note_failure("https://a/") is False
    assert note_failure("https://a") is True
    assert is_open("https://a/")
    panels = [
        {"api_url": "https://a", "name": "a"},
        {"api_url": "https://b", "name": "b"},
    ]
    assert [p["name"] for p in prefer_healthy(panels)] == ["b", "a"]
    note_success("https://a")
    assert not is_open("https://a")
    assert [p["name"] for p in prefer_healthy(panels)] == ["a", "b"]


def test_open_panel_is_not_the_first_purchase(monkeypatch):
    from shop_core import confirm
    from shop_core.breaker import note_failure
    for _ in range(3):
        note_failure("https://p1")
    calls = []

    def post(url, data):
        calls.append(url)
        return SimpleNamespace(status_code=200, json=lambda: {"order": 77})

    panels = [
        {"name": "p1", "api_url": "https://p1", "api_key": "k1", "service_id": "1", "_cost": 10, "section": "stars"},
        {"name": "p2", "api_url": "https://p2", "api_key": "k2", "service_id": "2", "_cost": 11, "section": "stars"},
    ]
    notes = []
    monkeypatch.setattr(confirm, "_candidates_for", lambda *a, **k: (panels, []))
    monkeypatch.setattr(confirm, "budget_panels", lambda c, s, q: (panels, "ok"))
    monkeypatch.setattr(confirm, "preflight_or_abort", lambda *a, **k: (True, "paid"))
    monkeypatch.setattr(confirm, "is_dry_run", lambda: False)
    monkeypatch.setattr(confirm, "bot_send", lambda card, chat, text, name=None: None)
    monkeypatch.setattr(confirm, "notify", lambda card, text, critical=False, keyboard=None: notes.append((text, keyboard)))
    monkeypatch.setattr(confirm, "supplier_post", lambda _post, url, data, timeout=12.0: post(url, data))
    card = SimpleNamespace(account=SimpleNamespace(id=1))
    assert confirm.deliver_via_panel(card, "stars", "ORD-BR", 555, "user_x", 100, 500.0, "stars") == "ok"
    assert calls == ["https://p2"]
    kb = notes[-1][1]
    datas = [b.callback_data for row in kb.keyboard for b in row]
    assert any(item.startswith("SHOP:st:") for item in datas)


def test_weekend_bucket_when_one_day_is_thin():
    from shop_core.db import get_db
    from plugins.raise_clock import plan, preferred_gap
    now = time.time()
    with get_db() as conn:
        for i in range(3):
            conn.execute(
                "INSERT INTO sale_clock (order_id, hour, created_at, weekday) VALUES (?, 20, ?, 5)",
                (f"sat{i}", now),
            )
        for i in range(6):
            conn.execute(
                "INSERT INTO sale_clock (order_id, hour, created_at, weekday) VALUES (?, 20, ?, 6)",
                (f"sun{i}", now),
            )
        for i in range(20):
            conn.execute(
                "INSERT INTO sale_clock (order_id, hour, created_at, weekday) VALUES (?, 3, ?, 0)",
                (f"mon{i}", now),
            )
    saturday = datetime(2026, 10, 17, 20, 15)
    assert saturday.weekday() == 5
    hours, why = plan(saturday)
    assert 20 in hours and 3 not in hours
    assert "выходные" in why
    assert preferred_gap(saturday, hours, {20: 9}) == 0
    thin = saturday.replace(hour=19)
    assert 19 in hours
    assert preferred_gap(thin, hours, {20: 9}) == 40 * 60


def test_weekday_bucket_ignores_weekend_peak():
    from shop_core.db import get_db
    from plugins.raise_clock import plan
    now = time.time()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sale_clock (order_id, hour, created_at, weekday) VALUES ('tue', 11, ?, 1)",
            (now,),
        )
        for day, n in ((0, 3), (2, 3), (3, 2), (4, 2)):
            for i in range(n):
                conn.execute(
                    "INSERT INTO sale_clock (order_id, hour, created_at, weekday) VALUES (?, 11, ?, ?)",
                    (f"d{day}-{i}", now, day),
                )
        for i in range(12):
            conn.execute(
                "INSERT INTO sale_clock (order_id, hour, created_at, weekday) VALUES (?, 22, ?, 5)",
                (f"we{i}", now),
            )
    tuesday = datetime(2026, 10, 13, 11, 0)
    assert tuesday.weekday() == 1
    hours, why = plan(tuesday)
    assert 11 in hours and 22 not in hours
    assert why.startswith("будни")


def test_hold_alert_lists_order_ids_from_journal():
    from shop_core.db import get_db
    from plugins.balance_monitor import candidate_order_ids, hold_alert_text
    with get_db() as conn:
        conn.execute(
            """INSERT INTO supplier_orders (order_id, plugin_name, provider, task_id, status, created_at)
               VALUES ('ZZ1', 'autostars', 'stars', '15', 'success', ?)""",
            (time.time(),),
        )
        conn.execute(
            """INSERT INTO supplier_orders (order_id, plugin_name, provider, task_id, status, created_at)
               VALUES ('lot-key', 'restock', 'smm', '9', 'waiting', ?)""",
            (time.time(),),
        )
    ids = candidate_order_ids(SimpleNamespace(account=None))
    assert ids == ["ZZ1"]
    text = hold_alert_text(120.5, 130.0, ids)
    assert "ZZ1" in text and "48 ч" in text and "lot-key" not in text
    assert "не прочитался" in hold_alert_text(1, 1, None)


def test_market_skips_own_lots_and_dumps():
    from plugins.market_analyzer import market_stats

    def seller(sid, name):
        return SimpleNamespace(id=sid, username=name, reviews=10, stars=5, online=True)

    lots = [
        SimpleNamespace(id=1, price=10, description="stars", seller=seller(7, "me"), server="", side=""),
        SimpleNamespace(id=2, price=1, description="stars", seller=seller(2, "dump"), server="", side=""),
        SimpleNamespace(id=3, price=100, description="stars", seller=seller(3, "a"), server="", side=""),
        SimpleNamespace(id=4, price=110, description="stars", seller=seller(4, "b"), server="", side=""),
        SimpleNamespace(id=5, price=120, description="stars", seller=seller(5, "c"), server="", side=""),
        SimpleNamespace(id=6, price=130, description="stars", seller=seller(6, "d"), server="", side=""),
    ]
    card = SimpleNamespace(account=SimpleNamespace(id=7, username="me"))
    stats = market_stats(card, 1, "stars", lots=lots)
    assert stats["cheapest"] == 100
    assert stats["n"] == 4
    assert stats["floor_bar"] > 1


def test_task_status_shows_progress_and_refund():
    from shop_core.task_status import format_task_status, remember_task, status_keyboard
    rid = remember_task("ORD1", "autostars", "stars", "15")
    assert rid > 0
    text = format_task_status("15", "stars", {
        "status": "In progress",
        "start_count": "1000",
        "remains": "400",
        "charge": "1.20",
        "refund": "0.30",
    })
    assert "Прогресс" in text
    assert "400" in text
    assert "Возврат на баланс" in text
    assert "0.30" in text
    datas = [b.callback_data for row in status_keyboard(rid).keyboard for b in row]
    assert datas == [f"SHOP:st:{rid}"]
