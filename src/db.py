"""Database connection, schema creation and seed data.

The connection is per-request (stored on Flask's `g`), additive schema migrations preserve team accounts,
and old prompt previews are removed from the live audit trail on upgrade.
"""

import logging
import sqlite3
import sys

from flask import g

from config import DB_FILE
from passwords import admin_password_problem, hash_password
from policy import ACTION_FIELDS, DEFAULT_FLAGS, legacy_action

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
    created_at TEXT,
    UNIQUE (Parent_id, username)
);
CREATE TABLE IF NOT EXISTS SETTINGS (
    Parent_id   INTEGER NOT NULL,
    Employee_id INTEGER NOT NULL DEFAULT 0,
    check1      INTEGER NOT NULL DEFAULT 1,
    check2      INTEGER NOT NULL DEFAULT 1,
    check3      INTEGER NOT NULL DEFAULT 1,
    block_code  INTEGER NOT NULL DEFAULT 0,
    API_KEY     TEXT NOT NULL DEFAULT '',
    MODEL_NAME  TEXT NOT NULL DEFAULT 'gpt-4o-mini',
    PROVIDER    TEXT NOT NULL DEFAULT 'auto',
    API_BASE    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (Parent_id, Employee_id)
);
CREATE TABLE IF NOT EXISTS AI_TOOL_POLICY (
    Parent_id  INTEGER NOT NULL REFERENCES ADMINS(id) ON DELETE CASCADE,
    tool_key   TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('approved', 'restricted', 'unapproved')),
    note       TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 240),
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    domain     TEXT,
    name       TEXT,
    PRIMARY KEY (Parent_id, tool_key),
    UNIQUE (Parent_id, domain)
);
CREATE TABLE IF NOT EXISTS DISCOVERY_EVENTS (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    Parent_id   INTEGER NOT NULL REFERENCES ADMINS(id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    team        TEXT NOT NULL CHECK (length(team) <= 64),
    actor       TEXT NOT NULL CHECK (length(actor) <= 64),
    host        TEXT NOT NULL,
    tool_key    TEXT NOT NULL,
    tool_name   TEXT NOT NULL,
    method      TEXT NOT NULL,
    bytes_sent  INTEGER NOT NULL CHECK (bytes_sent >= 0),
    data_signal TEXT NOT NULL,
    imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_discovery_workspace_time ON DISCOVERY_EVENTS (Parent_id, observed_at DESC, id DESC);
"""

EXPECTED_COLUMNS = {
    "ADMINS": {"id", "username", "password"},
    "EMPLOYEES": {"id", "Parent_id", "username", "password", "CHAT_LOGS"},
    "SETTINGS": {"Parent_id", "Employee_id", "check1", "check2", "check3",
                 "block_code", "API_KEY", "MODEL_NAME", "PROVIDER", "API_BASE",
                 *ACTION_FIELDS.values(), "restore_redactions"},
    "AI_TOOL_POLICY": {"Parent_id", "tool_key", "status", "note", "updated_at", "updated_by", "domain", "name"},
    "DISCOVERY_EVENTS": {"id", "Parent_id", "observed_at", "team", "actor", "host", "tool_key",
                         "tool_name", "method", "bytes_sent", "data_signal", "imported_at"},
}


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def connect(db_file=None):
    """A standalone connection, for code that runs outside a request."""
    con = sqlite3.connect(db_file or DB_FILE, timeout=10.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 10000")
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA synchronous = NORMAL")
    return con


def init_db():
    """Initialize the database and migrate older installations in place."""
    con = connect()
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript("BEGIN IMMEDIATE;\n" + SCHEMA_SQL)
    # created_at was added after the first release; add it to live databases.
    cols = {r[1] for r in con.execute("PRAGMA table_info(EMPLOYEES)")}
    if "created_at" not in cols:
        con.execute("ALTER TABLE EMPLOYEES ADD COLUMN created_at TEXT")
    _add_settings_columns(con)
    try:
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_employees_parent_username "
                    "ON EMPLOYEES (Parent_id, username)")
    except sqlite3.IntegrityError:
        logging.getLogger(__name__).warning("Duplicate legacy member names; resolve duplicates to enable unique index.")
    # Old releases stored prompt prefixes in the activity timeline. Remove
    # those details on upgrade, without deleting events or future safe metadata.
    if con.execute("PRAGMA user_version").fetchone()[0] == 0:
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='ACTIVITY_LOG'").fetchone():
            con.execute("UPDATE ACTIVITY_LOG SET detail=NULL WHERE kind IN "
                        "('blocked','override','prompt','regenerated','message_edited')")
        con.execute("PRAGMA user_version = 1")
    con.commit()
    con.close()


# Columns added after the first release. CREATE TABLE IF NOT EXISTS never
# touches a table that exists, so live databases need the ALTER.
SETTINGS_MIGRATIONS = {
    "block_code": "INTEGER NOT NULL DEFAULT 0",
    "PROVIDER": "TEXT NOT NULL DEFAULT 'auto'",
    "API_BASE": "TEXT NOT NULL DEFAULT ''",
    **{column: f"TEXT NOT NULL DEFAULT '{legacy_action(DEFAULT_FLAGS[flag])}'"
       for flag, column in ACTION_FIELDS.items()},
    "restore_redactions": "INTEGER NOT NULL DEFAULT 0",
}


def _add_settings_columns(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(SETTINGS)")}
    legacy_flags = {column: flag for flag, column in ACTION_FIELDS.items()}
    for name, definition in SETTINGS_MIGRATIONS.items():
        if name not in cols:
            con.execute(f"ALTER TABLE SETTINGS ADD COLUMN {name} {definition}")
            if name in legacy_flags:
                flag = legacy_flags[name]
                con.execute(f"UPDATE SETTINGS SET {name}=CASE WHEN {flag} THEN 'block' ELSE 'allow' END")


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
    password = os.environ.get("CYBERSYN_SEED_PASSWORD") if password is None else password
    if not username:
        print(
            "Refusing to create an account with a default username.\n"
            "  python3 src/app.py seed <username> [password]\n"
            "  CYBERSYN_SEED_USERNAME=... CYBERSYN_SEED_PASSWORD=... "
            "python3 src/app.py seed",
            file=sys.stderr,
        )
        return 1

    username = username.strip()
    if not username or len(username) > 64:
        print("Username must contain 1 to 64 characters.", file=sys.stderr)
        return 1
    generated = password is None
    if generated:
        password = "A1" + secrets.token_urlsafe(18)
    problem = admin_password_problem(password)
    if problem:
        print(problem, file=sys.stderr)
        return 1

    con = connect()
    try:
        with con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT id FROM ADMINS WHERE username = ?", (username,)).fetchone()
            if row is None:
                pid = con.execute("INSERT INTO ADMINS (username, password) VALUES (?, ?)",
                                  (username, hash_password(password))).lastrowid
            else:
                pid = row["id"]
            con.execute("INSERT OR IGNORE INTO SETTINGS (Parent_id, Employee_id) VALUES (?, 0)", (pid,))
    finally:
        con.close()
    print(f"Admin '{username}' already exists." if row else f"Created admin '{username}'.")
    if generated and row is None:
        print(f"Generated password (shown once): {password}")
    return 0
