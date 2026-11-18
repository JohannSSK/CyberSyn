"""Administrator sessions.

The ADMIN_SESSIONS table and the routes that let a browser restore or end an
administrator session. The token hashing, expiry check and lookup live in
`auth.py` alongside the team-member sessions, so there is one implementation
of "is this token still valid".
"""

import secrets
from contextlib import closing
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from auth import ADMIN_COOKIE, PAGE_COOKIE, SESSION_DAYS, _connect, _hash, cookie_token
from config import ROUTES

TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS ADMIN_SESSIONS ("
    "token_hash TEXT PRIMARY KEY, "
    "admin_id INTEGER NOT NULL, "
    "expires_at TEXT NOT NULL, purpose TEXT NOT NULL DEFAULT 'session')"
)

admin_session_api = Blueprint("admin_session_api", __name__)


def init_table(db_file):
    con = _connect(db_file)
    con.execute("BEGIN IMMEDIATE")
    con.execute(TABLE_SQL)
    if "purpose" not in {r[1] for r in con.execute("PRAGMA table_info(ADMIN_SESSIONS)")}:
        con.execute("ALTER TABLE ADMIN_SESSIONS ADD COLUMN purpose TEXT NOT NULL DEFAULT 'session'")
    con.commit()
    con.close()


# Every privileged action asks for the password again, and each answer mints
# a session. Cap them per administrator so a week of overrides cannot leave
# thousands of live tokens behind, and drop expired rows while we are here.
MAX_SESSIONS_PER_ADMIN = 20


def create_session(db_file, admin_id, purpose="session", con=None):
    if con is None:
        with closing(_connect(db_file)) as con, con:
            return create_session(db_file, admin_id, purpose, con)
    lifetime = {"session": timedelta(days=SESSION_DAYS), "approval_once": timedelta(minutes=5),
                "approval_page": timedelta(minutes=15)}[purpose]
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    con.execute("DELETE FROM ADMIN_SESSIONS WHERE expires_at <= ?", (now.isoformat(),))
    con.execute("INSERT INTO ADMIN_SESSIONS (token_hash, admin_id, expires_at, purpose) VALUES (?,?,?,?)",
                (_hash(token), admin_id, (now + lifetime).isoformat(), purpose))
    con.execute("DELETE FROM ADMIN_SESSIONS WHERE rowid IN (SELECT rowid FROM ADMIN_SESSIONS "
                "WHERE admin_id=? AND (purpose='session')=? ORDER BY rowid DESC LIMIT -1 OFFSET ?)",
                (admin_id, purpose == "session", MAX_SESSIONS_PER_ADMIN))
    return token


def revoke(db_file, token):
    """End one session. Safe to call with a missing or malformed token."""
    if not isinstance(token, str) or not token.strip():
        return False
    con = _connect(db_file)
    cur = con.execute(
        "DELETE FROM ADMIN_SESSIONS WHERE token_hash = ?", (_hash(token.strip()),)
    )
    con.commit()
    changed = cur.rowcount > 0
    con.close()
    return changed


def register(app):
    app.register_blueprint(admin_session_api)


@admin_session_api.post(ROUTES["ADMIN_SESSION"])
def restore():
    """Tell the browser whether a remembered admin token is still good."""
    from auth import admin_from_token
    from config import DB_FILE

    data = request.get_json(silent=True)
    token = data.get("token") if isinstance(data, dict) else None
    admin = admin_from_token(DB_FILE, token)
    if admin is None:
        return jsonify({"success": False}), 401
    return jsonify({
        "success": True,
        "Parent_id": str(admin["id"]),
        "username": admin["username"],
    })


@admin_session_api.post(ROUTES["ADMIN_LOGOUT"])
def logout():
    from config import DB_FILE

    data = request.get_json(silent=True)
    token = data.get("token") if isinstance(data, dict) else None
    page_only = isinstance(data, dict) and data.get("scope") == "page"
    cookies = (PAGE_COOKIE,) if page_only else (ADMIN_COOKIE, PAGE_COOKIE)
    if token is not None:
        revoke(DB_FILE, token)
    else:
        for name in cookies:
            revoke(DB_FILE, cookie_token(None, name))
    response = jsonify({"success": True})
    for name in cookies:
        response.delete_cookie(name)
    return response
