"""Administrator accounts, primary sessions and purpose-limited approvals."""

import hmac
import os
import sqlite3

from flask import Blueprint

import admin_session
from auth import ADMIN_COOKIE, PAGE_COOKIE, admin_from_token, session_response
from config import DB_FILE, NULL, ROUTES, _env_flag
from db import get_db
from errors import ApiError
from members import list_members
from passwords import admin_password_problem, credentials_match, hash_password, upgrade_password
from rate_limit import limited
from web import clean_str, fail_admin, fail_admin_login, get_json_dict, ok, password_field, require_body, to_int

admin_api = Blueprint("admin_api", __name__)
INVALID = "Invalid username or password."


@admin_api.post(ROUTES["ADMIN_LOGIN"])
@limited(fail_admin_login)
def admin_login():
    return _sign_in(approval=False)


@admin_api.post(ROUTES["ADMIN_APPROVE"])
@limited(fail_admin_login)
def approve():
    return _sign_in(approval=True)


def _sign_in(approval):
    try:
        data = require_body()
        username = clean_str(data.get("username"), "username", 64)
        password = password_field(data, "password")
    except ApiError as exc:
        return fail_admin_login(exc.message, exc.status)
    scope = data.get("scope", "once")
    if approval and scope not in ("once", "page"):
        return fail_admin_login("scope must be once or page.", 400)
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM ADMINS WHERE username=?", (username,)).fetchone()
        if not credentials_match(row, password):
            return fail_admin_login(INVALID, 401)
        if approval and "Parent_id" in data and to_int(data["Parent_id"]) != row["id"]:
            return fail_admin_login("This administrator does not own the workspace.", 403)
        upgrade_password(db, "ADMINS", row["id"], row["password"], password)
        purpose = "approval_" + scope if approval else "session"
        token = admin_session.create_session(DB_FILE, row["id"], purpose, db)
    body = {"success": True, "Parent_id": str(row["id"]), "username": username, "reason": NULL}
    if not approval:
        return session_response(body, ADMIN_COOKIE, token)
    if scope == "page":
        return session_response(body, PAGE_COOKIE, token, max_age=900)
    return dict(body, admin_token=token)


def signup_allowed(db, data):
    if not db.execute("SELECT 1 FROM ADMINS LIMIT 1").fetchone() or _env_flag("CYBERSYN_ALLOW_OPEN_SIGNUP"):
        return True
    configured = os.environ.get("CYBERSYN_ADMIN_SIGNUP_TOKEN")
    supplied = data.get("signup_token")
    if configured and isinstance(supplied, str) and hmac.compare_digest(configured.encode(), supplied.encode()):
        return True
    return admin_from_token(DB_FILE, data.get("admin_token", data.get("token")), consume=True, con=db) is not None


@admin_api.post(ROUTES["ADMIN"])
@limited(fail_admin)
def admin_manage():
    try:
        data = require_body()
        username = clean_str(data.get("username"), "username", 64)
        password = password_field(data, "password")
    except ApiError as exc:
        return fail_admin(exc.message, exc.status)
    method = str(data.get("method", "")).strip().lower()
    if method not in ("add", "remove"):
        return fail_admin("'method' must be 'add' or 'remove'.", 400)
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")  # serialize the bootstrap check with the insert
        if method == "add":
            if not signup_allowed(db, data):
                return fail_admin("An administrator already exists on this gateway. Sign in as an administrator "
                                  "or provide the registration token to add another.", 403)
            problem = admin_password_problem(password)
            if problem:
                return fail_admin(problem, 400)
            try:
                pid = db.execute("INSERT INTO ADMINS (username, password) VALUES (?, ?)",
                                 (username, hash_password(password))).lastrowid
            except sqlite3.IntegrityError:
                return fail_admin(f"Admin '{username}' already exists.", 409)
            db.execute("INSERT INTO SETTINGS (Parent_id, Employee_id) VALUES (?, 0)", (pid,))
            token = admin_session.create_session(DB_FILE, pid, con=db)
            return session_response({"error": False, "Parent_id": str(pid), "username": username,
                                     "error_message": NULL}, ADMIN_COOKIE, token, 201)
        row = db.execute("SELECT * FROM ADMINS WHERE username=?", (username,)).fetchone()
        if not credentials_match(row, password):
            return fail_admin(INVALID, 401)
        pid = row["id"]
        db.execute("DELETE FROM ADMIN_SESSIONS WHERE admin_id=?", (pid,))
        for table in ("EMPLOYEE_SESSIONS", "CHATS", "SETTINGS", "EMPLOYEES"):
            db.execute(f"DELETE FROM {table} WHERE Parent_id=?", (pid,))
        db.execute("DELETE FROM ADMINS WHERE id=?", (pid,))
    return ok(Parent_id=str(pid))


@admin_api.post(ROUTES["TEAM_LIST"])
def team_list():
    data = require_body()
    admin = admin_from_token(DB_FILE, data.get("token"), page=True)
    if admin is None:
        return fail_admin("Your session has ended. Sign in again.", 401)
    return ok(members=[dict(m) for m in list_members(admin["id"])])


@admin_api.post(ROUTES["ADMIN_PASSWORD"])
@limited(fail_admin)
def change_admin_password():
    data = require_body()
    current = password_field(data, "current_password")
    new = password_field(data, "new_password")
    if new == current:
        return fail_admin("The new password must differ from the current one.", 400)
    problem = admin_password_problem(new)
    if problem:
        return fail_admin(problem, 400)
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        admin = admin_from_token(DB_FILE, data.get("token", data.get("admin_token")), consume=True, con=db)
        if admin is None:
            return fail_admin("Your session has ended. Sign in again.", 401)
        row = db.execute("SELECT password FROM ADMINS WHERE id=?", (admin["id"],)).fetchone()
        if not credentials_match(row, current):
            return fail_admin("Current password is incorrect.", 401)
        db.execute("UPDATE ADMINS SET password=? WHERE id=?", (hash_password(new), admin["id"]))
        db.execute("DELETE FROM ADMIN_SESSIONS WHERE admin_id=?", (admin["id"],))
    response = ok()
    response.delete_cookie(ADMIN_COOKIE)
    response.delete_cookie(PAGE_COOKIE)
    return response
