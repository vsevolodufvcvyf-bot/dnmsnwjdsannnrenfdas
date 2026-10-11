import gzip
import os
import sqlite3
import threading
import time
from types import SimpleNamespace


def test_settings_cache_sees_own_and_external_writes():
    from shop_core.settings import ini_bool, set_ini
    path = "configs/test.cfg"
    set_ini(path, "S", "flag", "1")
    assert ini_bool(path, "S", "flag", False) is True
    set_ini(path, "S", "flag", "0")
    assert ini_bool(path, "S", "flag", True) is False
    time.sleep(0.01)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[S]\nflag = 1\nextra = 1\n")
    assert ini_bool(path, "S", "flag", False) is True


def test_concurrent_set_ini_keeps_all_keys():
    from shop_core.settings import load_ini, set_ini
    path = "configs/race.cfg"

    def worker(n):
        for i in range(20):
            set_ini(path, "S", f"k{n}_{i}", str(i))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    cfg = load_ini(path)
    assert len(cfg["S"]) == 100


def test_backup_includes_wal_transactions(tmp_path):
    from plugins.ops_core import backup_db
    db = str(tmp_path / "live.db")
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA wal_autocheckpoint=0;")
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(50)])
    conn.commit()
    dest = str(tmp_path / "backup.db.gz")
    backup_db(db, dest)
    conn.close()
    restored = str(tmp_path / "restored.db")
    with gzip.open(dest, "rb") as src, open(restored, "wb") as out:
        out.write(src.read())
    assert sqlite3.connect(restored).execute("SELECT COUNT(*) FROM t").fetchone()[0] == 50
    assert not os.path.exists(dest + ".snapshot")


def _frozen(reason="FunPay 401/403 — проверь golden_key"):
    from shop_core import bus
    bus.set_flag("freeze", "1")
    bus.set_flag("freeze_reason", reason)


def test_probe_unfreezes_when_session_works(fake_tg):
    from plugins import ops_core
    from shop_core.bus import is_frozen
    ops_core._LAST_PROBE = 0.0
    _frozen()
    calls = []
    card = SimpleNamespace(telegram=fake_tg, account=SimpleNamespace(get=lambda: calls.append("get")))
    assert ops_core.probe_session(card, now=time.time()) is True
    assert not is_frozen()
    assert calls == ["get"]
    assert "снята автоматически" in fake_tg.notifications[-1][0]


def test_probe_keeps_freeze_when_session_dead(fake_tg):
    from plugins import ops_core
    from shop_core.bus import is_frozen
    ops_core._LAST_PROBE = 0.0
    _frozen()

    def dead():
        raise RuntimeError("401")

    card = SimpleNamespace(telegram=fake_tg, account=SimpleNamespace(get=dead))
    now = time.time()
    assert ops_core.probe_session(card, now=now) is False
    assert is_frozen()
    assert ops_core.probe_session(card, now=now + 60) is False, "не чаще probe_every_min"


def test_probe_never_lifts_manual_panic(fake_tg):
    from plugins import ops_core
    from shop_core.bus import is_frozen
    from shop_core.settings import set_flag
    ops_core._LAST_PROBE = 0.0
    set_flag("Ops", "panic", "1")
    _frozen("аварийный стоп")
    card = SimpleNamespace(telegram=fake_tg, account=SimpleNamespace(get=lambda: None))
    assert ops_core.probe_session(card, now=time.time()) is False
    assert is_frozen()
