from types import SimpleNamespace

import pytest

from conftest import make_callback


# ---------- autoback ----------

def test_autoback_decide_ask_mode_always_asks():
    from plugins.autoback import decide
    assert decide("ask", 10, 300, False, True, 0, 1, 0, 1000)[0] == "ask"


@pytest.mark.parametrize("kwargs, expected", [
    (dict(price=100), "auto"),
    (dict(price=500), "ask"),
    (dict(price=100, delivered=True), "ask"),
    (dict(price=100, buyer_refunds_30d=1), "ask"),
    (dict(price=100, refunded_today=950), "ask"),
])
def test_autoback_decide_auto_limits(kwargs, expected):
    from plugins.autoback import decide
    base = dict(mode="auto", price=100, max_refund=300, delivered=False, skip_if_delivered=True,
                buyer_refunds_30d=0, buyer_limit=1, refunded_today=0, daily_limit=1000)
    base.update(kwargs)
    assert decide(**base)[0] == expected


class FakeAccount:
    def __init__(self):
        self.refunds = []

    def refund(self, order_id):
        self.refunds.append(order_id)


def _review_event(order_id="ORD1", stars=1, price=150.0, buyer="buyer1"):
    from FunPayAPI.common.enums import MessageTypes
    msg = SimpleNamespace(type=MessageTypes.NEW_FEEDBACK, i_am_buyer=False, chat_id=999)
    order = SimpleNamespace(id=order_id, price=price, buyer_username=buyer, currency="₽",
                            review=SimpleNamespace(stars=stars, text="плохо <3 & долго"))
    return msg, order


def _cardinal(fake_tg, order):
    return SimpleNamespace(telegram=fake_tg, account=FakeAccount(), get_order_from_object=lambda m: order)


def test_autoback_ask_mode_waits_for_owner(monkeypatch, fake_tg):
    from plugins import autoback
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "111")
    monkeypatch.setattr(autoback, "is_dry_run", lambda: False)
    monkeypatch.setattr(autoback, "bot_send", lambda *a, **k: True)
    msg, order = _review_event()
    card = _cardinal(fake_tg, order)
    autoback.process_review_event(card, SimpleNamespace(message=msg))
    assert card.account.refunds == []
    text, kb, _ = fake_tg.notifications[-1]
    datas = [b.callback_data for row in kb.keyboard for b in row]
    assert "ABK:yes:ORD1" in datas and "ABK:no:ORD1" in datas

    fake_tg.authorized_users = {111: {}, 222: {}}
    autoback.handle_callback(card, make_callback(222, "ABK:yes:ORD1"))
    assert card.account.refunds == [], "оператор без права не возвращает"
    autoback.handle_callback(card, make_callback(111, "ABK:yes:ORD1"))
    autoback.handle_callback(card, make_callback(111, "ABK:yes:ORD1"))
    assert card.account.refunds == ["ORD1"], "возврат ровно один раз"


def test_autoback_decline_blocks_future_asks(monkeypatch, fake_tg):
    from plugins import autoback
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "111")
    msg, order = _review_event(order_id="ORD2")
    card = _cardinal(fake_tg, order)
    autoback.process_review_event(card, SimpleNamespace(message=msg))
    fake_tg.authorized_users = {111: {}}
    autoback.handle_callback(card, make_callback(111, "ABK:no:ORD2"))
    n = len(fake_tg.notifications)
    autoback.process_review_event(card, SimpleNamespace(message=msg))
    assert len(fake_tg.notifications) == n
    assert card.account.refunds == []


def test_autoback_auto_mode_refuses_delivered_goods(monkeypatch, fake_tg):
    from plugins import autoback
    from shop_core.finance import log_finance
    from shop_core.settings import set_ini
    set_ini(autoback.CONFIG_FILE, "Autoback", "mode", "auto")
    monkeypatch.setattr(autoback, "is_dry_run", lambda: False)
    log_finance("ORD3", "autodelivery", 150, 5)
    msg, order = _review_event(order_id="ORD3")
    card = _cardinal(fake_tg, order)
    autoback.process_review_event(card, SimpleNamespace(message=msg))
    assert card.account.refunds == []
    assert "уже выдан" in fake_tg.notifications[-1][0]


# ---------- quantity ----------

@pytest.mark.parametrize("desc, amount, expected", [
    ("Telegram Stars | 50 звёзд", 3, 150),
    ("Подписчики Telegram 1000 | гарантия 30 дней", 3, 3000),
    ("Telegram Stars | 2026 | 100", 2, 200),
    ("Звёзды Telegram, цена за 1 шт", 500, 500),
    ("Подарок мишка", 2, 2),
    ("Просмотры 1000 | 24 часа", 1, 1000),
])
def test_parse_qty(desc, amount, expected):
    from shop_core.confirm import parse_qty
    assert parse_qty(desc, amount) == expected


# ---------- supplier responses ----------

def test_request_not_sent_classification():
    import requests
    from shop_core.confirm import request_not_sent
    assert request_not_sent(requests.exceptions.ConnectTimeout("connect timeout"))
    assert request_not_sent(requests.ConnectionError("NewConnectionError: Failed to establish a new connection"))
    assert not request_not_sent(requests.exceptions.ReadTimeout("read timed out"))
    assert not request_not_sent(requests.ConnectionError("Connection aborted. RemoteDisconnected"))


