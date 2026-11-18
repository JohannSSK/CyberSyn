"""Team-member accounts, per-member policy and workspace defaults."""

import sqlite3

from flask import Blueprint

from auth import (ADMIN_COOKIE, MEMBER_COOKIE, PAGE_COOKIE, admin_from_token, cookie_token,
                  create_employee_session, require_member, revoke_browser_admin, revoke_employee_session, session_response)
from block_log import record_activity
from config import DB_FILE, NULL, ROUTES
from db import get_db
from errors import ApiError
from members import (CONNECTION_FIELDS, POLICY_FIELDS, create_default_settings, employee_row, get_settings, not_found_employee_message,
                     save_settings, settings_payload, settings_updates)
from passwords import credentials_match, hash_password, member_password_problem, upgrade_password
from rate_limit import limited
from web import clean_str, fail, fail_employee_login, ok, password_field, require_body, to_int

member_api = Blueprint("member_api", __name__)


def require_admin_approval(data, parent_id, db):
    token = data.get("admin_token", data.get("token", data.get("session_token")))
    admin = admin_from_token(DB_FILE, token, parent_id=parent_id, consume=True, con=db)
    if admin is None:
        raise ApiError("Changing these settings needs the administrator password.", 401)
    return admin


@member_api.post(ROUTES["EMPLOYEE"])
@limited(fail, methods=("remove",))
def employee_manage():
    data = require_body()
    method = str(data.get("method", "")).strip().lower()
    if method not in ("add", "remove"):
        return fail("'method' must be 'add' or 'remove'.", 400)
    pid = to_int(data.get("Parent_id"))
    if not pid:
        return fail("'Parent_id' must be a positive integer.", 400)
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        admin = admin_from_token(DB_FILE, data.get("token"), parent_id=pid, consume=True, con=db)
        if admin is None:
            return fail("Adding or removing a team member needs a valid administrator session for this workspace.", 401)
        username = clean_str(data.get("username"), "username", 64)
        row = db.execute("SELECT id FROM EMPLOYEES WHERE Parent_id=? AND username=?", (pid, username)).fetchone()
        if method == "add":
            password = password_field(data, "password")
            problem = member_password_problem(password)
            if problem:
                return fail(problem, 400)
            try:
                if row:  # legacy DBs with duplicate names may lack the unique index
                    return fail("That member username is already taken.", 409)
                eid = db.execute("INSERT INTO EMPLOYEES (Parent_id, username, password, created_at) "
                                 "VALUES (?, ?, ?, datetime('now'))", (pid, username, hash_password(password))).lastrowid
            except sqlite3.IntegrityError:
                return fail("That member username is already taken.", 409)
            create_default_settings(pid, eid, inherit=True, commit=False)
            return ok(Employee_id=str(eid)), 201
        password = password_field(data, "admin_password")
        owner = db.execute("SELECT password FROM ADMINS WHERE id=?", (pid,)).fetchone()
        if not credentials_match(owner, password):
            return fail("Invalid administrator password.", 401)
        if row is None:
            return fail("That team member was not found.", 404)
        for table in ("SETTINGS", "CHATS", "EMPLOYEE_SESSIONS"):
            db.execute(f"DELETE FROM {table} WHERE Parent_id=? AND Employee_id=?", (pid, row["id"]))
        db.execute("DELETE FROM EMPLOYEES WHERE id=?", (row["id"],))
    return ok()


@member_api.post(ROUTES["EMPLOYEE_LOGIN"])
@limited(fail_employee_login)
def employee_login():
    from chat_store import list_chats, newest_chat

    try:
        data = require_body()
        username = clean_str(data.get("username"), "username", 64)
        password = password_field(data, "password")
        workspace = clean_str(data["workspace"], "workspace", 64) if "workspace" in data else None
        pid = to_int(data.get("Parent_id"))
        if "Parent_id" in data and pid is None:
            raise ApiError("'Parent_id' must be a positive integer.", 400)
        if pid is not None and workspace is not None:
            raise ApiError("Provide either Parent_id or workspace, not both.", 400)
    except ApiError as exc:
        return fail_employee_login(exc.message, exc.status)
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        if workspace is not None:
            owner = db.execute("SELECT id FROM ADMINS WHERE username=?", (workspace,)).fetchone()
            pid = owner["id"] if owner else None
        elif pid is None:
            owners = db.execute("SELECT id FROM ADMINS LIMIT 2").fetchall()
            if len(owners) == 2:
                return fail_employee_login("Enter your workspace name to sign in.", 400)
            pid = owners[0]["id"] if owners else None
        row = db.execute("SELECT * FROM EMPLOYEES WHERE Parent_id=? AND username=?", (pid, username)).fetchone()
        if not credentials_match(row, password):
            return fail_employee_login("Invalid employee username or password.", 401)
        eid = row["id"]
        upgrade_password(db, "EMPLOYEES", eid, row["password"], password)
        token = create_employee_session(DB_FILE, pid, eid, db)
        revoke_browser_admin(db)
    record_activity(DB_FILE, pid, eid, "login")
    latest = newest_chat(DB_FILE, pid, eid)
    response = session_response({"error": False, "Parent_id": str(pid), "Employee_id": str(eid), "username": username,
                                 "chats": list_chats(DB_FILE, pid, eid), "chat_id": latest["id"] if latest else None,
                                 "CHAT_LOGS": latest["messages"] if latest else [], "error_message": NULL,
                                 "settings": settings_payload(pid, eid, get_settings(pid, eid))}, MEMBER_COOKIE, token)
    response.delete_cookie(ADMIN_COOKIE)
    response.delete_cookie(PAGE_COOKIE)
    return response


