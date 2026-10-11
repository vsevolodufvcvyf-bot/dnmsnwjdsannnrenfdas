import configparser
import glob
import importlib
import os
import threading
import uuid
from types import SimpleNamespace

import pytest

from conftest import FakeTG, ROOT

PLUGIN_FILES = sorted(glob.glob(os.path.join(ROOT, "plugins", "*.py")))
REQUIRED = ["NAME", "VERSION", "DESCRIPTION", "CREDITS", "SETTINGS_PAGE", "UUID", "BIND_TO_DELETE"]


class RegisteringBot:
    """Как telebot: декораторы регистрации и методы отправки, ничего не шлёт в сеть."""

    def __init__(self):
        self.message_handlers = []
        self.callback_handlers = []
        self.sent = []
        self.parse_mode = "HTML"
        self.user = SimpleNamespace(username="test_bot", id=1)

    def message_handler(self, *args, **kwargs):
        def deco(fn):
            self.message_handlers.append((fn, kwargs))
            return fn
        return deco

    def callback_query_handler(self, func=None, **kwargs):
        def deco(fn):
            self.callback_handlers.append((fn, func))
            return fn
        return deco

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.sent.append((name, args, kwargs))
            return SimpleNamespace(chat=SimpleNamespace(id=1), id=1, message_id=1)
        return record


class FakeCardinalTG(FakeTG):
    def __init__(self):
        super().__init__()
        self.bot = RegisteringBot()

    def msg_handler(self, handler, **kwargs):
        self.bot.message_handler(**kwargs)(handler)

    def cbq_handler(self, handler, func, **kwargs):
        self.bot.callback_query_handler(func, **kwargs)(handler)

    def get_state(self, *args, **kwargs):
        return None


def _main_cfg():
    cfg = configparser.ConfigParser()
    cfg.read_dict({
        "FunPay": {"golden_key": "", "autoRaise": "0", "autoDelivery": "0", "autoResponse": "0"},
        "Telegram": {"enabled": "1", "token": "", "proxy": ""},
        "Proxy": {"enable": "0", "proxy": ""},
        "Other": {"watermark": "", "language": "ru"},
    })
    return cfg


def _fake_cardinal():
    commands = {}
    account = SimpleNamespace(
        id=1, username="seller", is_initiated=True, active_sales=0, currency=None,
        get_sales=lambda **kw: (None, [], "ru", {}), method=lambda *a, **k: None,
        get_user=lambda *a, **k: None, get=lambda: None,
    )
    return SimpleNamespace(
        MAIN_CFG=_main_cfg(), account=account, profile=None, curr_profile=None, telegram=FakeCardinalTG(),
        balance=None, lots_ids=[], plugins={}, VERSION="test",
        add_telegram_commands=lambda plugin_uuid, cmds: commands.setdefault(plugin_uuid, []).extend(cmds),
        send_message=lambda *a, **k: True, commands=commands,
    )


def _module(path):
    return importlib.import_module("plugins." + os.path.basename(path)[:-3])


@pytest.mark.parametrize("path", PLUGIN_FILES, ids=os.path.basename)
def test_plugin_has_loader_fields(path):
    mod = _module(path)
    for field in REQUIRED:
        assert hasattr(mod, field), f"{os.path.basename(path)}: нет {field}"
    uuid.UUID(mod.UUID)


def test_plugin_uuids_are_unique():
    seen = {}
    for path in PLUGIN_FILES:
        mod = _module(path)
        assert mod.UUID not in seen, f"{path} и {seen.get(mod.UUID)} с одним UUID"
        seen[mod.UUID] = path


def test_all_init_handlers_run(monkeypatch):
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    card = _fake_cardinal()
    failures = []
    for path in PLUGIN_FILES:
        mod = _module(path)
        for bind in ("BIND_TO_PRE_INIT", "BIND_TO_POST_INIT", "BIND_TO_POST_START"):
            for handler in getattr(mod, bind, []) or []:
                try:
                    handler(card)
                except Exception as ex:
                    failures.append(f"{os.path.basename(path)}.{bind}.{handler.__name__}: {ex!r}")
    assert not failures, "\n".join(failures)
    assert card.telegram.bot.message_handlers, "плагины должны зарегистрировать команды"
    assert card.telegram.bot.callback_handlers