@pytest.mark.parametrize("code, data, verdict", [
    (200, {"order": 123}, "ok"),
    (200, {"error": "Incorrect link"}, "rejected"),
    (200, {"error": "Not enough funds on balance"}, "no_funds"),
    (402, {}, "no_funds"),
    (502, {}, "uncertain"),
    (200, {}, "uncertain"),
    (200, {"status": "weird"}, "uncertain"),
])
def test_classify_panel_response(code, data, verdict):
    from shop_core.confirm import classify_panel_response
    assert classify_panel_response(code, data) == verdict


def test_smm_service_mapping():
    from shop_core.confirm import smm_service_for
    cand = {"services": "подписчик:123, лайк=456"}
    assert smm_service_for(cand, "1000 подписчиков Telegram") == "123"
    assert smm_service_for(cand, "Лайки на пост") == "456"
    assert smm_service_for(cand, "просмотры") is None
    assert smm_service_for({"service_id": "999"}, "лайки") is None


def _panel_setup(monkeypatch, post):
    from shop_core import confirm
    sent, notes = [], []
    panels = [
        {"name": "p1", "api_url": "https://p1", "api_key": "k1", "service_id": "1", "_cost": 10, "section": "stars"},
        {"name": "p2", "api_url": "https://p2", "api_key": "k2", "service_id": "2", "_cost": 11, "section": "stars"},
    ]
    monkeypatch.setattr(confirm, "_candidates_for", lambda *a, **k: (panels, []))
    monkeypatch.setattr(confirm, "budget_panels", lambda c, s, q: (panels, "ok"))
    monkeypatch.setattr(confirm, "preflight_or_abort", lambda *a, **k: (True, "paid"))
    monkeypatch.setattr(confirm, "is_dry_run", lambda: False)
    monkeypatch.setattr(confirm, "bot_send", lambda card, chat, text, name=None: sent.append(text))
    monkeypatch.setattr(confirm, "notify", lambda card, text, critical=False, keyboard=None: notes.append((text, keyboard)))
    monkeypatch.setattr(confirm, "supplier_post", lambda _post, url, data, timeout=12.0: post(url, data))
    return confirm, sent, notes


def test_read_timeout_does_not_buy_twice(monkeypatch):
    import requests
    calls = []

    def post(url, data):
        calls.append(url)
        raise requests.exceptions.ReadTimeout("read timed out")

    confirm, sent, notes = _panel_setup(monkeypatch, post)
    card = SimpleNamespace(account=SimpleNamespace(id=1))
    res = confirm.deliver_via_panel(card, "stars", "ORD9", 555, "user_x", 100, 500.0, "stars")
    assert res == "uncertain"
    assert calls == ["https://p1"], "вторую панель не трогаем — первая могла создать заказ"
    from shop_core.finance import claim_delivery
    assert claim_delivery("ORD9", "autostars") is False, "замок заказа остаётся"
    kb = notes[-1][1]
    datas = [b.callback_data for row in kb.keyboard for b in row]
    assert "CNF:retry:ORD9" in datas and "CNF:done:ORD9" in datas
    assert all("да ещё раз" not in t for t in sent)


def test_connect_timeout_tries_next_panel(monkeypatch):
    import requests
    calls = []

    def post(url, data):
        calls.append(url)
        if url == "https://p1":
            raise requests.exceptions.ConnectTimeout("connect timeout")
        return SimpleNamespace(status_code=200, json=lambda: {"order": 77})

    confirm, sent, notes = _panel_setup(monkeypatch, post)
    card = SimpleNamespace(account=SimpleNamespace(id=1))
    assert confirm.deliver_via_panel(card, "stars", "ORD10", 555, "user_x", 100, 500.0, "stars") == "ok"
    assert calls == ["https://p1", "https://p2"]


def test_explicit_rejection_releases_lock(monkeypatch):
    def post(url, data):
        return SimpleNamespace(status_code=200, json=lambda: {"error": "Incorrect username"})

    confirm, sent, notes = _panel_setup(monkeypatch, post)
    card = SimpleNamespace(account=SimpleNamespace(id=1))
    assert confirm.deliver_via_panel(card, "stars", "ORD11", 555, "user_x", 100, 500.0, "stars") == "fail"
    from shop_core.finance import claim_delivery
    assert claim_delivery("ORD11", "autostars") is True, "заказа у поставщика нет — можно повторить"


# ---------- autoprice ----------

def test_seller_price_conversion():
    from plugins.auto_price import coef_from, seller_price_for
    assert seller_price_for(110, 1.1) == 100.0
    assert coef_from(SimpleNamespace(commission_coefficient=1.12)) == 1.12
    assert coef_from(SimpleNamespace(commission_coefficient=12)) is None
    assert coef_from(None) is None


def test_target_keeps_pinned_lot_price():
    from plugins.auto_price import _target
    stats = {"cheapest": 90, "live_med": 120, "q1": 95, "n": 10}
    assert _target(100, stats, 10, 1, 25, pinned=True)[0] == 100
    raised, why = _target(100, stats, 10, 1, 25, pinned=True, raise_pct=5, max_over_med_pct=10)
    assert raised == 105 and "закреп" in why
    assert _target(100, stats, 10, 1, 25)[0] < 100


def test_apply_writes_price_without_commission():
    from plugins.auto_price import _apply
    saved = {}
    fields = SimpleNamespace(price=None, calc_result=SimpleNamespace(commission_coefficient=1.25))
    acc = SimpleNamespace(get_lot_fields=lambda lot_id: fields, save_lot=lambda f: saved.update(price=f.price))
    lot = SimpleNamespace(id="42")
    _apply(SimpleNamespace(account=acc), lot, 125.0)
    assert saved["price"] == 100.0
    fields.calc_result = None
    with pytest.raises(ValueError):
        _apply(SimpleNamespace(account=acc), lot, 125.0)
