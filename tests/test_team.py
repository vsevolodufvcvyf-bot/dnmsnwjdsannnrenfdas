import configparser

from conftest import make_callback, make_message
from shop_core import team


def test_no_owner_means_nobody_is_owner():
    assert team.owner_id() == 0
    assert team.is_owner(123456789) is False
    assert team.extra_ids() == set()


def test_owner_from_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "111")
    assert team.owner_id() == 111
    assert team.is_owner(111)
    assert not team.is_owner(222)
    assert 111 in team.extra_ids()


def test_owner_from_team_cfg_when_env_missing():
    cfg = configparser.ConfigParser()
    cfg["Team"] = {"usernames": "", "ids": "", "owner_id": "333"}
    team.save_team(cfg)
    assert team.owner_id() == 333


def test_invited_username_does_not_grant_access(monkeypatch, fake_tg):
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "111")
    assert team.invite_username("@helper_one")
    granted = team.try_authorize_message(fake_tg, make_message(555, "helper_one"))
    assert granted is False
    assert 555 not in fake_tg.authorized_users
    owner_msgs = [s for s in fake_tg.bot.sent if s[0] == 111]
    assert owner_msgs, "владелец должен получить запрос"
    kb = owner_msgs[0][2]["reply_markup"]
    datas = [b.callback_data for row in kb.keyboard for b in row]
    assert "TEAM:ok:555" in datas and "TEAM:no:555" in datas


def test_someone_else_with_same_username_cannot_self_approve(monkeypatch, fake_tg):
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "111")
    team.invite_username("helper_one")
    team.try_authorize_message(fake_tg, make_message(555, "helper_one"))
    team.handle_decision(fake_tg, make_callback(555, "TEAM:ok:555"))
    assert 555 not in fake_tg.authorized_users


def test_owner_approves_invite(monkeypatch, fake_tg):
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "111")
    team.invite_username("helper_one")
    team.try_authorize_message(fake_tg, make_message(555, "helper_one"))
    team.handle_decision(fake_tg, make_callback(111, "TEAM:ok:555"))
    assert 555 in fake_tg.authorized_users
    assert 555 in team.extra_ids()
    assert "helper_one" not in team.invited_usernames()


def test_owner_rejects_invite(monkeypatch, fake_tg):
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "111")
    team.invite_username("helper_one")
    team.try_authorize_message(fake_tg, make_message(555, "helper_one"))
    team.handle_decision(fake_tg, make_callback(111, "TEAM:no:555"))
    assert 555 not in fake_tg.authorized_users


def test_numeric_operator_id_is_granted(monkeypatch, fake_tg):
    monkeypatch.setenv("TELEGRAM_OPERATORS", "777, @legacy_nick")
    assert team.try_authorize_message(fake_tg, make_message(777, "whoever"))
    assert 777 in fake_tg.authorized_users
    assert team.try_authorize_message(fake_tg, make_message(888, "legacy_nick")) is False
    assert 888 not in fake_tg.authorized_users


def test_approval_request_is_rate_limited(monkeypatch, fake_tg):
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "111")
    team.invite_username("helper_two")
    team._LAST_REQUEST.clear()
    team.try_authorize_message(fake_tg, make_message(556, "helper_two"))
    team.try_authorize_message(fake_tg, make_message(556, "helper_two"))
    owner_msgs = [s for s in fake_tg.bot.sent if s[0] == 111]
    assert len(owner_msgs) == 1
