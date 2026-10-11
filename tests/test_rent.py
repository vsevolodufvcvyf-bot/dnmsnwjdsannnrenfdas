import json
import os
import time
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("desc, amount, hours", [
    ("[rent: 3h] Аренда CS2 Prime 2500 часов", 1, 3),
    ("Аренда CS2 Prime | 2500 часов в игре | 1 час аренды", 1, 1),
    ("Аренда аккаунта Dota 2 на 2 часа", 2, 4),
    ("Аккаунт CS2 Prime | 5000 ч. | на 3 часа", 1, 3),
    ("Аренда Steam на сутки", 1, 24),
    ("Аренда GTA 5, срок: 2 дня", 1, 48),
])
def test_rent_duration_found(desc, amount, hours):
    from plugins.steam_autorent_mafile import parse_rent_duration
    seconds, how = parse_rent_duration(desc, amount)
    assert seconds == hours * 3600, how


@pytest.mark.parametrize("desc", [
    "Аренда CS2 Prime | 2500 часов",
    "Аренда Dota 2 | 5000 ч. | Immortal",
    "Аренда аккаунта Rust",
])
def test_rent_duration_unknown_goes_manual(desc):
    from plugins.steam_autorent_mafile import parse_rent_duration
    seconds, why = parse_rent_duration(desc, 1)
    assert seconds is None and why


def test_rent_duration_cap():
    from plugins.steam_autorent_mafile import parse_rent_duration
    seconds, why = parse_rent_duration("[rent: 30d] Аренда", 1, max_hours=336)
    assert seconds is None and "лимит" in why


def _add_slot(account_id=1, password="pass123", needs_reset=0):
    from shop_core.db import get_db
    with get_db() as conn:
        conn.execute(
            """INSERT INTO mafile_rentals (account_id, account_name, login, password, shared_secret, lot_keywords, needs_reset)
               VALUES (?, ?, ?, ?, ?, '[]', ?)""",
            (account_id, f"acc{account_id}", f"login{account_id}", password, "c2VjcmV0c2VjcmV0", needs_reset),
        )


def test_expired_rent_locks_slot_until_reset(monkeypatch, fake_tg):
    from plugins import steam_autorent_mafile as rent
    _add_slot(1)
    assert rent.reserve_account(1, 3600, 555, "buyer", "ORD1", "users-1-2")
    sent = []
    card = SimpleNamespace(telegram=fake_tg)
    monkeypatch.setattr(rent, "bot_send", lambda c, chat, text, name=None: sent.append(text))
    rent.release_expired(card, now=time.time() + 7200)
    assert rent.free_accounts_for_order("cs2") == []
    assert not rent.reserve_account(1, 3600, 556, "next", "ORD2")
    text, kb, _ = fake_tg.notifications[-1]
    assert "/rentpass 1" in text
    assert any("MA_RENT:reset:1" == b.callback_data for row in kb.keyboard for b in row)
    assert rent.set_rent_password(1, "newpass")
    assert [a["account_id"] for a in rent.free_accounts_for_order("cs2")] == [1]


def test_slot_without_password_is_not_offered():
    from plugins import steam_autorent_mafile as rent
    _add_slot(2, password="")
    assert rent.free_accounts_for_order("") == []


def test_seed_from_mafiles(tmp_path):
    from plugins import steam_autorent_mafile as rent
    os.makedirs("mafiles", exist_ok=True)
    payload = {"account_name": "rent_acc", "shared_secret": "c2VjcmV0", "identity_secret": "x",
               "Session": {"SteamID": 76561190000000001}}
    with open("mafiles/76561190000000001.maFile", "w", encoding="utf-8") as f:
        json.dump(payload, f)
    assert rent.seed_from_mafiles() == 1
    assert rent.seed_from_mafiles() == 0
    assert rent.free_accounts_for_order("") == []


def test_guard_code_limit(monkeypatch, fake_tg):
    from FunPayAPI.common.enums import MessageTypes
    from plugins import steam_autorent_mafile as rent
    from shop_core.settings import set_ini
    set_ini(rent.CONFIG_FILE, "AutoRent", "max_codes_per_rent", "2")
    _add_slot(3)
    assert rent.reserve_account(3, 3600, 555, "buyer", "ORD3")
    replies = []
    monkeypatch.setattr(rent, "bot_send", lambda c, chat, text, name=None: replies.append(text))
    card = SimpleNamespace(telegram=fake_tg, account=SimpleNamespace(id=1))
    msg = SimpleNamespace(author_id=555, by_bot=False, text="код", chat_id=555, chat_name="buyer",
                          interlocutor_id=555, type=MessageTypes.NON_SYSTEM)
    for _ in range(4):
        rent._handle_guard_msg(card, SimpleNamespace(message=msg))
    assert sum("код Steam Guard" in r for r in replies) == 2
    assert "Лимит кодов" in replies[-1]
    assert sum("лимит кодов" in n[0] for n in fake_tg.notifications) == 1
