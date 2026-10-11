from types import SimpleNamespace


def test_review_bonus_disabled_once_then_respects_choice(fake_tg):
    from plugins import review_manager as rm
    from shop_core.settings import ini_bool, set_ini
    set_ini(rm.CONFIG_FILE, "Review", "bonus_hour", "1")
    card = SimpleNamespace(telegram=fake_tg)
    rm._disable_bonus_once(card)
    assert ini_bool(rm.CONFIG_FILE, "Review", "bonus_hour", False) is False
    assert len(fake_tg.notifications) == 1

    rm._toggle_bonus(None)
    assert rm._bonus_on() is True
    rm._disable_bonus_once(card)
    assert rm._bonus_on() is True, "владелец включил сам — больше не выключаем"
    assert len(fake_tg.notifications) == 1
