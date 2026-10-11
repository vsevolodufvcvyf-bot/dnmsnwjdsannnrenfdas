import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    """Каждый тест — в пустой папке: конфиги, база и кэш создаются там, а не в репозитории."""
    monkeypatch.chdir(tmp_path)
    for var in ("TELEGRAM_OWNER_ID", "TELEGRAM_OPERATORS", "OPENROUTER_KEY", "YANDEX_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    os.makedirs("configs", exist_ok=True)
    os.makedirs(os.path.join("storage", "cache"), exist_ok=True)
    from shop_core import db
    db.init_db()
    from shop_core import settings
    clear = getattr(settings, "clear_cache", None)
    if clear:
        clear()
    yield tmp_path


class FakeBot:
    def __init__(self):
        self.sent = []
        self.answers = []

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))
        return SimpleNamespace(chat=SimpleNamespace(id=chat_id), id=len(self.sent))

    def edit_message_text(self, text, chat_id, message_id, **kwargs):
        self.sent.append((chat_id, text, kwargs))

    def answer_callback_query(self, *args, **kwargs):
        self.answers.append((args, kwargs))

    def delete_message(self, *args, **kwargs):
        pass


class FakeTG:
    def __init__(self):
        self.bot = FakeBot()
        self.authorized_users = {}
        self.notification_settings = {}
        self.notifications = []

    def send_notification(self, text, keyboard=None, notification_type=None, photo=None, pin=False):
        self.notifications.append((text, keyboard, notification_type))


@pytest.fixture
def fake_tg():
    return FakeTG()


def make_message(user_id, username=None, text="/menu", chat_type="private"):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id, username=username, language_code="ru"),
        chat=SimpleNamespace(id=user_id, type=chat_type),
        text=text,
    )


def make_callback(user_id, data, chat_id=None):
    return SimpleNamespace(
        id="cb1",
        data=data,
        from_user=SimpleNamespace(id=user_id, username=None),
        message=SimpleNamespace(chat=SimpleNamespace(id=chat_id or user_id), id=1),
    )
