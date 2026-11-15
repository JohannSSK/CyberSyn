import json
from datetime import datetime, timezone

from flask import jsonify, request

from admin_session import _connect, _hash
from block_log import block_rows


def admin_from_token(db_file, token):
    if not isinstance(token, str) or not token.strip():
        return None
    con = _connect(db_file)
    row = con.execute(
        "SELECT a.id, a.username, s.expires_at FROM ADMIN_SESSIONS s "
        "JOIN ADMINS a ON a.id = s.admin_id WHERE s.token_hash = ?",
        (_hash(token.strip()),),
    ).fetchone()
    con.close()
    if row is None:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        return None
    return row


def count_answered(raw):
    try:
        logs = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return 0
    return len(logs) if isinstance(logs, list) else 0


def pct(part, whole):
    return round(100 * part / whole) if whole else 0


def tally(items):
    counts = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts


def ranked(counts, total):
    rows = [{"label": k, "count": v, "percent": pct(v, total)} for k, v in counts.items()]
    return sorted(rows, key=lambda r: (-r["count"], r["label"]))


def register(app, db_file):
    @app.post("/api/admin/team")
    def admin_team_stats():
        data = request.get_json(silent=True)
        token = data.get("token") if isinstance(data, dict) else None
        admin = admin_from_token(db_file, token)
        if admin is None:
            return jsonify({"error": True, "error_message": "Your administrator session has ended."}), 401

        con = _connect(db_file)
        employees = con.execute(
            "SELECT id, username, CHAT_LOGS FROM EMPLOYEES WHERE Parent_id = ? "
            "ORDER BY username COLLATE NOCASE",
            (admin["id"],),
        ).fetchall()
        settings = {
            r["Employee_id"]: r for r in con.execute(
                "SELECT Employee_id, check1, check2, check3 FROM SETTINGS WHERE Parent_id = ?",
                (admin["id"],),
            ).fetchall()
        }
        con.close()

        blocks = {}
        for row in block_rows(db_file, admin["id"]):
            blocks.setdefault(row["Employee_id"], []).append(row)

        members = []
        for emp in employees:
            s = settings.get(emp["id"])
            checks_on = sum(int(s[k]) for k in ("check1", "check2", "check3")) if s else 3
            answered = count_answered(emp["CHAT_LOGS"])
            emp_blocks = blocks.get(emp["id"], [])
            blocked = len(emp_blocks)
            sent = answered + blocked
            members.append({
                "username": emp["username"],
                "sent": sent,
                "answered": answered,
                "blocked": blocked,
                "block_rate": pct(blocked, sent),
                "checks_on": checks_on,
                "reasons": ranked(tally(b["reason"] for b in emp_blocks), blocked),
                "stages": ranked(tally(b["stage"] for b in emp_blocks), blocked),
            })

        total_sent = sum(m["sent"] for m in members)
        total_blocked = sum(m["blocked"] for m in members)
        return jsonify({
            "error": False,
            "admin": admin["username"],
            "stats": {
                "members": len(members),
                "sent": total_sent,
                "blocked": total_blocked,
                "block_rate": pct(total_blocked, total_sent),
            },
            "members": members,
        })
