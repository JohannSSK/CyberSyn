"""Hashed, expiring sessions. Cookies and explicit API tokens share validation."""

import hashlib
import secrets
from contextlib import closing
from datetime import datetime, timedelta, timezone

from flask import has_request_context, make_response, request

from config import _env_flag
from db import connect as _connect
from errors import ApiError
from web import to_int

SESSION_DAYS = 7
MAX_SESSIONS_PER_EMPLOYEE = 10
MEMBER_COOKIE = "cybersyn_member"
ADMIN_COOKIE = "cybersyn_admin"
PAGE_COOKIE = "cybersyn_page"


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def cookie_token(explicit, cookie):
    if explicit is not None or not has_request_context():
        return explicit
    value = request.cookies.get(cookie)
    if value:
        origin = request.headers.get("Origin")
        if (request.headers.get("X-CyberSyn-Request") != "1" or
                (origin is not None and origin != request.host_url.rstrip("/"))):
            raise ApiError("Cookie requests require a same-origin X-CyberSyn-Request header.", 403)
    return value


def session_response(body, cookie, token, status=200, max_age=SESSION_DAYS * 86400):
    # Browser callers do not need a JS-readable copy of the bearer credential.
    if request.headers.get("X-CyberSyn-Session") != "cookie":
        body["admin_token" if cookie == PAGE_COOKIE else "session_token"] = token
    response = make_response(body, status)
    response.set_cookie(cookie, token, max_age=max_age, httponly=True, samesite="Lax",
                        secure=request.is_secure or _env_flag("CYBERSYN_COOKIE_SECURE"), path="/")
    return response


def init_tables(db_file):
    with closing(_connect(db_file)) as con, con:
        con.execute("CREATE TABLE IF NOT EXISTS EMPLOYEE_SESSIONS (token_hash TEXT PRIMARY KEY, "
                    "Parent_id INTEGER NOT NULL, Employee_id INTEGER NOT NULL, expires_at TEXT NOT NULL)")


def create_employee_session(db_file, parent_id, employee_id, con=None):
    if con is None:
        with closing(_connect(db_file)) as con, con:
            return create_employee_session(db_file, parent_id, employee_id, con)
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    con.execute("DELETE FROM EMPLOYEE_SESSIONS WHERE expires_at <= ?", (now.isoformat(),))
    con.execute("INSERT INTO EMPLOYEE_SESSIONS VALUES (?, ?, ?, ?)",
                (_hash(token), parent_id, employee_id, (now + timedelta(days=SESSION_DAYS)).isoformat()))
    con.execute("DELETE FROM EMPLOYEE_SESSIONS WHERE rowid IN "
                "(SELECT rowid FROM EMPLOYEE_SESSIONS WHERE Parent_id=? AND Employee_id=? "
                "ORDER BY rowid DESC LIMIT -1 OFFSET ?)", (parent_id, employee_id, MAX_SESSIONS_PER_EMPLOYEE))
    return token


def revoke_employee_session(db_file, token):
    if not isinstance(token, str) or not token.strip():
        return False
    with closing(_connect(db_file)) as con, con:
        return con.execute("DELETE FROM EMPLOYEE_SESSIONS WHERE token_hash=?", (_hash(token),)).rowcount > 0


def revoke_employee_sessions(db_file, parent_id, employee_id):
    with closing(_connect(db_file)) as con, con:
        con.execute("DELETE FROM EMPLOYEE_SESSIONS WHERE Parent_id=? AND Employee_id=?", (parent_id, employee_id))


def _expired(value):
    try:
        return datetime.fromisoformat(value) <= datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return True


def member_from_token(db_file, token=None, *, con=None):
    token = cookie_token(token, MEMBER_COOKIE)
    if not isinstance(token, str) or not token.strip():
        return None
    digest = _hash(token.strip())
    if con is None:
        with closing(_connect(db_file)) as con, con:
            return member_from_token(db_file, token, con=con)
    row = con.execute("SELECT s.Parent_id, s.Employee_id, s.expires_at FROM EMPLOYEE_SESSIONS s "
                      "JOIN EMPLOYEES e ON e.id=s.Employee_id AND e.Parent_id=s.Parent_id "
                      "WHERE s.token_hash=?", (digest,)).fetchone()
    if row and _expired(row["expires_at"]):
        con.execute("DELETE FROM EMPLOYEE_SESSIONS WHERE token_hash=?", (digest,))
    elif row:
        return {"Parent_id": row["Parent_id"], "Employee_id": row["Employee_id"]}
    return None


def admin_from_token(db_file, token=None, *, parent_id=None, consume=False, page=False, con=None):
    """Page grants are read-only; a once grant authorises exactly one transaction."""
    # Choose once: explicit token, primary cookie, then (for page reads only)
    # page cookie. Failed validation must not silently switch workspaces.
    token = cookie_token(token, ADMIN_COOKIE)
    if page:
        token = cookie_token(token, PAGE_COOKIE)
    if not isinstance(token, str) or not token.strip():
        return None
    if con is None:
        with closing(_connect(db_file)) as con, con:
            if consume:
                con.execute("BEGIN IMMEDIATE")
            return admin_from_token(db_file, token, parent_id=parent_id, consume=consume, page=page, con=con)
    digest = _hash(token.strip())
    row = con.execute("SELECT a.id, a.username, s.expires_at, s.purpose FROM ADMIN_SESSIONS s "
                      "JOIN ADMINS a ON a.id=s.admin_id WHERE s.token_hash=?", (digest,)).fetchone()
    if not row or (parent_id is not None and parent_id != row["id"]):
        return None
    if _expired(row["expires_at"]):
        con.execute("DELETE FROM ADMIN_SESSIONS WHERE token_hash=?", (digest,))
        return None
    if row["purpose"] == "session" or (page and row["purpose"] == "approval_page"):
        return row
    if consume and row["purpose"] == "approval_once":
        if con.execute("DELETE FROM ADMIN_SESSIONS WHERE token_hash=?", (digest,)).rowcount == 1:
            return row
    return None


def require_member(db_file, data, allow_admin=False, con=None):
    if isinstance(data, dict):
        pid, eid = to_int(data.get("Parent_id")), to_int(data.get("Employee_id"))
        if pid and eid:
            token = data.get("session_token")
            member = member_from_token(db_file, token, con=con)
            if member and (member["Parent_id"], member["Employee_id"]) == (pid, eid):
                return pid, eid, False
            if allow_admin and admin_from_token(db_file, token, parent_id=pid, con=con):
                return pid, eid, True
    return None, None, False
