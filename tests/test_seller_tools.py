import csv
import io
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from FunPayAPI.common.enums import OrderStatuses


def _order(oid, hours_ago, status=OrderStatuses.PAID, price=500):
    when = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return SimpleNamespace(id=oid, date=when, status=status, buyer_username=f"b_{oid}", price=price, currency="₽")


def test_find_stuck_orders():
    from plugins.seller_tools import find_stuck
    orders = [_order("A", 30), _order("B", 2), _order("C", 50), _order("D", 40, OrderStatuses.CLOSED)]
    stuck = find_stuck(orders, 24)
    assert [o.id for o in stuck] == ["C", "A"]


def test_stuck_text_has_links_and_ticket():
    from plugins.seller_tools import find_stuck, stuck_text
    stuck = find_stuck([_order("ABC123", 30)], 24)
    text = stuck_text(stuck, 24)
    assert 'href="https://funpay.com/orders/ABC123/"' in text
    assert "#ABC123" in text and "закрыть заказ" in text
    assert "Нет оплаченных" in stuck_text([], 24)


def test_fetch_paid_orders_paginates():
    from plugins import seller_tools
    pages = {None: ("N1", [_order("A", 30)]), "N1": (None, [_order("B", 30)])}
    calls = []

    def get_sales(start_from=None, **kw):
        calls.append(start_from)
        nxt, chunk = pages[start_from]
        return nxt, chunk, "ru", {}

    orig = seller_tools.time.sleep
    seller_tools.time.sleep = lambda s: None
    try:
        orders = seller_tools.fetch_paid_orders(SimpleNamespace(get_sales=get_sales))
    finally:
        seller_tools.time.sleep = orig
    assert [o.id for o in orders] == ["A", "B"] and calls == [None, "N1"]


def test_price_table():
    from plugins.seller_tools import price_table
    rows = price_table(1.0, 20, 10, packs=(100,))
    assert rows == [{"qty": 100, "cost": 100.0, "receive": 120.0, "buyer": 132.0, "profit": 20.0}]


def test_parse_calc_args():
    from plugins.seller_tools import parse_calc_args
    assert parse_calc_args("/calc 1,35 15 8") == (1.35, 15.0, 8.0)
    assert parse_calc_args("/calc 2")[0:2] == (2.0, 10.0)
    assert parse_calc_args("/calc") is None
    assert parse_calc_args("/calc -1 5") is None


def test_finance_csv_opens_in_excel():
    from plugins.seller_tools import finance_csv
    from shop_core.finance import log_finance
    log_finance("ORD1", "autostars", 150.5, 100)
    data = finance_csv().decode("utf-8")
    assert data.startswith("\ufeff")
    rows = list(csv.reader(io.StringIO(data.lstrip("\ufeff")), delimiter=";"))
    assert rows[0][0] == "дата" and rows[1][1] == "ORD1" and rows[1][3] == "150,50"


def test_collect_lots_skips_csrf_and_currency():
    from FunPayAPI.common.enums import SubCategoryTypes
    from plugins.seller_tools import collect_lots
    common = SimpleNamespace(type=SubCategoryTypes.COMMON, id=10, name="Аккаунты")
    chips = SimpleNamespace(type=SubCategoryTypes.CURRENCY, id=11, name="Золото")
    lots = [SimpleNamespace(id="1", subcategory=common, description="Лот 1", price=100),
            SimpleNamespace(id="2", subcategory=chips, description="Золото", price=5)]
    profile = SimpleNamespace(get_lots=lambda: lots)
    fields = SimpleNamespace(fields={"csrf_token": "x", "fields[summary][ru]": "Лот 1", "price": "90"})
    acc = SimpleNamespace(get_lot_fields=lambda lot_id: fields)
    out = collect_lots(acc, profile, pause=0)
    assert len(out) == 1 and out[0]["lot_id"] == "1"
    assert "csrf_token" not in out[0]["fields"] and out[0]["fields"]["price"] == "90"


def test_orders_text_lists_pending_and_checks():
    from plugins.seller_tools import orders_text
    from shop_core.confirm import put_pending
    put_pending(555, "ORD7", "stars", "check", "user_x", 100, 500.0, {}, peer_id=555)
    text, checks = orders_text(now=time.time() + 120)
    assert "ORD7" in text and "проверь" in text
    assert checks == ["ORD7"]
