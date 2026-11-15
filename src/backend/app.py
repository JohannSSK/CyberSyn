#!/usr/bin/env python3
"""
CyberSyn test-environment backend (single file).

Run:   cd ~/CyberSyn/testenv/backend && python3 app.py
Seed:  python3 app.py seed        (creates admin johann / admin_secret_123)
Open:  http://127.0.0.1:5000/
"""

import hmac
import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent


def find_constants_file():
    """Walk up from this file looking for includes/constants.json."""
    for folder in [HERE, *HERE.parents]:
        for d in ("includes", "include"):
            for n in ("constants.json", "constant.json"):
                p = folder / d / n
                if p.is_file():
                    return p
    raise FileNotFoundError(
        "Could not find includes/constants.json in any parent folder of " + str(HERE)
    )


CONSTANTS_FILE = find_constants_file()
ROOT_DIR = CONSTANTS_FILE.parent.parent

with open(CONSTANTS_FILE, "r", encoding="utf-8") as fh:
    CONSTANTS = json.load(fh)

HOST = CONSTANTS.get("HOST", "127.0.0.1")
PORT = int(CONSTANTS.get("PORT", 5000))
PATHS = CONSTANTS["PATHS"]
ROUTES = CONSTANTS["ROUTES"]

DB_FILE = ROOT_DIR / PATHS["DB_FILE"]
DB_FILE.parent.mkdir(parents=True, exist_ok=True)

NULL = "NULL"
DEFAULT_MODEL = "gpt-4o-mini"
OPENAI_URL = os.environ.get("OPENAI_URL", "https://api.openai.com/v1/chat/completions")
CHECK_TIMEOUT = 60
OPENAI_TIMEOUT = 60

CHECKS = [
    ("check1", "CHECK1_SCRIPT"),
    ("check2", "CHECK2_SCRIPT"),
    ("check3", "CHECK3_SCRIPT"),
]

# Names a scanner script may use for its "blocked" field.
BLOCK_KEYS = ("blocked", "is_blocked", "block", "flagged")

# ---------------------------------------------------------------------------
# Flask app + JSON error handling
# ---------------------------------------------------------------------------

app = Flask(__name__, template_folder=str(HERE / "templates"))
app.json.ensure_ascii = False


@app.route("/")
def index():
    return render_template("index.html")


@app.errorhandler(Exception)
def handle_any_error(exc):
    if isinstance(exc, HTTPException):
        return (
            jsonify({
                "error": True,
                "error_message": f"{exc.code} {exc.name}: {exc.description}",
            }),
            exc.code,
        )
    return (
        jsonify({
            "error": True,
            "error_message": f"Server error: {type(exc).__name__}: {exc}",
        }),
        500,
    )


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_FILE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create missing tables only. Never touches existing team tables."""
    con = sqlite3.connect(DB_FILE)
    con.executescript(
        """
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
            CHAT_LOGS  TEXT DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS SETTINGS (
            Parent_id   INTEGER NOT NULL,
            Employee_id INTEGER NOT NULL DEFAULT 0,
            check1      INTEGER NOT NULL DEFAULT 1,
            check2      INTEGER NOT NULL DEFAULT 1,
            check3      INTEGER NOT NULL DEFAULT 1,
            API_KEY     TEXT NOT NULL DEFAULT '',
            MODEL_NAME  TEXT NOT NULL DEFAULT 'gpt-4o-mini',
            PRIMARY KEY (Parent_id, Employee_id)
        );
        """
    )
    con.commit()
    con.close()


EXPECTED_COLUMNS = {
    "ADMINS": {"id", "username", "password"},
    "EMPLOYEES": {"id", "Parent_id", "username", "password", "CHAT_LOGS"},
    "SETTINGS": {"Parent_id", "Employee_id", "check1", "check2", "check3",
                 "API_KEY", "MODEL_NAME"},
}


def check_schema():
    con = sqlite3.connect(DB_FILE)
    problems = []
    for table, expected in EXPECTED_COLUMNS.items():
        cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
        missing = expected - cols
        if missing:
            problems.append(f"  table {table} is missing columns: {sorted(missing)}")
    con.close()
    if problems:
        sys.exit(
            "Database schema does not match what app.py expects ("
            + str(DB_FILE) + "):\n" + "\n".join(problems)
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def to_int(value):
    """Return a positive int from an int or digit string, otherwise None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, str) and value.strip().isdigit():
        n = int(value.strip())
        return n if n >= 1 else None
    return None


