import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

SESSION_DAYS = 7
TABLE_SQL = "CREATE TABLE IF NOT EXISTS ADMIN_SESSIONS (token_hash TEXT PRIMARY KEY, admin_id INTEGER NOT NULL, expires_at TEXT NOT NULL)"


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _connect(db_file):
    con = sqlite3.connect(db_file)
    con.row_factory = sqlite3.Row
    return con


def init_table(db_file):
    con = _connect(db_file)
    con.execute(TABLE_SQL)
    con.commit()
    con.close()


def create_session(db_file, admin_id):
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    con = _connect(db_file)
    con.execute(
        "INSERT INTO ADMIN_SESSIONS (token_hash, admin_id, expires_at) VALUES (?, ?, ?)",
        (_hash(token), admin_id, expires.isoformat()),
    )
    con.commit()
    con.close()
    return token


def register(app, db_file):
    @app.post("/api/admin/session")
    def admin_session_restore():
        data = request.get_json(silent=True)
        token = data.get("token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token.strip():
            return jsonify({"success": False}), 401
        digest = _hash(token.strip())
        con = _connect(db_file)
        row = con.execute(
            "SELECT a.id, a.username, s.expires_at FROM ADMIN_SESSIONS s "
            "JOIN ADMINS a ON a.id = s.admin_id WHERE s.token_hash = ?",
            (digest,),
        ).fetchone()
        if row is not None and datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            con.execute("DELETE FROM ADMIN_SESSIONS WHERE token_hash = ?", (digest,))
            con.commit()
            row = None
        con.close()
        if row is None:
            return jsonify({"success": False}), 401
        return jsonify({"success": True, "Parent_id": str(row["id"]), "username": row["username"]})

    @app.post("/api/admin/logout")
    def admin_session_logout():
        data = request.get_json(silent=True)
        token = data.get("token") if isinstance(data, dict) else None
        if isinstance(token, str) and token.strip():
            con = _connect(db_file)
            con.execute("DELETE FROM ADMIN_SESSIONS WHERE token_hash = ?", (_hash(token.strip()),))
            con.commit()
            con.close()
        return jsonify({"success": True})
