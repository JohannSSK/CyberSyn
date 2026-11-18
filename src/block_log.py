"""The audit trail.

Two tables:

BLOCK_LOG  — every time the gate stopped or overrode a prompt. This is the
             compliance record, and it is never pruned by the app.
ACTIVITY_LOG — member and workspace activity, including metadata-only copies
               of block/override decisions for audit consumers.

Both are append-only. Deleting a chat does not touch either, so the team
numbers stay honest.
"""

from contextlib import closing
from datetime import datetime, timezone

from auth import _connect

BLOCK_SQL = (
    "CREATE TABLE IF NOT EXISTS BLOCK_LOG ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "Parent_id INTEGER NOT NULL, "
    "Employee_id INTEGER NOT NULL, "
    "stage TEXT NOT NULL, "
    "reason TEXT NOT NULL, "
    "created_at TEXT NOT NULL)"
)

ACTIVITY_SQL = (
    "CREATE TABLE IF NOT EXISTS ACTIVITY_LOG ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "Parent_id INTEGER NOT NULL, "
    "Employee_id INTEGER NOT NULL, "
    "kind TEXT NOT NULL, "
    "detail TEXT, "
    "created_at TEXT NOT NULL)"
)
ACTIVITY_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_activity_owner "
    "ON ACTIVITY_LOG (Parent_id, Employee_id, created_at DESC)"
)

# Kinds stored in ACTIVITY_LOG. One place, so the label map cannot drift.
KIND_LABELS = {
    "login": "Signed in",
    "prompt": "Message sent",
    "blocked": "Message blocked",
    "override": "Override approved",
    "settings": "Policy changed",
    "chat_created": "Chat started",
    "chat_deleted": "Chat deleted",
    "message_edited": "Message edited",
    "message_deleted": "Message deleted",
    "regenerated": "Answer regenerated",
    "logout": "Signed out",
    "warned": "Message paused",
    "warn_proceeded": "Warning confirmed",
    "redacted": "Message redacted",
    "shadow_policy": "AI tool policy changed",
    "shadow_import": "Discovery logs imported",
    "shadow_clear": "Discovery logs cleared",
}


def init(db_file):
    con = _connect(db_file)
    con.execute(BLOCK_SQL)
    con.execute(ACTIVITY_SQL)
    con.execute(ACTIVITY_INDEX)
    con.commit()
    con.close()


def _now():
    return datetime.now(timezone.utc).isoformat()


def record_block(db_file, parent_id, employee_id, stage, reason, *, activity_detail=None):
    """Write the canonical decision and its optional audit copy atomically."""
    with closing(_connect(db_file)) as con, con:
        con.execute(BLOCK_SQL)
        con.execute(
            "INSERT INTO BLOCK_LOG (Parent_id, Employee_id, stage, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (parent_id, employee_id, str(stage or "unknown")[:40],
             str(reason or "Unspecified")[:200], _now()),
        )
        if activity_detail is not None:
            kind = "override" if stage == "override" else "blocked"
            record_activity(db_file, parent_id, employee_id, kind, activity_detail, con=con)


def record_activity(db_file, parent_id, employee_id, kind, detail=None, *, con=None):
    """Record one step, optionally as part of the caller's transaction."""
    if con is None:
        with closing(_connect(db_file)) as con, con:
            return record_activity(db_file, parent_id, employee_id, kind, detail, con=con)
    con.execute(ACTIVITY_SQL)
    con.execute(ACTIVITY_INDEX)
    con.execute(
        "INSERT INTO ACTIVITY_LOG (Parent_id, Employee_id, kind, detail, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (parent_id, employee_id, str(kind)[:40],
         None if detail is None else str(detail)[:200], _now()),
    )


