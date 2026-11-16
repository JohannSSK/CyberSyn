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
    PROVIDER    TEXT NOT NULL DEFAULT 'auto',
    API_BASE    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (Parent_id, Employee_id)
);
"""

EXPECTED_COLUMNS = {
    "ADMINS": {"id", "username", "password"},
    "EMPLOYEES": {"id", "Parent_id", "username", "password", "CHAT_LOGS"},
    "SETTINGS": {"Parent_id", "Employee_id", "check1", "check2", "check3",
                 "API_KEY", "MODEL_NAME", "PROVIDER", "API_BASE"},
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
    _add_settings_columns(con)
    con.commit()
    con.close()


# Columns added after the first release. CREATE TABLE IF NOT EXISTS never
# touches a table that exists, so live databases need the ALTER.
SETTINGS_MIGRATIONS = {
    "PROVIDER": "TEXT NOT NULL DEFAULT 'auto'",
    "API_BASE": "TEXT NOT NULL DEFAULT ''",
}


def _add_settings_columns(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(SETTINGS)")}
    for name, definition in SETTINGS_MIGRATIONS.items():
        if name not in cols:
            con.execute(f"ALTER TABLE SETTINGS ADD COLUMN {name} {definition}")


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


def seed(username=None, password=None):
    """Create one administrator.

    There is no default account. A gateway that ships with a known
    username and password is a gateway anyone can sign in to, so both have
    to be supplied — by argument, or by CYBERSYN_SEED_USERNAME and
    CYBERSYN_SEED_PASSWORD. Given a username but no password, a random one
    is generated and printed once.
    """
    import os
    import secrets

    username = username or os.environ.get("CYBERSYN_SEED_USERNAME")
    password = password or os.environ.get("CYBERSYN_SEED_PASSWORD")
    if not username:
        print(
            "Refusing to create an account with a default username.\n"
            "  python3 src/app.py seed <username> [password]\n"
            "  CYBERSYN_SEED_USERNAME=... CYBERSYN_SEED_PASSWORD=... "
            "python3 src/app.py seed",
            file=sys.stderr,
        )
        return 1

    generated = False
    if not password:
        password = secrets.token_urlsafe(18)
        generated = True

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
        print(f"Created admin '{username}'.")
    else:
        print(f"Admin '{username}' already exists.")
        con.close()
        return 0
    con.close()
    if generated:
        print(f"Generated password (shown once): {password}")
    return 0