def non_empty_str(value):
    return isinstance(value, str) and value.strip() != ""


def get_json_dict():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def is_hashed(stored):
    return isinstance(stored, str) and stored.startswith(("scrypt:", "pbkdf2:"))


def verify_password(stored, given):
    if not isinstance(stored, str) or not isinstance(given, str):
        return False
    if is_hashed(stored):
        return check_password_hash(stored, given)
    # Plain-text rows from teammates.
    return hmac.compare_digest(stored.encode("utf-8"), given.encode("utf-8"))


def upgrade_password(table, row_id, stored, given):
    """If the stored password was plain text, replace it with a hash."""
    if not is_hashed(stored):
        db = get_db()
        db.execute(f"UPDATE {table} SET password = ? WHERE id = ?",
                   (generate_password_hash(given), row_id))
        db.commit()


def load_chat_logs(raw):
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, dict):
            out.append({
                "prompt": str(item.get("prompt", "")),
                "answer": str(item.get("answer") or item.get("reply") or ""), "reply": str(item.get("reply") or item.get("answer") or ""),
            })
    return out


def employee_row(parent_id, employee_id):
    return get_db().execute(
        "SELECT * FROM EMPLOYEES WHERE id = ? AND Parent_id = ?",
        (employee_id, parent_id),
    ).fetchone()


def not_found_employee_message(parent_id, employee_id):
    return (
        f"Employee_id {employee_id} not found under Parent_id {parent_id}. "
        "Use the real Employee_id returned by /api/admin/employee/login."
    )


# ---- settings ----

def default_settings_values(parent_id):
    row = get_db().execute(
        "SELECT * FROM SETTINGS WHERE Parent_id = ? AND Employee_id = 0",
        (parent_id,),
    ).fetchone()
    if row:
        return {
            "check1": int(row["check1"]), "check2": int(row["check2"]),
            "check3": int(row["check3"]), "API_KEY": row["API_KEY"] or "",
            "MODEL_NAME": row["MODEL_NAME"] or DEFAULT_MODEL,
        }
    return {"check1": 1, "check2": 1, "check3": 1,
            "API_KEY": "", "MODEL_NAME": DEFAULT_MODEL}


def create_default_settings(parent_id, employee_id):
    """Create a SETTINGS row (copy of the admin default) if it doesn't exist."""
    db = get_db()
    exists = db.execute(
        "SELECT 1 FROM SETTINGS WHERE Parent_id = ? AND Employee_id = ?",
        (parent_id, employee_id),
    ).fetchone()
    if exists:
        return
    d = default_settings_values(parent_id)
    db.execute(
        "INSERT INTO SETTINGS (Parent_id, Employee_id, check1, check2, check3, "
        "API_KEY, MODEL_NAME) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (parent_id, employee_id, d["check1"], d["check2"], d["check3"],
         d["API_KEY"], d["MODEL_NAME"]),
    )
    db.commit()


def get_settings(parent_id, employee_id):
    create_default_settings(parent_id, employee_id)
    return get_db().execute(
        "SELECT * FROM SETTINGS WHERE Parent_id = ? AND Employee_id = ?",
        (parent_id, employee_id),
    ).fetchone()


def settings_payload(parent_id, employee_id, row):
    return {
        "Parent_id": str(parent_id),
        "Employee_id": str(employee_id),
        "check1": bool(row["check1"]),
        "check2": bool(row["check2"]),
        "check3": bool(row["check3"]),
        "API_KEY": row["API_KEY"] or "",
        "MODEL_NAME": row["MODEL_NAME"] or DEFAULT_MODEL,
    }


# ---------------------------------------------------------------------------
# API 1: POST /api/admin/login
# ---------------------------------------------------------------------------

