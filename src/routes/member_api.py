"""Team-member accounts: add, remove, sign in, settings, credentials.

Every one of these routes handles a member's own data, so they all go
through `require_member` (settings also accept an administrator's token,
because setting team policy is the administrator's job).
"""

from flask import Blueprint

from auth import (admin_from_token, create_employee_session, member_from_token,
                  require_member, revoke_employee_session,
                  revoke_employee_sessions)
from block_log import record_activity
from config import DB_FILE
from db import get_db
from errors import ApiError
from web import (fail, fail_employee_login, get_json_dict, non_empty_str, ok,
                  require_body, to_int)
from members import (create_default_settings, employee_row, get_settings,
                     not_found_employee_message, save_settings,
                     settings_payload, settings_updates)
from passwords import hash_password, upgrade_password, verify_password

member_api = Blueprint("member_api", __name__)


def require_admin_approval(data, parent_id):
    """Demand a live administrator session for this workspace.

    Returns the administrator row. The browser asks for the password and
    sends the token it gets back; this is what makes the answer binding,
    because a client-side check alone would be a suggestion.
    """
    admin = admin_from_token(DB_FILE, data.get("admin_token"))
    if admin is None or int(admin["id"]) != parent_id:
        raise ApiError(
            "Changing these settings needs the administrator password.", 401
        )
    return admin


def _credentials(data):
    username, password = data.get("username"), data.get("password")
    if not non_empty_str(username):
        raise ApiError("'username' is required.", 400)
    if not non_empty_str(password):
        raise ApiError("'password' is required.", 400)
    return username.strip(), password


@member_api.post("/api/admin/employee")
def employee_manage():
    """Add or remove a team member. Administrator action."""
    data = get_json_dict()
    if data is None:
        return fail("Request body must be a JSON object.", 400)
    method = str(data.get("method", "")).strip().lower()
    if method not in ("add", "remove"):
        return fail("'method' must be 'add' or 'remove'.", 400)
    parent_id = to_int(data.get("Parent_id"))
    if parent_id is None:
        return fail("'Parent_id' must be a positive integer.", 400)
    try:
        username, password = _credentials(data)
    except ApiError as exc:
        return fail(exc.message, exc.status)

    db = get_db()
    if db.execute("SELECT id FROM ADMINS WHERE id = ?", (parent_id,)).fetchone() is None:
        return fail(f"Parent_id {parent_id} not found.", 404)

    row = db.execute(
        "SELECT * FROM EMPLOYEES WHERE Parent_id = ? AND username = ?",
        (parent_id, username),
    ).fetchone()

    if method == "add":
        if row is not None:
            return fail(
                f"Employee '{username}' already exists under Parent_id {parent_id}.",
                409,
            )
        cur = db.execute(
            "INSERT INTO EMPLOYEES (Parent_id, username, password, CHAT_LOGS, "
            "created_at) VALUES (?, ?, ?, '[]', datetime('now'))",
            (parent_id, username, hash_password(password)),
        )
        db.commit()
        create_default_settings(parent_id, cur.lastrowid)
        return {
            "error": False,
            "Employee_id": str(cur.lastrowid),
            "error_message": "NULL",
        }, 201

    if row is None:
        return fail(f"Employee '{username}' not found under Parent_id {parent_id}.", 404)
    if not verify_password(row["password"], password):
        return fail("Invalid employee password.", 401)

    db.execute(
        "DELETE FROM SETTINGS WHERE Parent_id = ? AND Employee_id = ?",
        (parent_id, row["id"]),
    )
    db.execute("DELETE FROM EMPLOYEES WHERE id = ?", (row["id"],))
    db.commit()
    revoke_employee_sessions(DB_FILE, parent_id, row["id"])
    return {"error": False, "error_message": "NULL"}


@member_api.post("/api/admin/employee/login")
def employee_login():
    """Sign a member in and hand back their workspace."""
    from chat_store import list_chats, newest_chat

    data = get_json_dict()
    if data is None:
        return fail_employee_login("Request body must be a JSON object.", 400)
    parent_id = to_int(data.get("Parent_id"))
    if parent_id is None:
        return fail_employee_login("'Parent_id' must be a positive integer.", 400)
    try:
        username, password = _credentials(data)
    except ApiError as exc:
        return fail_employee_login(exc.message, exc.status)

    row = get_db().execute(
        "SELECT * FROM EMPLOYEES WHERE Parent_id = ? AND username = ?",
        (parent_id, username),
    ).fetchone()
    if row is None or not verify_password(row["password"], password):
        return fail_employee_login("Invalid employee username or password.", 401)

    upgrade_password(get_db(), "EMPLOYEES", row["id"], row["password"], password)
    record_activity(DB_FILE, parent_id, row["id"], "login")
    latest = newest_chat(DB_FILE, parent_id, row["id"])
    return {
        "error": False,
        "Employee_id": str(row["id"]),
        "username": row["username"],
        "session_token": create_employee_session(DB_FILE, parent_id, row["id"]),
        "chats": list_chats(DB_FILE, parent_id, row["id"]),
        "chat_id": latest["id"] if latest else None,
        "CHAT_LOGS": latest["messages"] if latest else [],
        "settings": settings_payload(
            parent_id, row["id"], get_settings(parent_id, row["id"])
        ),
        "error_message": "NULL",
    }


