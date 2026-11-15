from datetime import datetime, timezone

from admin_session import _connect

TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS BLOCK_LOG ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "Parent_id INTEGER NOT NULL, "
    "Employee_id INTEGER NOT NULL, "
    "stage TEXT NOT NULL, "
    "reason TEXT NOT NULL, "
    "created_at TEXT NOT NULL)"
)


def _open(db_file):
    con = _connect(db_file)
    con.execute(TABLE_SQL)
    return con


def record_block(db_file, parent_id, employee_id, stage, reason):
    con = _open(db_file)
    con.execute(
        "INSERT INTO BLOCK_LOG (Parent_id, Employee_id, stage, reason, created_at) VALUES (?, ?, ?, ?, ?)",
        (parent_id, employee_id, str(stage or "unknown")[:40], str(reason or "Unspecified")[:200], datetime.now(timezone.utc).isoformat()),
    )
    con.commit()
    con.close()


def block_rows(db_file, parent_id):
    con = _open(db_file)
    rows = con.execute(
        "SELECT Employee_id, stage, reason FROM BLOCK_LOG WHERE Parent_id = ?",
        (parent_id,),
    ).fetchall()
    con.close()
    return rows
