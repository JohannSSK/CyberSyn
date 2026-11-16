"""Chat storage.

One CHATS row per conversation, with the messages kept as a JSON array so a
whole chat is a single read. Each message carries an id and a timestamp,
which is what makes editing, deleting and regenerating a single message
possible, and what the statistics page charts.

EMPLOYEE_STATS keeps a lifetime answer count, so deleting a chat never
lowers the team numbers.
"""

import json
import secrets
from datetime import datetime, timezone

from auth import _connect

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


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc).isoformat()


def _load(raw):
    try:
        items = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return items if isinstance(items, list) else []


def _dump(messages):
    return json.dumps(messages, ensure_ascii=False)


def _new_id():
    return secrets.token_hex(8)


def make_title(prompt):
    text = " ".join(str(prompt).split())
    if len(text) <= TITLE_LEN:
        return text
    return text[:TITLE_LEN - 3].rstrip() + "..."


def normalise(messages):
    """Give every message an id and a timestamp.

    Chats written before this change have neither, so they are filled in
    here rather than by a migration that could fail halfway.
    """
    changed = False
    for index, item in enumerate(messages):
        if not isinstance(item, dict):
            continue
        if not item.get("id"):
            item["id"] = f"m{index}_{_new_id()}"
            changed = True
        if not item.get("created_at"):
            item["created_at"] = _now()
            changed = True
        item.setdefault("blocked", False)
        item.setdefault("edited", False)
    return messages, changed


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

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
                "INSERT INTO EMPLOYEE_STATS (Parent_id, Employee_id, answered) "
                "VALUES (?, ?, ?)",
                (emp["Parent_id"], emp["id"], len(logs)),
            )
        if logs:
            now = _now()
            con.execute(
                "INSERT INTO CHATS (Parent_id, Employee_id, title, messages, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (emp["Parent_id"], emp["id"], EARLIER_TITLE, _dump(logs), now, now),
            )
            con.execute(
                "UPDATE EMPLOYEES SET CHAT_LOGS = ? WHERE id = ?", ("[]", emp["id"])
            )
            moved += 1
    con.commit()
    con.close()
    return moved


def init_tables(db_file):
    con = _connect(db_file)
    con.executescript(TABLE_SQL)
    has_employees = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?",
        ("table", "EMPLOYEES"),
    ).fetchone()
    con.close()
    if has_employees:
        moved = migrate_legacy(db_file)
        if moved:
            print(f"chat_store: moved old chat history for {moved} member(s) into CHATS.")


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------

def list_chats(db_file, parent_id, employee_id):
    con = _connect(db_file)
    rows = con.execute(
        "SELECT id, title, messages, updated_at, created_at FROM CHATS "
        "WHERE Parent_id = ? AND Employee_id = ? ORDER BY updated_at DESC, id DESC",
        (parent_id, employee_id),
    ).fetchall()
    con.close()
    return [
        {"id": r["id"], "title": r["title"], "updated_at": r["updated_at"],
         "created_at": r["created_at"], "exchanges": len(_load(r["messages"]))}
        for r in rows
    ]


def get_chat(db_file, parent_id, employee_id, chat_id):
    con = _connect(db_file)
    row = con.execute(
        "SELECT id, title, messages FROM CHATS WHERE id = ? AND Parent_id = ? "
        "AND Employee_id = ?",
        (chat_id, parent_id, employee_id),
    ).fetchone()
    if row is None:
        con.close()
        return None

    messages, changed = normalise(_load(row["messages"]))
    if changed:
        con.execute(
            "UPDATE CHATS SET messages = ? WHERE id = ?", (_dump(messages), chat_id)
        )
        con.commit()
    con.close()
    return {"id": row["id"], "title": row["title"], "messages": messages}


def newest_chat(db_file, parent_id, employee_id):
    con = _connect(db_file)
    row = con.execute(
        "SELECT id FROM CHATS WHERE Parent_id = ? AND Employee_id = ? "
        "ORDER BY updated_at DESC, id DESC LIMIT 1",
        (parent_id, employee_id),
    ).fetchone()
    con.close()
    return get_chat(db_file, parent_id, employee_id, row["id"]) if row else None


def bump_answered(db_file, parent_id, employee_id):
    con = _connect(db_file)
    con.execute(
        "INSERT OR IGNORE INTO EMPLOYEE_STATS (Parent_id, Employee_id, answered) "
        "VALUES (?, ?, 0)",
        (parent_id, employee_id),
    )
    con.execute(
        "UPDATE EMPLOYEE_STATS SET answered = answered + 1 WHERE Parent_id = ? "
        "AND Employee_id = ?",
        (parent_id, employee_id),
    )
    con.commit()
    con.close()


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------

