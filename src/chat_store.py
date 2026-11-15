"""Chat storage: one CHATS row per conversation, plus lifetime answer counts.
EMPLOYEE_STATS keeps the answered total even after a chat is deleted,
so deleting a chat never lowers the admin team stats.
"""
import json
from datetime import datetime, timezone

from flask import jsonify, request

from admin_session import _connect

EARLIER_TITLE = "Earlier chat"
TITLE_LEN = 48

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS CHATS (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    Parent_id   INTEGER NOT NULL,
    Employee_id INTEGER NOT NULL,
    title       TEXT NOT NULL,
    messages    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chats_owner ON CHATS (Parent_id, Employee_id);
CREATE TABLE IF NOT EXISTS EMPLOYEE_STATS (
    Parent_id   INTEGER NOT NULL,
    Employee_id INTEGER NOT NULL,
    answered    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (Parent_id, Employee_id)
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load(raw):
    try:
        items = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return items if isinstance(items, list) else []


def make_title(prompt):
    text = " ".join(str(prompt).split())
    if len(text) <= TITLE_LEN:
        return text
    return text[:TITLE_LEN - 3].rstrip() + "..."


def migrate_legacy(db_file):
    con = _connect(db_file)
    moved = 0
    for emp in con.execute("SELECT id, Parent_id, CHAT_LOGS FROM EMPLOYEES").fetchall():
        logs = _load(emp["CHAT_LOGS"])
        has_stats = con.execute(
            "SELECT 1 FROM EMPLOYEE_STATS WHERE Parent_id = ? AND Employee_id = ?",
            (emp["Parent_id"], emp["id"]),
        ).fetchone()
        if has_stats is None:
            con.execute(
                "INSERT INTO EMPLOYEE_STATS (Parent_id, Employee_id, answered) VALUES (?, ?, ?)",
                (emp["Parent_id"], emp["id"], len(logs)),
            )
        if logs:
            now = _now()
            con.execute(
                "INSERT INTO CHATS (Parent_id, Employee_id, title, messages, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (emp["Parent_id"], emp["id"], EARLIER_TITLE,
                 json.dumps(logs, ensure_ascii=False), now, now),
            )
            con.execute("UPDATE EMPLOYEES SET CHAT_LOGS = ? WHERE id = ?", ("[]", emp["id"]))
            moved += 1
    con.commit()
    con.close()
    return moved


def init_tables(db_file):
    con = _connect(db_file)
    con.executescript(TABLE_SQL)
    has_employees = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?", ("table", "EMPLOYEES")
    ).fetchone()
    con.close()
    if has_employees:
        moved = migrate_legacy(db_file)
        if moved:
            print(f"chat_store: moved old chat history for {moved} team member(s) into CHATS.")


def bump_answered(db_file, parent_id, employee_id):
    con = _connect(db_file)
    con.execute(
        "INSERT OR IGNORE INTO EMPLOYEE_STATS (Parent_id, Employee_id, answered) VALUES (?, ?, 0)",
        (parent_id, employee_id),
    )
    con.execute(
        "UPDATE EMPLOYEE_STATS SET answered = answered + 1 WHERE Parent_id = ? AND Employee_id = ?",
        (parent_id, employee_id),
    )
    con.commit()
    con.close()


def list_chats(db_file, parent_id, employee_id):
    con = _connect(db_file)
    rows = con.execute(
        "SELECT id, title, messages, updated_at FROM CHATS "
        "WHERE Parent_id = ? AND Employee_id = ? ORDER BY updated_at DESC, id DESC",
        (parent_id, employee_id),
    ).fetchall()
    con.close()
    return [
        {"id": r["id"], "title": r["title"], "updated_at": r["updated_at"],
         "exchanges": len(_load(r["messages"]))}
        for r in rows
    ]


def get_chat(db_file, parent_id, employee_id, chat_id):
    con = _connect(db_file)
    row = con.execute(
        "SELECT id, title, messages FROM CHATS WHERE id = ? AND Parent_id = ? AND Employee_id = ?",
        (chat_id, parent_id, employee_id),
    ).fetchone()
    con.close()
    if row is None:
        return None
    return {"id": row["id"], "title": row["title"], "messages": _load(row["messages"])}


def newest_chat(db_file, parent_id, employee_id):
    con = _connect(db_file)
    row = con.execute(
        "SELECT id FROM CHATS WHERE Parent_id = ? AND Employee_id = ? "
        "ORDER BY updated_at DESC, id DESC LIMIT 1",
        (parent_id, employee_id),
    ).fetchone()
    con.close()
    return get_chat(db_file, parent_id, employee_id, row["id"]) if row else None


