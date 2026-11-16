"""Database connection, schema creation and seed data.

The connection is per-request (stored on Flask's `g`), the schema is created
with CREATE TABLE IF NOT EXISTS only — existing team data is never touched —
and a schema mismatch is a hard stop rather than a confusing runtime error.
"""

import sqlite3
import sys

from flask import g

from config import DB_FILE
from passwords import hash_password

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ADMINS (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT NOT NULL UNIQUE,
    password  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS EMPLOYEES (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    Parent_id  INTEGER NOT NULL,
    username   TEXT NOT NULL,
    password   TEXT NOT NULL,
    CHAT_LOGS  TEXT DEFAULT '[]',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS SETTINGS (
    Parent_id   INTEGER NOT NULL,
    Employee_id INTEGER NOT NULL DEFAULT 0,
    check1      INTEGER NOT NULL DEFAULT 1,
    check2      INTEGER NOT NULL DEFAULT 1,
    check3      INTEGER NOT NULL DEFAULT 1,
    API_KEY     TEXT NOT NULL DEFAULT '',
    MODEL_NAME  TEXT NOT NULL DEFAULT 'gpt-4o-mini',
    PRIMARY KEY (Parent_id, Employee_id)
);
"""

EXPECTED_COLUMNS = {
    "ADMINS": {"id", "username", "password"},
    "EMPLOYEES": {"id", "Parent_id", "username", "password", "CHAT_LOGS"},
    "SETTINGS": {"Parent_id", "Employee_id", "check1", "check2", "check3",
                 "API_KEY", "MODEL_NAME"},
}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_FILE)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def connect():
    """A standalone connection, for code that runs outside a request."""
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    """Create missing tables only. Never touches existing team tables."""
    con = connect()
    con.executescript(SCHEMA_SQL)
    # created_at was added after the first release; add it to live databases.
    cols = {r[1] for r in con.execute("PRAGMA table_info(EMPLOYEES)")}
    if "created_at" not in cols:
        con.execute("ALTER TABLE EMPLOYEES ADD COLUMN created_at TEXT")
    con.commit()
    con.close()


def check_schema():
    con = connect()
    problems = []
    for table, expected in EXPECTED_COLUMNS.items():
        cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
        missing = expected - cols
        if missing:
            problems.append(f"  table {table} is missing columns: {sorted(missing)}")
    con.close()
    if problems:
        sys.exit(
            "Database schema does not match what the app expects ("
            + str(DB_FILE) + "):\n" + "\n".join(problems)
        )


def seed(username="johann", password="admin_secret_123"):
    """Create the demonstration administrator if it does not exist."""
    con = connect()
    row = con.execute(
        "SELECT id FROM ADMINS WHERE username = ?", (username,)
    ).fetchone()
    if row is None:
        con.execute(
            "INSERT INTO ADMINS (username, password) VALUES (?, ?)",
            (username, hash_password(password)),
        )
        con.commit()
        print(f"Created admin {username} / {password}")
    else:
        print(f"Admin {username} already exists.")
    con.close()