def fail1(reason, status):
    return jsonify({"success": False, "Parent_id": NULL, "reason": reason}), status


@app.post(ROUTES["ADMIN_LOGIN"])
def admin_login():
    data = get_json_dict()
    if data is None:
        return fail1("Request body must be a JSON object.", 400)
    username, password = data.get("username"), data.get("password")
    if not non_empty_str(username) or not non_empty_str(password):
        return fail1("'username' and 'password' are required.", 400)

    row = get_db().execute(
        "SELECT * FROM ADMINS WHERE username = ?", (username,)
    ).fetchone()
    if row is None:
        return fail1(f"Admin username '{username}' not found.", 401)
    if not verify_password(row["password"], password):
        return fail1("Invalid password.", 401)

    upgrade_password("ADMINS", row["id"], row["password"], password)
    return jsonify({"success": True, "Parent_id": str(row["id"]), "reason": NULL})


# ---------------------------------------------------------------------------
# API 2: POST /api/admin  (add / remove admin)
# ---------------------------------------------------------------------------

def fail2(message, status):
    return jsonify({"error": True, "Parent_id": NULL, "error_message": message}), status


@app.post(ROUTES["ADMIN"])
def admin_manage():
    data = get_json_dict()
    if data is None:
        return fail2("Request body must be a JSON object.", 400)
    method = str(data.get("method", "")).strip().lower()
    username, password = data.get("username"), data.get("password")
    if method not in ("add", "remove"):
        return fail2("'method' must be 'add' or 'remove'.", 400)
    if not non_empty_str(username) or not non_empty_str(password):
        return fail2("'username' and 'password' are required.", 400)

    db = get_db()
    row = db.execute("SELECT * FROM ADMINS WHERE username = ?", (username,)).fetchone()

    if method == "add":
        if row is not None:
            return fail2(f"Admin '{username}' already exists.", 409)
        cur = db.execute(
            "INSERT INTO ADMINS (username, password) VALUES (?, ?)",
            (username, generate_password_hash(password)),
        )
        db.commit()
        new_id = cur.lastrowid
        create_default_settings(new_id, 0)
        return jsonify({"error": False, "Parent_id": str(new_id),
                        "error_message": NULL}), 201

    # remove
    if row is None:
        return fail2(f"Admin '{username}' not found.", 404)
    if not verify_password(row["password"], password):
        return fail2("Invalid password.", 401)
    pid = row["id"]
    db.execute("DELETE FROM SETTINGS WHERE Parent_id = ?", (pid,))
    db.execute("DELETE FROM EMPLOYEES WHERE Parent_id = ?", (pid,))
    db.execute("DELETE FROM ADMINS WHERE id = ?", (pid,))
    db.commit()
    return jsonify({"error": False, "Parent_id": str(pid), "error_message": NULL})


# ---------------------------------------------------------------------------
# API 3: POST /api/admin/employee  (add / remove employee)
# ---------------------------------------------------------------------------

def fail3(message, status):
    return jsonify({"error": True, "error_message": message}), status


@app.post(ROUTES["EMPLOYEE"])
def employee_manage():
    data = get_json_dict()
    if data is None:
        return fail3("Request body must be a JSON object.", 400)
    method = str(data.get("method", "")).strip().lower()
    username, password = data.get("username"), data.get("password")
    parent_id = to_int(data.get("Parent_id"))
    if method not in ("add", "remove"):
        return fail3("'method' must be 'add' or 'remove'.", 400)
    if not non_empty_str(username) or not non_empty_str(password):
        return fail3("'username' and 'password' are required.", 400)
    if parent_id is None:
        return fail3("'Parent_id' must be a positive integer.", 400)

    db = get_db()
    admin = db.execute("SELECT id FROM ADMINS WHERE id = ?", (parent_id,)).fetchone()
    if admin is None:
        return fail3(f"Parent_id {parent_id} not found.", 404)

    row = db.execute(
        "SELECT * FROM EMPLOYEES WHERE Parent_id = ? AND username = ?",
        (parent_id, username),
    ).fetchone()

    if method == "add":
        if row is not None:
            return fail3(
                f"Employee '{username}' already exists under Parent_id {parent_id}.", 409)
        cur = db.execute(
            "INSERT INTO EMPLOYEES (Parent_id, username, password, CHAT_LOGS) "
            "VALUES (?, ?, ?, '[]')",
            (parent_id, username, generate_password_hash(password)),
        )
        db.commit()
        create_default_settings(parent_id, cur.lastrowid)
        return jsonify({"error": False, "error_message": NULL}), 201

    # remove
    if row is None:
        return fail3(f"Employee '{username}' not found under Parent_id {parent_id}.", 404)
    if not verify_password(row["password"], password):
        return fail3("Invalid employee password.", 401)
    db.execute("DELETE FROM SETTINGS WHERE Parent_id = ? AND Employee_id = ?",
               (parent_id, row["id"]))
    db.execute("DELETE FROM EMPLOYEES WHERE id = ?", (row["id"],))
    db.commit()
    return jsonify({"error": False, "error_message": NULL})