@member_api.post("/api/admin/employee/logout")
def employee_logout():
    """End the caller's own session on the server as well as in the browser.

    Without this, signing out only cleared localStorage and the token stayed
    valid for a week — a copy of it could not be revoked by the member who
    was given it.
    """
    data = get_json_dict()
    if data is None:
        return fail("Request body must be a JSON object.", 400)
    token = data.get("session_token")
    member = member_from_token(DB_FILE, token)
    if member is not None:
        revoke_employee_session(DB_FILE, token)
    return ok()


@member_api.post("/api/admin/employee/settings")
def employee_settings():
    """Read or change a member's policy.

    A member changes their own; an administrator may set it for anyone on
    their team. Nobody else may — policy is not something an unauthenticated
    caller gets to switch off.
    """
    data = get_json_dict()
    if data is None:
        return fail("Request body must be a JSON object.", 400)
    if require_member(DB_FILE, data, allow_admin=True)[0] is None:
        return fail(
            "Your session has ended. Sign in again to change these settings.", 401
        )

    parent_id = to_int(data.get("Parent_id"))
    employee_id = to_int(data.get("Employee_id"))
    if parent_id is None:
        return fail("'Parent_id' must be a positive integer.", 400)
    if employee_id is None:
        return fail("'Employee_id' must be a positive integer.", 400)
    if employee_row(parent_id, employee_id) is None:
        return fail(not_found_employee_message(parent_id, employee_id), 404)

    try:
        updates = settings_updates(data)
    except ApiError as exc:
        return fail(exc.message, exc.status)

    # Reading policy is the member's own business; changing it is not. These
    # settings decide whether prompts are screened and where they are sent,
    # so a member cannot turn them down on their own authority — including
    # by replaying a request with the checks switched off.
    if updates:
        try:
            require_admin_approval(data, parent_id)
        except ApiError as exc:
            return fail(exc.message, exc.status)

    create_default_settings(parent_id, employee_id)
    row = save_settings(parent_id, employee_id, updates)
    if updates:
        record_activity(DB_FILE, parent_id, employee_id, "settings",
                        ", ".join(sorted(updates)))
    return settings_payload(parent_id, employee_id, row)


@member_api.post("/api/admin/employee/account")
def employee_account():
    """A member changes their own username or password."""
    data = get_json_dict()
    if data is None:
        return fail("Request body must be a JSON object.", 400)
    parent_id = to_int(data.get("Parent_id"))
    employee_id = to_int(data.get("Employee_id"))
    action = str(data.get("action", "")).strip().lower()
    current = data.get("current_password")
    if parent_id is None:
        return fail("Parent_id must be a positive integer.", 400)
    if employee_id is None:
        return fail("Employee_id must be a positive integer.", 400)
    if action not in ("password", "username"):
        return fail("action must be password or username.", 400)
    if not non_empty_str(current):
        return fail("current_password is required.", 400)

    # The member's own session proves who is changing what.
    if require_member(DB_FILE, data)[0] is None:
        return fail("Your session has ended. Sign in again.", 401)

    row = employee_row(parent_id, employee_id)
    if row is None:
        return fail(not_found_employee_message(parent_id, employee_id), 404)
    if not verify_password(row["password"], current):
        return fail("Current password is incorrect.", 401)

    db = get_db()
    if action == "password":
        new_password = data.get("new_password")
        if not non_empty_str(new_password):
            return fail("new_password is required.", 400)
        if new_password.strip() == current.strip():
            return fail(
                "The new password must be different from the current one.", 400
            )
        db.execute(
            "UPDATE EMPLOYEES SET password = ? WHERE id = ?",
            (hash_password(new_password.strip()), employee_id),
        )
        db.commit()
        return ok()

    new_username = data.get("new_username")
    if not non_empty_str(new_username):
        return fail("new_username is required.", 400)
    new_username = new_username.strip()
    if new_username == row["username"]:
        return fail("The new username is the same as the current one.", 400)
    taken = db.execute(
        "SELECT 1 FROM EMPLOYEES WHERE Parent_id = ? AND username = ? AND id != ?",
        (parent_id, new_username, employee_id),
    ).fetchone()
    if taken is not None:
        return fail(
            f"That username is already taken under Parent_id {parent_id}.", 409
        )
    db.execute(
        "UPDATE EMPLOYEES SET username = ? WHERE id = ?",
        (new_username, employee_id),
    )
    db.commit()
    return ok(username=new_username)


@member_api.post("/api/admin/employee/override/check")
def override_check():
    """Is this administrator token good enough to approve an override?

    Lets the front end disable the override button before someone types a
    password that is going to be refused.
    """
    data = require_body()
    parent_id = to_int(data.get("Parent_id"))
    if parent_id is None:
        return fail("'Parent_id' must be a positive integer.", 400)
    admin = admin_from_token(DB_FILE, data.get("admin_token"))
    allowed = admin is not None and int(admin["id"]) == parent_id
    return ok(allowed=allowed)
