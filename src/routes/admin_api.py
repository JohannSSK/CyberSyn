"""Administrator accounts: /api/admin/login and /api/admin.

Signing in issues a session token that the administrator's own routes and
the override flow both rely on.
"""

from flask import Blueprint

import admin_session
from auth import admin_from_token
from config import DB_FILE, NULL
from db import get_db
from web import (clean_str, fail_admin, fail_admin_login, get_json_dict, ok,
                  require_body)
from members import create_default_settings
from passwords import (admin_password_problem, hash_password, upgrade_password,
                       verify_password)

admin_api = Blueprint("admin_api", __name__)


@admin_api.post("/api/admin/login")
def admin_login():
    data = get_json_dict()
    if data is None:
        return fail_admin_login("Request body must be a JSON object.", 400)
    username, password = data.get("username"), data.get("password")
    if not isinstance(username, str) or not username.strip():
        return fail_admin_login("'username' is required.", 400)
    if not isinstance(password, str) or not password.strip():
        return fail_admin_login("'password' is required.", 400)

    username = username.strip()
    row = get_db().execute(
        "SELECT * FROM ADMINS WHERE username = ?", (username,)
    ).fetchone()
    if row is None:
        return fail_admin_login(f"Admin username '{username}' not found.", 401)
    if not verify_password(row["password"], password):
        return fail_admin_login("Invalid password.", 401)

    upgrade_password(get_db(), "ADMINS", row["id"], row["password"], password)
    return {
        "success": True,
        "Parent_id": str(row["id"]),
        "username": username,
        "reason": NULL,
        "session_token": admin_session.create_session(DB_FILE, row["id"]),
    }


@admin_api.post("/api/admin")
def admin_manage():
    data = get_json_dict()
    if data is None:
        return fail_admin("Request body must be a JSON object.", 400)
    method = str(data.get("method", "")).strip().lower()
    username, password = data.get("username"), data.get("password")
    if method not in ("add", "remove"):
        return fail_admin("'method' must be 'add' or 'remove'.", 400)
    if not isinstance(username, str) or not username.strip():
        return fail_admin("'username' is required.", 400)
    if not isinstance(password, str) or not password.strip():
        return fail_admin("'password' is required.", 400)

    username, password = username.strip(), password.strip()
    db = get_db()
    row = db.execute(
        "SELECT * FROM ADMINS WHERE username = ?", (username,)
    ).fetchone()

    if method == "add":
        problem = admin_password_problem(password)
        if problem:
            return fail_admin(problem, 400)
        if row is not None:
            return fail_admin(f"Admin '{username}' already exists.", 409)
        cur = db.execute(
            "INSERT INTO ADMINS (username, password) VALUES (?, ?)",
            (username, hash_password(password)),
        )
        db.commit()
        new_id = cur.lastrowid
        create_default_settings(new_id, 0)
        return {
            "error": False,
            "Parent_id": str(new_id),
            "username": username,
            "session_token": admin_session.create_session(DB_FILE, new_id),
            "error_message": NULL,
        }, 201

    if row is None:
        return fail_admin(f"Admin '{username}' not found.", 404)
    if not verify_password(row["password"], password):
        return fail_admin("Invalid password.", 401)

    pid = row["id"]
    db.execute("DELETE FROM ADMIN_SESSIONS WHERE admin_id = ?", (pid,))
    db.execute("DELETE FROM SETTINGS WHERE Parent_id = ?", (pid,))
    db.execute("DELETE FROM EMPLOYEES WHERE Parent_id = ?", (pid,))
    db.execute("DELETE FROM ADMINS WHERE id = ?", (pid,))
    db.commit()
    return {"error": False, "Parent_id": str(pid), "error_message": NULL}


@admin_api.post("/api/admin/team/list")
def team_list():
    """Members of the signed-in administrator's workspace."""
    data = require_body()
    admin = admin_from_token(DB_FILE, data.get("token"))
    if admin is None:
        return fail_admin("Your session has ended. Sign in again.", 401)

    from members import list_members

    members = [
        {"id": m["id"], "username": m["username"], "created_at": m["created_at"]}
        for m in list_members(int(admin["id"]))
    ]
    return ok(members=members)


@admin_api.post("/api/admin/password")
def change_admin_password():
    """Administrator changes their own password."""
    data = require_body()
    admin = admin_from_token(DB_FILE, data.get("token"))
    if admin is None:
        return fail_admin("Your session has ended. Sign in again.", 401)

    current = clean_str(data.get("current_password"), "current_password")
    new_password = clean_str(data.get("new_password"), "new_password")
    if new_password.strip() == current.strip():
        return fail_admin("The new password must differ from the current one.", 400)
    problem = admin_password_problem(new_password)
    if problem:
        return fail_admin(problem, 400)

    db = get_db()
    row = db.execute(
        "SELECT * FROM ADMINS WHERE id = ?", (int(admin["id"]),)
    ).fetchone()
    if not verify_password(row["password"], current):
        return fail_admin("Current password is incorrect.", 401)

    db.execute(
        "UPDATE ADMINS SET password = ? WHERE id = ?",
        (hash_password(new_password), int(admin["id"])),
    )
    db.commit()
    return ok()