# ---------------------------------------------------------------------------
# API 4: POST /api/admin/employee/login
# ---------------------------------------------------------------------------

def fail4(message, status):
    return jsonify({"error": True, "Employee_id": NULL, "CHAT_LOGS": [],
                    "error_message": message}), status


@app.post(ROUTES["EMPLOYEE_LOGIN"])
def employee_login():
    data = get_json_dict()
    if data is None:
        return fail4("Request body must be a JSON object.", 400)
    parent_id = to_int(data.get("Parent_id"))
    username, password = data.get("username"), data.get("password")
    if parent_id is None:
        return fail4("'Parent_id' must be a positive integer.", 400)
    if not non_empty_str(username) or not non_empty_str(password):
        return fail4("'username' and 'password' are required.", 400)

    row = get_db().execute(
        "SELECT * FROM EMPLOYEES WHERE Parent_id = ? AND username = ?",
        (parent_id, username),
    ).fetchone()
    if row is None or not verify_password(row["password"], password):
        return fail4("Invalid employee username or password.", 401)

    upgrade_password("EMPLOYEES", row["id"], row["password"], password)
    return jsonify({
        "error": False,
        "Employee_id": str(row["id"]),
        "CHAT_LOGS": load_chat_logs(row["CHAT_LOGS"]),
        "error_message": NULL,
    })


# ---------------------------------------------------------------------------
# API 5: POST /api/admin/employee/settings
# ---------------------------------------------------------------------------

@app.post(ROUTES["SETTINGS"])
def employee_settings():
    data = get_json_dict()
    if data is None:
        return fail3("Request body must be a JSON object.", 400)
    parent_id = to_int(data.get("Parent_id"))
    employee_id = to_int(data.get("Employee_id"))
    if parent_id is None:
        return fail3("'Parent_id' must be a positive integer.", 400)
    if employee_id is None:
        return fail3("'Employee_id' must be a positive integer.", 400)
    if employee_row(parent_id, employee_id) is None:
        return fail3(not_found_employee_message(parent_id, employee_id), 404)

    updates = {}
    for key in ("check1", "check2", "check3"):
        if key in data:
            if not isinstance(data[key], bool):
                return fail3(f"'{key}' must be true or false.", 400)
            updates[key] = 1 if data[key] else 0
    if "API_KEY" in data:
        if not isinstance(data["API_KEY"], str):
            return fail3("'API_KEY' must be a string.", 400)
        updates["API_KEY"] = data["API_KEY"]
    if "MODEL_NAME" in data:
        if not non_empty_str(data["MODEL_NAME"]):
            return fail3("'MODEL_NAME' must be a non-empty string.", 400)
        updates["MODEL_NAME"] = data["MODEL_NAME"].strip()

    create_default_settings(parent_id, employee_id)
    db = get_db()
    if updates:
        sets = ", ".join(f"{k} = ?" for k in updates)
        db.execute(
            f"UPDATE SETTINGS SET {sets} WHERE Parent_id = ? AND Employee_id = ?",
            (*updates.values(), parent_id, employee_id),
        )
        db.commit()

    row = get_settings(parent_id, employee_id)
    return jsonify(settings_payload(parent_id, employee_id, row))


