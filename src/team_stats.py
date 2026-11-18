"""Team statistics for the administrator dashboard.

Gives the page a per-member screening breakdown, daily trends and a
metadata-only activity timeline. Imported network activity is in Shadow AI.

Blocks, successful completions and approved overrides are counted separately.
An approval is an audit event, not a refusal or a guarantee of completion.
"""

from collections import Counter

from flask import Blueprint

import block_log
from auth import admin_from_token, _connect
from config import DB_FILE, DEFAULT_MODEL, ROUTES
from policy import ACTION_FIELDS, rule_actions

team_stats_api = Blueprint("team_stats_api", __name__)

OVERRIDE_STAGE = "override"
DAYS = 30


def pct(part, whole):
    return round(part * 100 / whole) if whole else 0


def tally(values):
    return Counter(v for v in values if v)


def ranked(counter, total, limit=6):
    """Top items as {label, count, percent}, largest first."""
    items = [
        {"label": label, "count": count, "percent": pct(count, total)}
        for label, count in counter.most_common(limit)
    ]
    return items


def member_stats(db_file, parent_id, employee_id, username, settings,
                 answered, regenerated, blocks, created_at):
    """Everything the page charts for one member."""
    stopped = [b for b in blocks if b["stage"] != OVERRIDE_STAGE]
    blocked = len(stopped)
    overrides = len(blocks) - blocked
    # Count completions saved to history, not all provider call attempts.
    sent = answered + regenerated
    attempts = sent + blocked
    checks_on = sum(action != "allow" for action in rule_actions(settings or {}).values())

    return {
        "id": employee_id,
        "username": username,
        "member_since": created_at,
        "sent": sent,
        "answered": answered,
        "regenerated": regenerated,
        "blocked": blocked,
        "attempts": attempts,
        "overrides": overrides,
        "block_rate": pct(blocked, attempts),
        "checks_on": checks_on,
        "checks_off": len(ACTION_FIELDS) - checks_on,
        "model": (settings["MODEL_NAME"] if settings else None) or DEFAULT_MODEL,
        "has_key": bool(settings and settings["API_KEY"]),
        "reasons": ranked(tally(b["reason"] for b in stopped), blocked),
        "stages": ranked(tally(b["stage"] for b in stopped), blocked),
        "trend": block_log.daily_counts(db_file, parent_id, employee_id, DAYS),
        "timeline": block_log.timeline(db_file, parent_id, employee_id,
                                       limit=60),
    }


def build_stats(db_file, parent_id):
    con = _connect(db_file)

    employees = con.execute(
        "SELECT id, username, created_at FROM EMPLOYEES WHERE Parent_id = ? "
        "ORDER BY username",
        (parent_id,),
    ).fetchall()

    settings = {
        r["Employee_id"]: r
        for r in con.execute(
            "SELECT * FROM SETTINGS WHERE Parent_id = ?", (parent_id,)
        ).fetchall()
    }
    answered_map = {
        r["Employee_id"]: r["answered"]
        for r in con.execute(
            "SELECT Employee_id, answered FROM EMPLOYEE_STATS WHERE Parent_id = ?",
            (parent_id,),
        ).fetchall()
    }
    con.close()

    regenerated_map = block_log.regeneration_counts(db_file, parent_id)
    blocks_by_member = {}
    for row in block_log.block_rows(db_file, parent_id):
        blocks_by_member.setdefault(row["Employee_id"], []).append(row)

    members = [
        member_stats(
            db_file, parent_id, emp["id"], emp["username"],
            settings.get(emp["id"]),
            answered_map.get(emp["id"], 0),
            regenerated_map.get(emp["id"], 0),
            blocks_by_member.get(emp["id"], []),
            emp["created_at"],
        )
        for emp in employees
    ]

    total_sent = sum(m["sent"] for m in members)
    total_blocked = sum(m["blocked"] for m in members)
    total_overrides = sum(m["overrides"] for m in members)
    total_attempts = total_sent + total_blocked

    all_stages = Counter()
    all_reasons = Counter()
    for member in members:
        for item in member["stages"]:
            all_stages[item["label"]] += item["count"]
        for item in member["reasons"]:
            all_reasons[item["label"]] += item["count"]

    trend = block_log.daily_counts(db_file, parent_id, None, DAYS)

    return {
        "members": members,
        "stats": {
            "members": len(members),
            "sent": total_sent,
            "blocked": total_blocked,
            "overrides": total_overrides,
            "attempts": total_attempts,
            "regenerated": sum(m["regenerated"] for m in members),
            "block_rate": pct(total_blocked, total_attempts),
        },
        "stages": ranked(all_stages, total_blocked),
        "reasons": ranked(all_reasons, total_blocked),
        "trend": trend,
        "timeline": block_log.timeline(db_file, parent_id, None, limit=120),
        "days": DAYS,
    }


@team_stats_api.post(ROUTES["TEAM"])
def team():
    """Full statistics for the signed-in administrator's workspace."""
    from web import get_json_dict, to_int

    data = get_json_dict() or {}
    pid = to_int(data.get("Parent_id"))
    if "Parent_id" in data and pid is None:
        return {"error": True, "error_message": "'Parent_id' must be a positive integer."}, 400
    admin = admin_from_token(DB_FILE, data.get("token"), parent_id=pid, page=True)
    if admin is None:
        return {"error": True, "error_message": "Your session has ended. Sign in again."}, 401

    payload = build_stats(DB_FILE, int(admin["id"]))
    payload["error"] = False
    payload["admin"] = admin["username"]
    payload["error_message"] = "NULL"
    return payload


def register(app):
    app.register_blueprint(team_stats_api)
