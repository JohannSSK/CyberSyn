"""Administrator sessions.

The ADMIN_SESSIONS table and the routes that let a browser restore or end an
administrator session. The token hashing, expiry check and lookup live in
`auth.py` alongside the team-member sessions, so there is one implementation
of "is this token still valid".
"""

import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from auth import _connect, _hash

SESSION_DAYS = 7
TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS ADMIN_SESSIONS ("
    "token_hash TEXT PRIMARY KEY, "
    "admin_id INTEGER NOT NULL, "
    "expires_at TEXT NOT NULL)"
)

admin_session_api = Blueprint("admin_session_api", __name__)


def init_table(db_file):
    con = _connect(db_file)
    con.execute(TABLE_SQL)
    con.commit()
    con.close()


def create_session(db_file, admin_id):
    """Issue a token for an administrator and return it (once)."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    con = _connect(db_file)
    con.execute(
        "INSERT INTO ADMIN_SESSIONS (token_hash, admin_id, expires_at) "
        "VALUES (?, ?, ?)",
        (_hash(token), admin_id, expires.isoformat()),
    )
    con.commit()
    con.close()
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


@admin_session_api.post("/api/admin/session")
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


@admin_session_api.post("/api/admin/logout")
def logout():
    from config import DB_FILE

    data = request.get_json(silent=True)
    token = data.get("token") if isinstance(data, dict) else None
    revoke(DB_FILE, token)
    return jsonify({"success": True})
