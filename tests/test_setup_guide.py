from types import SimpleNamespace

from shop_core.db import get_db


def test_robux_guide_hides_key_and_stays_off_until_enabled():
    from shop_core.panels import load_suppliers_cfg
    from shop_core.setup_guide import apply_action, apply_text, begin, load, price_advice, screen
    run = begin(7, "robux", "gamepass")
    section = run["section"]
    assert load_suppliers_cfg()[section].getboolean("enabled") is False
    assert apply_action(7, "next")[0] is True
    assert apply_action(7, "next")[0] is True
    assert load(7)["step"] == "url"
    ok, _text, wipe = apply_text(7, "https://panel.example/api/v2")
    assert ok and wipe is False
    secret = "super-secret-key"
    ok, shown, wipe = apply_text(7, secret)
    assert ok and wipe is True
    assert secret not in shown
    assert secret not in screen(load(7))
    with get_db() as conn:
        blob = " ".join(str(dict(row)) for row in conn.execute("SELECT * FROM setup_wizard"))
    assert secret not in blob
    assert apply_text(7, "55")[0] is True
    assert apply_action(7, "unit_piece")[0] is True
    assert apply_text(7, "1.5")[0] is True
    assert load(7)["step"] == "floor"
    low_ok, low_text = price_advice(1.5, 1.0)
    assert low_ok is False and "не уйдёт" in low_text
    assert apply_text(7, "1")[0] is False
    assert load(7)["step"] == "floor"
    assert apply_action(7, "next")[0] is True
    lot = screen(load(7))
    assert "Автовыдачу" in lot and "не включай" in lot
    assert "Game Pass" in lot
    assert apply_action(7, "next")[0] is True
    assert load(7)["step"] == "enable"
    assert load_suppliers_cfg()[section].getboolean("enabled") is False
    assert apply_action(7, "enable")[0] is True
    assert load_suppliers_cfg()[section].getboolean("enabled") is True
    high_ok, high_text = price_advice(1.5, 100)
    assert high_ok is True and "x" in high_text


def test_file_guide_does_not_enable_autodelivery():
    from shop_core.setup_guide import apply_action, begin, screen
    run = begin(8, "steam", "file")
    assert run["section"] is None
    text = screen(run)
    assert "storage/products" in text
    assert apply_action(8, "next")[0] is True
    bind = screen(begin(8, "steam", "file"))
    # повторный заход продолжает тот же шаг
    assert "Автовыдач" in bind
    assert "включаешь ты" in bind


def test_buyer_prompts_for_steam_and_robux():
    from shop_core.confirm import _explicit_correction, _parse_target, ask_target
    sent = []

    def send_message(chat_id, text, *args, **kwargs):
        sent.append(text)

    card = SimpleNamespace(send_message=send_message)
    ask_target(card, 1, "steam")
    ask_target(card, 1, "robux")
    assert "логин Steam" in sent[0] and "пароля" in sent[0]
    assert "Roblox" in sent[1] and "Game Pass" in sent[1]
    assert _parse_target("robux", "@PlayerOne") == "PlayerOne"
    assert _parse_target("steam", "mysteam") == "mysteam"
    assert _explicit_correction("robux", "ник PlayerOne") == "PlayerOne"
