from Utils.tg_html import LIMIT, install, safe_html, split_message


def test_error_text_with_angle_brackets_is_escaped():
    err = "Caused by NewConnectionError('<urllib3.connection.HTTPSConnection object at 0x7f>: refused')"
    out = safe_html(f"❌ autosmm #A1: {err}")
    assert "<urllib3" not in out
    assert "&lt;urllib3.connection.HTTPSConnection object at 0x7f&gt;" in out


def test_allowed_tags_and_entities_survive():
    text = '<b>Заказ</b> <code>#A1</code> <a href="https://funpay.com/orders/A1/">ссылка</a> &amp; &lt;3'
    assert safe_html(text) == text


def test_user_text_with_ampersand_and_lt():
    out = safe_html("<i>Отзыв:</i> товар топ <3 & быстро")
    assert out == "<i>Отзыв:</i> товар топ &lt;3 &amp; быстро"


def test_unbalanced_tags_fall_back_to_plain_text():
    out = safe_html("<b>жирный без закрытия и <code>код</b>")
    assert "<b>" not in out and "<code>" not in out
    assert "жирный без закрытия" in out


def test_split_respects_limit_and_lines():
    line = "<b>строка</b> " + "x" * 90
    text = "\n".join([line] * 200)
    parts = split_message(text)
    assert len(parts) > 1
    assert all(len(p) <= LIMIT for p in parts)
    assert all(p.count("<b>") == p.count("</b>") for p in parts)


class RecordingBot:
    parse_mode = "HTML"

    def __init__(self):
        self.calls = []

    def send_message(self, chat_id, text, *args, **kwargs):
        self.calls.append(("send", chat_id, text, kwargs))
        return len(self.calls)

    def edit_message_text(self, text, *args, **kwargs):
        self.calls.append(("edit", text, kwargs))

    def send_photo(self, chat_id, photo, caption=None, *args, **kwargs):
        self.calls.append(("photo", chat_id, caption, kwargs))


def test_install_wraps_bot_methods():
    bot = RecordingBot()
    install(bot)
    install(bot)
    bot.send_message(1, "ошибка <Response [500]>", reply_markup="KB")
    kind, chat, text, kwargs = bot.calls[-1]
    assert text == "ошибка &lt;Response [500]&gt;" and kwargs["reply_markup"] == "KB"


def test_long_message_is_split_and_keyboard_goes_last():
    bot = RecordingBot()
    install(bot)
    bot.send_message(1, "\n".join(["строка " * 20] * 100), reply_markup="KB")
    sends = [c for c in bot.calls if c[0] == "send"]
    assert len(sends) > 1
    assert "reply_markup" not in sends[0][3]
    assert sends[-1][3]["reply_markup"] == "KB"


def test_plain_parse_mode_is_untouched():
    bot = RecordingBot()
    install(bot)
    bot.send_message(1, "a < b", parse_mode="")
    assert bot.calls[-1][2] == "a < b"


def test_digest_keeps_rows_until_sent(monkeypatch, fake_tg):
    from types import SimpleNamespace

    from shop_core import bus
    from shop_core.db import get_db
    monkeypatch.setattr(bus, "quiet_hours_now", lambda: True)
    card = SimpleNamespace(telegram=fake_tg)
    for i in range(3):
        bus.notify(card, f"событие {i}", critical=False)
    with get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM notify_digest").fetchone()[0] == 3
    bus.drain_digest(card)
    assert len(fake_tg.notifications) == 1
    assert "событие 0" in fake_tg.notifications[0][0] and "событие 2" in fake_tg.notifications[0][0]
    with get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM notify_digest").fetchone()[0] == 0
