from types import SimpleNamespace


def test_version_compare():
    from shop_core.upstream import is_newer
    assert is_newer("v0.1.17.16", "0.1.17.15")
    assert is_newer("v0.1.18", "0.1.17.15")
    assert not is_newer("v0.1.17.15", "0.1.17.15")
    assert not is_newer("v0.1.17.9", "0.1.17.15")
    assert not is_newer("", "0.1.17.15")


def test_notifies_once_per_new_release(fake_tg):
    from shop_core.upstream import check_and_notify, status_line
    card = SimpleNamespace(telegram=fake_tg)
    assert check_and_notify(card, tag="v0.1.17.15") is None
    assert check_and_notify(card, tag="v0.1.18.0") == "v0.1.18.0"
    assert check_and_notify(card, tag="v0.1.18.0") == "v0.1.18.0"
    assert len(fake_tg.notifications) == 1
    assert "есть новее" in status_line()
