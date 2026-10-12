import configparser
from types import SimpleNamespace

from conftest import make_callback, make_message


def _cardinal():
    cfg = configparser.ConfigParser()
    cfg.read_dict({
        "FunPay": {"golden_key": "", "user_agent": "", "autoRaise": "0"},
        "Telegram": {"enabled": "1", "token": "123456789:AAFakeTokenForOfflineTestsOnly_abcdefgh",
                     "proxy": "", "secretKeyHash": "", "blockLogin": "0"},
        "Other": {"language": "ru", "watermark": ""},
    })
    return SimpleNamespace(MAIN_CFG=cfg, VERSION="test", block_tg_login=False, old_mode_enabled=False)


def test_tgbot_registers_handlers_offline():
    from tg_bot.bot import TGBot
    tg = TGBot(_cardinal())
    tg.init()
    handlers = tg.bot.callback_query_handlers
    assert any(h["filters"].get("func") and h["filters"]["func"](make_callback(1, "TEAM:ok:2"))
               for h in handlers if h["filters"].get("func")), "кнопки команды должны быть зарегистрированы"
    assert getattr(tg.bot, "_safe_html_installed", False)


def test_setup_commands_uses_valid_names(monkeypatch):
    import re

    from tg_bot.bot import TGBot
    tg = TGBot(_cardinal())
    captured = {}
    monkeypatch.setattr(tg.bot, "delete_my_commands", lambda *a, **k: None)
    monkeypatch.setattr(tg.bot, "set_my_commands", lambda cmds, *a, **k: captured.setdefault("cmds", cmds))
    tg.setup_commands()
    names = [c.command for c in captured["cmds"]]
    assert len(names) == len(set(names)) <= 100
    assert all(re.fullmatch(r"[a-z0-9_]{1,32}", n) for n in names), names
    assert {"orders", "stuck", "calc", "rentpass", "day", "goal", "hours", "lottext"} <= set(names)


def test_unauthorized_click_by_invited_username_only_requests(monkeypatch):
    from shop_core import team
    from tg_bot.bot import TGBot
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "111")
    team.invite_username("helper_one")
    tg = TGBot(_cardinal())
    sent = []
    monkeypatch.setattr(tg.bot, "send_message", lambda chat_id, text, *a, **k: sent.append((chat_id, text)))
    monkeypatch.setattr(tg.bot, "answer_callback_query", lambda *a, **k: None)
    c = make_callback(555, "anything")
    c.from_user.username = "helper_one"
    c.message.chat.username = None
    tg.ignore_unauthorized_users(c)
    assert 555 not in tg.authorized_users
    assert any(chat == 111 for chat, _ in sent), "запрос ушёл владельцу"


def test_message_from_invited_username_is_not_authorized(monkeypatch):
    from shop_core import team
    from tg_bot.bot import TGBot
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "111")
    team.invite_username("helper_two")
    team._LAST_REQUEST.clear()
    tg = TGBot(_cardinal())
    monkeypatch.setattr(tg.bot, "send_message", lambda *a, **k: None)
    tg.authorize_team_mdw(tg.bot, make_message(556, "helper_two"))
    assert 556 not in tg.authorized_users
