# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager

DB_LOCK = threading.RLock()
DB_FILE = os.path.join("storage", "plugins", "cardinal_storage.db")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db():
    with DB_LOCK:
        conn = _connect()
        conn.execute("PRAGMA journal_mode=WAL;")
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS mafile_rentals (
                account_id INTEGER PRIMARY KEY,
                account_name TEXT,
                login TEXT,
                password TEXT,
                shared_secret TEXT,
                identity_secret TEXT DEFAULT '',
                steamid TEXT DEFAULT '',
                bound_lots TEXT DEFAULT '',
                lot_keywords TEXT DEFAULT '',
                is_rented INTEGER DEFAULT 0,
                renter_chat_id INTEGER,
                renter_name TEXT,
                order_id TEXT,
                duration_seconds INTEGER DEFAULT 7200,
                start_time REAL,
                expire_time REAL,
                warned_15m INTEGER DEFAULT 0
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS processed_orders (
                order_id TEXT NOT NULL,
                plugin_name TEXT NOT NULL,
                processed_at REAL,
                PRIMARY KEY (order_id, plugin_name)
            )
        """)
        _migrate_processed_orders(c)

        c.execute("""
            CREATE TABLE IF NOT EXISTS muted_chats (
                chat_id INTEGER PRIMARY KEY,
                expire_time REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                role TEXT,
                message TEXT,
                created_at REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS processed_messages (
                msg_id TEXT PRIMARY KEY,
                created_at REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS autoback_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT,
                buyer_name TEXT,
                stars INTEGER,
                price REAL,
                currency TEXT,
                review_text TEXT,
                refunded_at REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS smm_orders (
                order_id TEXT PRIMARY KEY,
                service_id INTEGER,
                target_link TEXT,
                task_id TEXT,
                status TEXT,
                created_at REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS bus_chats (
                chat_id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                waiting_input INTEGER DEFAULT 0,
                order_id TEXT,
                updated_at REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS bus_flags (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS finance_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT,
                plugin_name TEXT,
                sale_price REAL,
                cost REAL,
                profit REAL,
                currency TEXT,
                dry_run INTEGER DEFAULT 0,
                created_at REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS notify_digest (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT,
                created_at REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS supplier_orders (
                order_id TEXT NOT NULL,
                plugin_name TEXT NOT NULL,
                provider TEXT,
                task_id TEXT,
                status TEXT,
                created_at REAL,
                PRIMARY KEY (order_id, plugin_name)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS autoprice_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lot_id INTEGER,
                title TEXT,
                old_price REAL,
                new_price REAL,
                floor_price REAL,
                market_min REAL,
                reason TEXT,
                dry_run INTEGER DEFAULT 0,
                created_at REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS withdraw_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount REAL,
                fee_est REAL,
                got REAL,
                way TEXT,
                bank TEXT,
                dest_mask TEXT,
                ok INTEGER,
                error TEXT,
                created_at REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS pending_confirms (
                chat_id INTEGER NOT NULL,
                order_id TEXT NOT NULL,
                kind TEXT,
                step TEXT,
                payload TEXT,
                qty INTEGER,
                sale REAL,
                extra TEXT,
                created_at REAL,
                PRIMARY KEY (chat_id, order_id)
            )
        """)
        _migrate_pending(c)
        _ensure_column(c, "mafile_rentals", "renter_node", "TEXT")
        _ensure_column(c, "mafile_rentals", "needs_reset", "INTEGER DEFAULT 0")
        _ensure_column(c, "mafile_rentals", "codes_given", "INTEGER DEFAULT 0")
        _ensure_column(c, "mafile_rentals", "last_renter", "TEXT")
        c.execute("""
            CREATE TABLE IF NOT EXISTS chat_aliases (
                alias TEXT PRIMARY KEY,
                peer_id INTEGER NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS sale_clock (
                order_id TEXT PRIMARY KEY,
                hour INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS lot_price_anchor (
                lot_id INTEGER PRIMARY KEY,
                base_price REAL NOT NULL,
                created_at REAL
            )
        """)
        _ensure_column(c, "sale_clock", "weekday", "INTEGER")
        c.execute("""
            CREATE TABLE IF NOT EXISTS buyer_seen (
                order_id TEXT PRIMARY KEY,
                buyer TEXT NOT NULL,
                price REAL,
                currency TEXT,
                description TEXT,
                created_at REAL NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS needs_human (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                order_id TEXT,
                reason TEXT NOT NULL,
                detail TEXT,
                status TEXT DEFAULT 'open',
                created_at REAL,
                resolved_at REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS autoback_pending (
                order_id TEXT PRIMARY KEY,
                chat_id TEXT,
                buyer_name TEXT,
                stars INTEGER,
                price REAL,
                currency TEXT,
                review_text TEXT,
                reason TEXT,
                status TEXT DEFAULT 'pending',
                decided_by INTEGER,
                created_at REAL,
                decided_at REAL
            )
        """)
        conn.commit()
        conn.close()


def _ensure_column(c: sqlite3.Cursor, table: str, column: str, decl: str) -> None:
    info = c.execute(f"PRAGMA table_info({table})").fetchall()
    if column not in {row[1] for row in info}:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _migrate_pending(c: sqlite3.Cursor):
    c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='pending_confirms'")
    row = c.fetchone()
    sql = ((row[0] if row else "") or "").replace("\n", " ")
    compact = sql.replace(" ", "")
    if "PRIMARYKEY(chat_id,order_id)" in compact:
        return
    c.execute("ALTER TABLE pending_confirms RENAME TO pending_confirms_old")
    c.execute("""
        CREATE TABLE pending_confirms (
            chat_id INTEGER NOT NULL,
            order_id TEXT NOT NULL,
            kind TEXT,
            step TEXT,
            payload TEXT,
            qty INTEGER,
            sale REAL,
            extra TEXT,
            created_at REAL,
            PRIMARY KEY (chat_id, order_id)
        )
    """)
    c.execute("""
        INSERT OR IGNORE INTO pending_confirms
            (chat_id, order_id, kind, step, payload, qty, sale, extra, created_at)
        SELECT chat_id, COALESCE(order_id, ''), kind, step, payload, qty, sale, extra, created_at
        FROM pending_confirms_old
    """)
    c.execute("DROP TABLE pending_confirms_old")


def _migrate_processed_orders(c: sqlite3.Cursor):
    c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='processed_orders'")
    row = c.fetchone()
    sql = ((row[0] if row else "") or "").replace("\n", " ")
    compact = sql.replace(" ", "")
    if "PRIMARYKEY(order_id,plugin_name)" in compact:
        return
    if "order_id TEXT PRIMARY KEY" in sql:
        c.execute("ALTER TABLE processed_orders RENAME TO processed_orders_old")
        c.execute("""
            CREATE TABLE processed_orders (
                order_id TEXT NOT NULL,
                plugin_name TEXT NOT NULL,
                processed_at REAL,
                PRIMARY KEY (order_id, plugin_name)
            )
        """)
        c.execute("""
            INSERT OR IGNORE INTO processed_orders (order_id, plugin_name, processed_at)
            SELECT order_id, COALESCE(plugin_name, 'legacy'), processed_at FROM processed_orders_old
        """)
        c.execute("DROP TABLE processed_orders_old")


init_db()


@contextmanager
def get_db():
    with DB_LOCK:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