def save_exchange(db_file, parent_id, employee_id, chat_id, prompt, answer):
    now = _now()
    con = _connect(db_file)
    if chat_id is None:
        cur = con.execute(
            "INSERT INTO CHATS (Parent_id, Employee_id, title, messages, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (parent_id, employee_id, make_title(prompt),
             json.dumps([{"prompt": prompt, "answer": answer}], ensure_ascii=False), now, now),
        )
        chat_id = cur.lastrowid
    else:
        row = con.execute(
            "SELECT messages FROM CHATS WHERE id = ? AND Parent_id = ? AND Employee_id = ?",
            (chat_id, parent_id, employee_id),
        ).fetchone()
        messages = _load(row["messages"]) if row else []
        messages.append({"prompt": prompt, "answer": answer})
        con.execute(
            "UPDATE CHATS SET messages = ?, updated_at = ? WHERE id = ? AND Parent_id = ? AND Employee_id = ?",
            (json.dumps(messages, ensure_ascii=False), now, chat_id, parent_id, employee_id),
        )
    con.commit()
    con.close()
    return chat_id


def rename_chat(db_file, parent_id, employee_id, chat_id, title):
    con = _connect(db_file)
    cur = con.execute(
        "UPDATE CHATS SET title = ? WHERE id = ? AND Parent_id = ? AND Employee_id = ?",
        (title, chat_id, parent_id, employee_id),
    )
    con.commit()
    changed = cur.rowcount > 0
    con.close()
    return changed


def delete_chat(db_file, parent_id, employee_id, chat_id):
    con = _connect(db_file)
    cur = con.execute(
        "DELETE FROM CHATS WHERE id = ? AND Parent_id = ? AND Employee_id = ?",
        (chat_id, parent_id, employee_id),
    )
    con.commit()
    deleted = cur.rowcount > 0
    con.close()
    return deleted


def _ids(data):
    if not isinstance(data, dict):
        return None
    try:
        return int(data.get("Parent_id")), int(data.get("Employee_id"))
    except (TypeError, ValueError):
        return None


def _chat_id(data):
    if not isinstance(data, dict):
        return None
    try:
        return int(data.get("chat_id"))
    except (TypeError, ValueError):
        return None


def register(app, db_file):
    @app.post("/api/admin/employee/chats")
    def chats_list():
        ids = _ids(request.get_json(silent=True))
        if ids is None:
            return jsonify({"error": True, "error_message": "Parent_id and Employee_id are required."}), 400
        return jsonify({"error": False, "chats": list_chats(db_file, ids[0], ids[1])})

    @app.post("/api/admin/employee/chats/open")
    def chats_open():
        data = request.get_json(silent=True)
        ids, chat_id = _ids(data), _chat_id(data)
        if ids is None or chat_id is None:
            return jsonify({"error": True, "error_message": "Parent_id, Employee_id and chat_id are required."}), 400
        chat = get_chat(db_file, ids[0], ids[1], chat_id)
        if chat is None:
            return jsonify({"error": True, "error_message": "That chat was not found."}), 404
        return jsonify({"error": False, "chat": chat})

    @app.post("/api/admin/employee/chats/delete")
    def chats_delete():
        data = request.get_json(silent=True)
        ids, chat_id = _ids(data), _chat_id(data)
        if ids is None or chat_id is None:
            return jsonify({"error": True, "error_message": "Parent_id, Employee_id and chat_id are required."}), 400
        if not delete_chat(db_file, ids[0], ids[1], chat_id):
            return jsonify({"error": True, "error_message": "That chat was not found."}), 404
        return jsonify({"error": False, "deleted": chat_id})

    @app.post("/api/admin/employee/chats/rename")
    def chats_rename():
        data = request.get_json(silent=True)
        ids, chat_id = _ids(data), _chat_id(data)
        if ids is None or chat_id is None:
            return jsonify({"error": True, "error_message": "Parent_id, Employee_id and chat_id are required."}), 400
        title = " ".join(str(data.get("title") or "").split())[:80]
        if not title:
            return jsonify({"error": True, "error_message": "Title cannot be empty."}), 400
        if not rename_chat(db_file, ids[0], ids[1], chat_id, title):
            return jsonify({"error": True, "error_message": "That chat was not found."}), 404
        return jsonify({"error": False, "chat_id": chat_id, "title": title})
