from flask import Flask, jsonify, render_template, request
import sqlite3, os, json

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
with open(
    os.path.join(ROOT_DIR, "includes/constants.json"), "r", encoding="utf-8"
) as f:
    CONST = json.load(f)

DB_PATH = os.path.join(ROOT_DIR, CONST["PATHS"]["DB_FILE"])
FRONTEND_DIR = os.path.join(ROOT_DIR, CONST["PATHS"]["FRONTEND_DIR"])
ASSETS_DIR = os.path.join(ROOT_DIR, CONST["PATHS"]["ASSETS_DIR"])
CHECK1_SCRIPT = os.path.join(ROOT_DIR, CONST["PATHS"]["CHECK1_SCRIPT"])
CHECK2_SCRIPT = os.path.join(ROOT_DIR, CONST["PATHS"]["CHECK2_SCRIPT"])
CHECK3_SCRIPT = os.path.join(ROOT_DIR, CONST["PATHS"]["CHECK3_SCRIPT"])

app = Flask(
    __name__,
    template_folder=FRONTEND_DIR,
    static_folder=FRONTEND_DIR,
    static_url_path="",
)


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS ADMINS (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS EMPLOYEES (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Parent_id TEXT,
            username TEXT,
            password TEXT,
            CHAT_LOGS TEXT DEFAULT '[]'
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS SETTINGS (
            Parent_id TEXT,
            Employee_id TEXT,
            check1 INTEGER DEFAULT 1,
            check2 INTEGER DEFAULT 1,
            check3 INTEGER DEFAULT 1,
            API_KEY TEXT DEFAULT '',
            MODEL_NAME TEXT DEFAULT 'gpt-4o-mini'
        )""")


app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json()
    # TODO: Backend implements this
    return jsonify({})


@app.route("/api/admin", methods=["POST"])
def admin_add_remove():
    data = request.get_json()
    # TODO: Backend implements this
    return jsonify({})


@app.route("/api/admin/employee", methods=["POST"])
def employee_add_remove():
    data = request.get_json()
    # TODO: Backend implements this
    return jsonify({})


@app.route("/api/admin/employee/login", methods=["POST"])
def employee_login():
    data = request.get_json()
    # TODO: Backend implements this
    return jsonify({})


@app.route("/api/admin/employee/settings", methods=["POST"])
def settings_update():
    data = request.get_json()
    # TODO: Backend implements this
    return jsonify({})


@app.route("/api/admin/employee/chat", methods=["POST"])
def chat():
    data = request.get_json()
    # TODO: Backend implements this
    return jsonify({})


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