# ---------------------------------------------------------------------------
# API 6: POST /api/admin/employee/chat
# ---------------------------------------------------------------------------

class ChatError(Exception):
    def __init__(self, message, status=500):
        super().__init__(message)
        self.message = message
        self.status = status


def chat_response(error=False, blocked=False, reply=NULL, message=NULL,
                  block_info=NULL, status=200):
    return jsonify({
        "error": error,
        "blocked": blocked,
        "reply_message": reply,
        "error_message": message,
        "block_info": block_info,
    }), status


def resolve_script(configured):
    """Find an ML script: configured path first, then testenv/MLscripts/<name>."""
    name = Path(configured).name
    candidates = [
        ROOT_DIR / configured,
        HERE.parent / "MLscripts" / name,
        ROOT_DIR / "testenv" / "MLscripts" / name,
    ]
    for c in candidates:
        if c.is_file():
            return c, candidates
    return None, candidates


def find_result_json(text):
    """
    Find the last JSON object in `text` that has a blocked-like field.
    Works for one-line JSON, pretty-printed JSON, and JSON surrounded by
    other log/print lines. Returns a dict (with a normalized 'blocked') or None.
    """
    decoder = json.JSONDecoder()
    found = []
    i = text.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(obj, dict):
            found.append(obj)
        i = text.find("{", end)
    for obj in reversed(found):
        for key in BLOCK_KEYS:
            if key in obj:
                result = dict(obj)
                result["blocked"] = bool(obj[key])
                return result
    return None


def _tail(text, n=300):
    text = (text or "").strip()
    return text[-n:]


def run_check(stage, prompt):
    """
    Run one ML script and return its result dict.

    Attempt 1: prompt on stdin.
    Attempt 2: prompt as a command-line argument.
    The script's stdout must contain a JSON object with a 'blocked' field
    (pretty-printed or surrounded by other output is fine).
    """
    key = dict(CHECKS)[stage]
    script, tried = resolve_script(PATHS[key])
    if script is None:
        raise ChatError(
            f"Script for {stage} not found. Tried: " + ", ".join(str(t) for t in tried))

    attempts = []
    for mode in ("stdin", "argument"):
        cmd = [sys.executable, str(script)]
        if mode == "argument":
            cmd.append(prompt)
        try:
            proc = subprocess.run(
                cmd, input=prompt if mode == "stdin" else "",
                capture_output=True, text=True, encoding="utf-8",
                timeout=CHECK_TIMEOUT, cwd=str(script.parent),
            )
        except subprocess.TimeoutExpired:
            raise ChatError(f"{stage} timed out after {CHECK_TIMEOUT}s.")
        except OSError as exc:
            raise ChatError(f"{stage} could not be started: {exc}")

        if proc.returncode == 0:
            result = find_result_json(proc.stdout or "")
            if result is not None:
                return result
        attempts.append(
            f"[{mode}] exit={proc.returncode} "
            f"stdout={_tail(proc.stdout)!r} stderr={_tail(proc.stderr)!r}"
        )

    raise ChatError(
        f"{stage}: could not find a JSON result with a 'blocked' field in the "
        f"script output. " + " | ".join(attempts)
    )


def build_block_info(stage, result):
    matches = result.get("matches")
    return {
        "blocked": True,
        "stage": stage,
        "score": result.get("score", NULL),
        "main_cause": result.get("main_cause", NULL),
        "line": result.get("line", NULL),
        "start_offset": result.get("start_offset", NULL),
        "end_offset": result.get("end_offset", NULL),
        "snippet": result.get("snippet", NULL),
        "matches": matches if isinstance(matches, list) else [],
    }


def call_openai(api_key, model, prompt):
    import time as _t
    _t0 = _t.time()
    print("CHAT DEBUG model=" + repr(model) + " key_len=" + str(len(api_key)), flush=True)
    try:
        from litellm import completion
        resp = completion(model=("gemini/" + model if model.startswith("gemini-") else model), messages=[{"role": "user", "content": prompt}], api_key=api_key, timeout=OPENAI_TIMEOUT)
        return resp.choices[0].message.content or ""
    except Exception as exc:
        print("CHAT DEBUG failed after " + str(round(_t.time() - _t0, 1)) + "s: " + type(exc).__name__ + ": " + str(exc)[:300], flush=True)
        raise ChatError(f"AI API Error: {exc}", 502)


