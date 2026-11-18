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
from contextlib import closing
from datetime import datetime, timezone

from auth import _connect
from redaction import retained_redactions

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


def normalise_title(value):
    """Use the same title rules on chat creation and rename."""
    if not isinstance(value, str):
        return ""
    try:
        value.encode("utf-8")
    except UnicodeError:
        return ""
    return " ".join(value.split())[:80].rstrip()


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
    con.execute("BEGIN IMMEDIATE")
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
    con.execute("BEGIN IMMEDIATE")  # legacy message-id normalization may write
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

def _mutate(db_file, parent_id, employee_id, chat_id, change, *, retitle=None):
    """Serialize the complete read/modify/write, including legacy ID assignment."""
    with closing(_connect(db_file)) as con, con:
        con.execute("BEGIN IMMEDIATE")
        ids = (chat_id, parent_id, employee_id)
        row = con.execute("SELECT title, messages FROM CHATS WHERE id=? AND Parent_id=? AND Employee_id=?", ids).fetchone()
        if row is None:
            con.rollback()
            return None
        messages = normalise(_load(row["messages"]))[0]
        if not change(messages):
            return None
        title = retitle(row["title"], messages) if retitle else row["title"]
        con.execute("UPDATE CHATS SET title=?, messages=?, updated_at=? WHERE id=? AND Parent_id=? AND Employee_id=?",
                    (title, _dump(messages), _now(), *ids))
        return messages


def save_exchange(db_file, parent_id, employee_id, chat_id, prompt, answer, blocked=False, block_info=None,
                  *, redaction_info=None, metadata_only=False, title=None):
    now = _now()
    entry = {"id": _new_id(), "prompt": prompt, "answer": answer, "created_at": now,
             "blocked": bool(blocked), "edited": False}
    if blocked and block_info:
        entry["block_info"] = block_info
    if redaction_info:
        entry.update(redacted=True, redaction_info=redaction_info)
    if metadata_only:
        entry["metadata_only"] = True
    if chat_id is None:
        with closing(_connect(db_file)) as con, con:
            # A member may have been offboarded while the provider was answering.
            cur = con.execute("INSERT INTO CHATS (Parent_id, Employee_id, title, messages, created_at, updated_at) "
                              "SELECT Parent_id, id, ?, ?, ?, ? FROM EMPLOYEES WHERE Parent_id=? AND id=?",
                              (title or make_title(prompt), _dump([entry]), now, now, parent_id, employee_id))
            if not cur.rowcount:
                return None, None
            chat_id = cur.lastrowid
    else:
        def append(messages):
            messages.append(entry)
            return True
        if _mutate(db_file, parent_id, employee_id, chat_id, append) is None:
            return None, None
    return chat_id, entry


def _change_entry(db_file, parent_id, employee_id, chat_id, message_id, change, *, retitle=None):
    def apply(messages):
        for i, entry in enumerate(messages):
            if entry.get("id") != message_id:
                continue
            if change is None:
                del messages[i]
                return True
            return change(entry)
        return False
    return _mutate(db_file, parent_id, employee_id, chat_id, apply, retitle=retitle)


def _redaction_metadata(entry, info):
    if info:
        entry.update(redacted=True, redaction_info=info, metadata_only=True)
        entry.pop("block_info", None)  # legacy evidence may contain original text
    else:
        entry.pop("redacted", None)
        entry.pop("redaction_info", None)


def _redacted_title(message_id, previous_prompt, safe_prompt):
    """Replace an auto-title derived from a formerly unsanitized first prompt."""
    def retitle(title, messages):
        if messages and messages[0].get("id") == message_id and title == make_title(previous_prompt):
            return make_title(safe_prompt)
        return title
    return retitle


def edit_message(db_file, parent_id, employee_id, chat_id, message_id, text, *, redaction=None):
    if redaction:
        text = redaction.prompt
    previous = None

    def change(entry):
        nonlocal previous
        previous = entry.get("prompt")
        info = redaction.info if redaction else retained_redactions(text, entry)
        _redaction_metadata(entry, info)
        if redaction and isinstance(entry.get("answer"), str):
            # A reply from before the edit may have echoed the very values
            # we are masking now. Don't leave those echoes in a redacted row.
            entry["answer"] = redaction.un_restored_reply(entry["answer"])
        entry.update(prompt=text, edited=True, edited_at=_now())
        return True

    def retitle(title, messages):
        return _redacted_title(message_id, previous, text)(title, messages)

    return _change_entry(db_file, parent_id, employee_id, chat_id, message_id, change,
                         retitle=retitle if redaction else None)


def delete_message(db_file, parent_id, employee_id, chat_id, message_id):
    return _change_entry(db_file, parent_id, employee_id, chat_id, message_id, None)


def replace_answer(db_file, parent_id, employee_id, chat_id, message_id, answer, *,
                   expected_prompt=None, sent_prompt=None, redaction_info=None, metadata_only=False):
    def change(entry):
        if expected_prompt is not None and entry.get("prompt") != expected_prompt:
            return False  # a newer edit arrived while the provider was answering
        if sent_prompt is not None and sent_prompt != expected_prompt:
            entry.update(prompt=sent_prompt, edited=True, edited_at=_now())
        entry.update(answer=answer, regenerated_at=_now())
        if sent_prompt is not None:
            _redaction_metadata(entry, redaction_info)
        if metadata_only:
            entry["metadata_only"] = True
        return True
    retitle = _redacted_title(message_id, expected_prompt, sent_prompt) if redaction_info else None
    return _change_entry(db_file, parent_id, employee_id, chat_id, message_id, change, retitle=retitle)


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
        items = _load(row["messages"])
        if any(isinstance(m, dict) and not m.get("id") for m in items):
            # A search hit needs the same legacy message ID when opened.
            chat = get_chat(db_file, parent_id, employee_id, row["id"])
            items = chat["messages"] if chat else []
        for item in items:
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