def block_rows(db_file, parent_id, employee_id=None):
    con = _connect(db_file)
    con.execute(BLOCK_SQL)
    if employee_id is None:
        rows = con.execute(
            "SELECT Employee_id, stage, reason, created_at FROM BLOCK_LOG "
            "WHERE Parent_id = ? ORDER BY created_at DESC",
            (parent_id,),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT Employee_id, stage, reason, created_at FROM BLOCK_LOG "
            "WHERE Parent_id = ? AND Employee_id = ? ORDER BY created_at DESC",
            (parent_id, employee_id),
        ).fetchall()
    con.close()
    return rows


def activity_rows(db_file, parent_id, employee_id=None, limit=200):
    """Most recent steps first."""
    con = _connect(db_file)
    con.execute(ACTIVITY_SQL)
    con.execute(ACTIVITY_INDEX)
    if employee_id is None:
        rows = con.execute(
            "SELECT Employee_id, kind, detail, created_at FROM ACTIVITY_LOG "
            "WHERE Parent_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (parent_id, limit),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT Employee_id, kind, detail, created_at FROM ACTIVITY_LOG "
            "WHERE Parent_id = ? AND Employee_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (parent_id, employee_id, limit),
        ).fetchall()
    con.close()
    return rows


def regeneration_counts(db_file, parent_id):
    """Successful regenerations are logged after the replacement is saved."""
    with closing(_connect(db_file)) as con:
        con.execute(ACTIVITY_SQL)
        return dict(con.execute(
            "SELECT Employee_id, COUNT(*) FROM ACTIVITY_LOG "
            "WHERE Parent_id = ? AND kind = 'regenerated' GROUP BY Employee_id", (parent_id,),
        ).fetchall())


def timeline(db_file, parent_id, employee_id=None, limit=300):
    """Merge canonical decisions and other activity without changing either log.

    Decision writers always record BLOCK_LOG first, even on legacy databases.
    ACTIVITY_LOG decision rows are audit copies, not additional attempts. Don't
    deduplicate by timestamp or reason: two canonical rows are two decisions.
    """
    scope = "Parent_id = ?"
    params = (parent_id,)
    if employee_id is not None:
        scope += " AND Employee_id = ?"
        params += (employee_id,)
    with closing(_connect(db_file)) as con:
        con.execute(BLOCK_SQL)
        con.execute(ACTIVITY_SQL)
        rows = con.execute(f"""
            SELECT Employee_id AS employee_id, created_at AS at,
                   CASE WHEN stage = 'override' THEN 'override' ELSE 'blocked' END AS kind,
                   stage, reason AS detail, id
            FROM BLOCK_LOG WHERE {scope}
            UNION ALL
            SELECT Employee_id, created_at, kind, NULL, detail, id
            FROM ACTIVITY_LOG WHERE {scope} AND kind NOT IN ('blocked', 'override')
            ORDER BY at DESC, id DESC LIMIT ?
        """, params + params + (limit,)).fetchall()
    return [{key: row[key] for key in ("employee_id", "at", "kind", "stage", "detail")} for row in rows]


def daily_counts(db_file, parent_id, employee_id=None, days=30):
    """Blocks and overrides per day, oldest first, for the trend chart."""
    con = _connect(db_file)
    con.execute(BLOCK_SQL)
    if employee_id is None:
        rows = con.execute(
            "SELECT created_at, stage FROM BLOCK_LOG WHERE Parent_id = ?",
            (parent_id,),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT created_at, stage FROM BLOCK_LOG WHERE Parent_id = ? "
            "AND Employee_id = ?",
            (parent_id, employee_id),
        ).fetchall()
    con.close()

    from collections import OrderedDict
    from datetime import timedelta

    today = datetime.now(timezone.utc).date()
    buckets = OrderedDict()
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        buckets[day.isoformat()] = {"date": day.isoformat(), "blocked": 0,
                                    "overrides": 0}

    for r in rows:
        raw = r["created_at"] or ""
        try:
            day = datetime.fromisoformat(raw).date().isoformat()
        except ValueError:
            continue
        if day not in buckets:
            continue
        if r["stage"] == "override":
            buckets[day]["overrides"] += 1
        else:
            buckets[day]["blocked"] += 1

    return list(buckets.values())