@app.post(ROUTES["CHAT"])
def employee_chat():
    data = get_json_dict()
    if data is None:
        return chat_response(True, message="Request body must be a JSON object.",
                             status=400)
    try:
        parent_id = to_int(data.get("Parent_id"))
        employee_id = to_int(data.get("Employee_id"))
        if parent_id is None:
            raise ChatError("'Parent_id' must be a positive integer.", 400)
        if employee_id is None:
            raise ChatError("'Employee_id' must be a positive integer.", 400)

        emp = employee_row(parent_id, employee_id)
        if emp is None:
            raise ChatError(not_found_employee_message(parent_id, employee_id), 404)

        prompt = data.get("prompt")
        if not non_empty_str(prompt):
            raise ChatError("'prompt' must be a non-empty string.", 400)
        bypass = data.get("bypass", False)
        if not isinstance(bypass, bool):
            raise ChatError("'bypass' must be true or false.", 400)

        # Request values win, saved settings are the fallback.
        saved = get_settings(parent_id, employee_id)
        flags = {}
        for key in ("check1", "check2", "check3"):
            if key in data:
                if not isinstance(data[key], bool):
                    raise ChatError(f"'{key}' must be true or false.", 400)
                flags[key] = data[key]
            else:
                flags[key] = bool(saved[key])

        api_key = data.get("API_KEY")
        if not isinstance(api_key, str) or not api_key.strip():
            api_key = saved["API_KEY"] or ""
        api_key = api_key.strip()
        model = data.get("MODEL_NAME")
        if not non_empty_str(model):
            model = saved["MODEL_NAME"] or DEFAULT_MODEL
        model = model.strip()

        if not api_key:
            raise ChatError("No API_KEY provided.", 400)

        # Privacy checks (fail closed: any scanner error stops the request).
        if not bypass:
            for stage, _ in CHECKS:
                if not flags[stage]:
                    continue
                result = run_check(stage, prompt)
                if result.get("blocked"):
                    info = build_block_info(stage, result)
                    msg = (f"Blocked by {stage} ({info['main_cause']}): "
                           f"'{info['snippet']}' on line {info['line']}")
                    return chat_response(False, True, reply=NULL, message=msg, block_info=info)

        answer = call_openai(api_key, model, prompt)

        # Save to the chat history.
        logs = load_chat_logs(emp["CHAT_LOGS"])
        logs.append({"prompt": prompt, "answer": answer})
        db = get_db()
        db.execute("UPDATE EMPLOYEES SET CHAT_LOGS = ? WHERE id = ?",
                   (json.dumps(logs, ensure_ascii=False), employee_id))
        db.commit()

        return chat_response(False, False, reply=answer)

    except ChatError as exc:
        return chat_response(True, message=exc.message, status=exc.status)


# ---------------------------------------------------------------------------
# Seed + startup
# ---------------------------------------------------------------------------

def seed():
    con = sqlite3.connect(DB_FILE)
    row = con.execute("SELECT id FROM ADMINS WHERE username = ?", ("johann",)).fetchone()
    if row is None:
        con.execute("INSERT INTO ADMINS (username, password) VALUES (?, ?)",
                    ("johann", generate_password_hash("admin_secret_123")))
        con.commit()
        print("Created admin johann / admin_secret_123")
    else:
        print("Admin johann already exists.")
    con.close()


init_db()
check_schema()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "seed":
        seed()
        sys.exit(0)

    print("Constants file:", CONSTANTS_FILE)
    print("Database file :", DB_FILE)
    print("AI endpoint   :", OPENAI_URL)
    print("Routes:")
    for rule in app.url_map.iter_rules():
        if rule.endpoint != "static":
            print(f"  {sorted(rule.methods - {'HEAD', 'OPTIONS'})}  {rule.rule}")
    app.run(host=HOST, port=PORT, debug=True)