@member_api.post(ROUTES["EMPLOYEE_LOGOUT"])
def employee_logout():
    token = cookie_token(require_body().get("session_token"), MEMBER_COOKIE)
    revoke_employee_session(DB_FILE, token)
    response = ok()
    response.delete_cookie(MEMBER_COOKIE)
    return response


@member_api.post(ROUTES["SETTINGS"])
def employee_settings():
    data = require_body()
    pid = to_int(data.get("Parent_id"))
    value = data.get("Employee_id")
    eid = 0 if type(value) in (int, str) and value in (0, "0") else to_int(value)
    if not pid or eid is None:
        return fail("Expected a positive Parent_id and a non-negative Employee_id.", 400)
    db = get_db()
    also_default = data.get("also_default", False)
    if not isinstance(also_default, bool):
        return fail("'also_default' must be true or false.", 400)
    fields = {*POLICY_FIELDS, *CONNECTION_FIELDS, "CLEAR_API_KEY"}
    writing = not fields.isdisjoint(data)
    with db:
        db.execute("BEGIN IMMEDIATE")
        if writing:
            require_admin_approval(data, pid, db)
        elif eid == 0 or require_member(DB_FILE, data, con=db)[0] is None:
            token = data.get("admin_token", data.get("token", data.get("session_token")))
            if admin_from_token(DB_FILE, token, parent_id=pid, page=True, con=db) is None:
                return fail("Your session has ended. Sign in again.", 401)
        if eid and employee_row(pid, eid) is None:
            return fail(not_found_employee_message(pid, eid), 404)
        updates = settings_updates(data)
        save_settings(pid, eid, updates)
        saved = get_settings(pid, eid)
        if also_default and eid and updates:
            defaults = updates.copy()
            if any(field in updates for field in CONNECTION_FIELDS):
                # Copy one effective connection, including its encrypted key. Never
                # pair a previous default key with this member's new destination.
                defaults.update((field, saved[field]) for field in CONNECTION_FIELDS)
            save_settings(pid, 0, defaults)
        payload = settings_payload(pid, eid, saved)
    if updates:
        detail = ", ".join(sorted(updates))
        record_activity(DB_FILE, pid, eid, "settings", detail)
        if also_default and eid:
            record_activity(DB_FILE, pid, 0, "settings", ", ".join(sorted(defaults)))
    return payload


@member_api.post(ROUTES["EMPLOYEE_ACCOUNT"])
@limited(fail)
def employee_account():
    data = require_body()
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        pid, eid, _ = require_member(DB_FILE, data, con=db)
        if not pid:
            return fail("Your session has ended. Sign in again.", 401)
        current = password_field(data, "current_password")
        action = data.get("action")
        row = employee_row(pid, eid)
        if not credentials_match(row, current):
            return fail("Current password is incorrect.", 401)
        if action == "password":
            new = password_field(data, "new_password")
            problem = member_password_problem(new)
            if problem or new == current:
                return fail(problem or "The new password must differ from the current one.", 400)
            db.execute("UPDATE EMPLOYEES SET password=? WHERE id=?", (hash_password(new), eid))
            db.execute("DELETE FROM EMPLOYEE_SESSIONS WHERE Parent_id=? AND Employee_id=?", (pid, eid))
            token = create_employee_session(DB_FILE, pid, eid, db)
            return session_response({"error": False, "error_message": NULL}, MEMBER_COOKIE, token)
        if action != "username":
            return fail("action must be password or username.", 400)
        new = clean_str(data.get("new_username"), "new_username", 64)
        if new == row["username"]:
            return fail("The new username is the same as the current one.", 400)
        try:
            if db.execute("SELECT 1 FROM EMPLOYEES WHERE Parent_id=? AND username=?", (pid, new)).fetchone():
                return fail("That username is already taken.", 409)
            db.execute("UPDATE EMPLOYEES SET username=? WHERE id=?", (new, eid))
        except sqlite3.IntegrityError:
            return fail("That username is already taken.", 409)
    return ok(username=new)


@member_api.post(ROUTES["OVERRIDE_CHECK"])
def override_check():
    data = require_body()
    pid = to_int(data.get("Parent_id"))
    if not pid:
        return fail("'Parent_id' must be a positive integer.", 400)
    return ok(allowed=admin_from_token(DB_FILE, data.get("admin_token"), page=True, parent_id=pid) is not None)
