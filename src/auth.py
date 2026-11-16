"""Authentication helpers for CyberSyn.

Two kinds of caller reach the API:

* an administrator, holding the token issued at administrator login;
* a team member, holding the token issued at team-member login.

Only the SHA-256 hash of a token is stored, and an expired token is deleted
when it is next used. Every route that reads or writes a member's data goes
through require_member(), so a pair of guessable integers (Parent_id and
Employee_id) is never on its own enough to act as someone else.
"""

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

SESSION_DAYS = 7

EMPLOYEE_SESSIONS_SQL = (
    "CREATE TABLE IF NOT EXISTS EMPLOYEE_SESSIONS ("
    "token_hash TEXT PRIMARY KEY, "
    "Parent_id INTEGER NOT NULL, "
    "Employee_id INTEGER NOT NULL, "
    "expires_at TEXT NOT NULL)"
)


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _connect(db_file):
    con = sqlite3.connect(db_file)
    con.row_factory = sqlite3.Row
    return con


def _expired(iso_value):
    try:
        return datetime.fromisoformat(iso_value) < datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return True


def _positive_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
        return number if number >= 1 else None
    return None


def init_tables(db_file):
    """Create the team-member session table.

    ADMIN_SESSIONS keeps its own table in admin_session.py; this only adds the
    one that did not exist.
    """
    con = _connect(db_file)
    con.execute(EMPLOYEE_SESSIONS_SQL)
    con.commit()
    con.close()


def create_employee_session(db_file, parent_id, employee_id):
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    con = _connect(db_file)
    # Expired rows are dead weight and are never matched again; drop them
    # while the table is open rather than letting them accumulate.
    con.execute(
        "DELETE FROM EMPLOYEE_SESSIONS WHERE expires_at < ?",
        (datetime.now(timezone.utc).isoformat(),),
    )
    con.execute(
        "INSERT INTO EMPLOYEE_SESSIONS (token_hash, Parent_id, Employee_id, expires_at)"
        " VALUES (?, ?, ?, ?)",
        (_hash(token), int(parent_id), int(employee_id), expires.isoformat()),
    )
    con.commit()
    con.close()
    return token


def revoke_employee_session(db_file, token):
    """End one team-member session. Safe to call with a missing token."""
    if not isinstance(token, str) or not token.strip():
        return False
    con = _connect(db_file)
    cur = con.execute(
        "DELETE FROM EMPLOYEE_SESSIONS WHERE token_hash = ?", (_hash(token.strip()),)
    )
    con.commit()
    changed = cur.rowcount > 0
    con.close()
    return changed


def revoke_employee_sessions(db_file, parent_id, employee_id):
    """Drop every session of one team member (used when they are removed)."""
    con = _connect(db_file)
    con.execute(
        "DELETE FROM EMPLOYEE_SESSIONS WHERE Parent_id = ? AND Employee_id = ?",
        (int(parent_id), int(employee_id)),
    )
    con.commit()
    con.close()


def member_from_token(db_file, token):
    """Return {"Parent_id":…, "Employee_id":…} for a live token, else None."""
    if not isinstance(token, str) or not token.strip():
        return None
    digest = _hash(token.strip())
    con = _connect(db_file)
    row = con.execute(
        "SELECT Parent_id, Employee_id, expires_at FROM EMPLOYEE_SESSIONS"
        " WHERE token_hash = ?",
        (digest,),
    ).fetchone()
    if row is not None and _expired(row["expires_at"]):
        con.execute("DELETE FROM EMPLOYEE_SESSIONS WHERE token_hash = ?", (digest,))
        con.commit()
        row = None
    con.close()
    if row is None:
        return None
    return {"Parent_id": int(row["Parent_id"]), "Employee_id": int(row["Employee_id"])}


def admin_from_token(db_file, token):
    """Return the administrator row (id, username) for a live token, else None."""
    if not isinstance(token, str) or not token.strip():
        return None
    digest = _hash(token.strip())
    con = _connect(db_file)
    row = con.execute(
        "SELECT a.id, a.username, s.expires_at FROM ADMIN_SESSIONS s "
        "JOIN ADMINS a ON a.id = s.admin_id WHERE s.token_hash = ?",
        (digest,),
    ).fetchone()
    if row is not None and _expired(row["expires_at"]):
        con.execute("DELETE FROM ADMIN_SESSIONS WHERE token_hash = ?", (digest,))
        con.commit()
        row = None
    con.close()
    return row


def require_member(db_file, data, allow_admin=False):
    """Authorise the caller of a team-member route.

    The body must carry Parent_id, Employee_id and the session_token issued at
    login. An administrator's token is accepted only where allow_admin is set —
    an administrator may manage a member's policy, but never read the content
    of a member's chats.

    Returns (parent_id, employee_id, is_admin), or (None, None, False) when the
    caller is not authorised. Callers decide the status code, so this never
    raises.
    """
    if not isinstance(data, dict):
        return None, None, False

    parent_id = _positive_int(data.get("Parent_id"))
    employee_id = _positive_int(data.get("Employee_id"))
    if parent_id is None or employee_id is None:
        return None, None, False

    token = data.get("session_token")
    member = member_from_token(db_file, token)
    if member and member["Parent_id"] == parent_id and member["Employee_id"] == employee_id:
        return parent_id, employee_id, False

    if allow_admin:
        admin = admin_from_token(db_file, token)
        if admin is not None and int(admin["id"]) == parent_id:
            return parent_id, employee_id, True

    return None, None, False