def _write_messages(db_file, parent_id, employee_id, chat_id, messages):
    con = _connect(db_file)
    cur = con.execute(
        "UPDATE CHATS SET messages = ?, updated_at = ? WHERE id = ? AND "
        "Parent_id = ? AND Employee_id = ?",
        (_dump(messages), _now(), chat_id, parent_id, employee_id),
    )
    con.commit()
    ok = cur.rowcount > 0
    con.close()
    return ok


def save_exchange(db_file, parent_id, employee_id, chat_id, prompt, answer,
                  blocked=False, block_info=None):
    """Append one exchange, creating the chat when chat_id is None."""
    now = _now()
    entry = {
        "id": _new_id(),
        "prompt": prompt,
        "answer": answer,
        "created_at": now,
        "blocked": bool(blocked),
        "edited": False,
    }
    if blocked and block_info:
        entry["block_info"] = block_info

    con = _connect(db_file)
    if chat_id is None:
        cur = con.execute(
            "INSERT INTO CHATS (Parent_id, Employee_id, title, messages, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (parent_id, employee_id, make_title(prompt), _dump([entry]), now, now),
        )
        chat_id = cur.lastrowid
        messages = [entry]
    else:
        row = con.execute(
            "SELECT messages FROM CHATS WHERE id = ? AND Parent_id = ? AND "
            "Employee_id = ?",
            (chat_id, parent_id, employee_id),
        ).fetchone()
        messages = normalise(_load(row["messages"]))[0] if row else []
        messages.append(entry)
        con.execute(
            "UPDATE CHATS SET messages = ?, updated_at = ? WHERE id = ? AND "
            "Parent_id = ? AND Employee_id = ?",
            (_dump(messages), now, chat_id, parent_id, employee_id),
        )
    con.commit()
    con.close()
    return chat_id, entry


def edit_message(db_file, parent_id, employee_id, chat_id, message_id, text):
    """Replace the text of one message the member sent."""
    chat = get_chat(db_file, parent_id, employee_id, chat_id)
    if chat is None:
        return None
    for item in chat["messages"]:
        if item.get("id") == message_id:
            item["prompt"] = text
            item["edited"] = True
            item["edited_at"] = _now()
            break
    else:
        return None
    if not _write_messages(db_file, parent_id, employee_id, chat_id, chat["messages"]):
        return None
    return chat["messages"]


def delete_message(db_file, parent_id, employee_id, chat_id, message_id):
    chat = get_chat(db_file, parent_id, employee_id, chat_id)
    if chat is None:
        return None
    remaining = [m for m in chat["messages"] if m.get("id") != message_id]
    if len(remaining) == len(chat["messages"]):
        return None
    if not _write_messages(db_file, parent_id, employee_id, chat_id, remaining):
        return None
    return remaining


def replace_answer(db_file, parent_id, employee_id, chat_id, message_id, answer):
    """Store a regenerated answer for one message."""
    chat = get_chat(db_file, parent_id, employee_id, chat_id)
    if chat is None:
        return None
    for item in chat["messages"]:
        if item.get("id") == message_id:
            item["answer"] = answer
            item["regenerated_at"] = _now()
            break
    else:
        return None
    if not _write_messages(db_file, parent_id, employee_id, chat_id, chat["messages"]):
        return None
    return chat["messages"]


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


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

def search(db_file, parent_id, employee_id, query, limit=50):
    """Find messages containing `query`, case-insensitively.

    Returns the matching messages with their chat, so the browser can jump
    straight to the conversation.
    """
    needle = (query or "").strip().lower()
    if not needle:
        return []
    con = _connect(db_file)
    rows = con.execute(
        "SELECT id, title, messages FROM CHATS WHERE Parent_id = ? AND "
        "Employee_id = ? ORDER BY updated_at DESC",
        (parent_id, employee_id),
    ).fetchall()
    con.close()

    hits = []
    for row in rows:
        for item in normalise(_load(row["messages"]))[0]:
            if not isinstance(item, dict):
                continue
            prompt, answer = str(item.get("prompt", "")), str(item.get("answer", ""))
            haystack = f"{prompt}\n{answer}".lower()
            if needle in haystack:
                index = haystack.find(needle)
                start = max(0, index - 40)
                hits.append({
                    "chat_id": row["id"],
                    "chat_title": row["title"],
                    "message_id": item.get("id"),
                    "prompt": prompt,
                    "answer": answer,
                    "created_at": item.get("created_at"),
                    "excerpt": ("…" if start else "")
                    + f"{prompt}\n{answer}"[start:start + 160]
                    + ("…" if len(haystack) > start + 160 else ""),
                })
                if len(hits) >= limit:
                    return hits
    return hits
