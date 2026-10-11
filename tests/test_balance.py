from types import SimpleNamespace

from FunPayAPI.types import Balance


def _card(balance):
    return SimpleNamespace(balance=balance, account=SimpleNamespace(active_sales=0))


def test_balance_source_values():
    from plugins.balance_monitor import balance_source
    exact = Balance(100, 80, 0, 0, 0, 0)
    approx = Balance(100, 100, 0, 0, 0, 0)
    approx.source = "approx"
    assert balance_source(None) == "unknown"
    assert balance_source(exact) == "exact"
    assert balance_source(approx) == "approx"


def test_wallet_text_does_not_show_fake_zero():
    from plugins.balance_monitor import get_balance_text
    unknown = Balance(0, 0, 0, 0, 0, 0)
    unknown.source = "unknown"
    text = get_balance_text(_card(unknown))
    assert "не отдал баланс" in text and "Можно вывести" not in text


def test_wallet_text_exact_shows_available_and_held():
    from plugins.balance_monitor import get_balance_text
    text = get_balance_text(_card(Balance(100, 80, 0, 0, 0, 0)))
    assert "80.00" in text and "20.00" in text
