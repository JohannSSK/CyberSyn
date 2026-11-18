"""Team members and their per-member settings.

Settings live in one row per (Parent_id, Employee_id). The row with
Employee_id = 0 is the workspace default that new members inherit, so an
administrator can set a team-wide policy and only override per member where
it matters.
"""

from config import DEFAULT_MODEL, ROUTES
from db import get_db
from errors import ApiError
from policy import ACTION_FIELDS, ACTIONS, DEFAULT_FLAGS, legacy_action, rule_actions
from secret_store import encrypt_secret, mask_stored_key

SETTING_FLAGS = tuple(ACTION_FIELDS)
POLICY_FIELDS = (*SETTING_FLAGS, *ACTION_FIELDS.values(), "restore_redactions")
CONNECTION_FIELDS = ("API_KEY", "PROVIDER", "API_BASE", "MODEL_NAME")
CONTEXT_FIELDS = ("CONTEXT_MESSAGES",)
# How much of the conversation may travel with the next prompt. Zero keeps
# the original behaviour: one message, this one only.
DEFAULT_CONTEXT_MESSAGES = 0
MAX_CONTEXT_MESSAGES = 20


def employee_row(parent_id, employee_id):
    if employee_id == 0:
        return None
    return get_db().execute(
        "SELECT * FROM EMPLOYEES WHERE id = ? AND Parent_id = ?",
        (employee_id, parent_id),
    ).fetchone()


def not_found_employee_message(parent_id, employee_id):
    return (
        f"Employee_id {employee_id} not found under Parent_id {parent_id}. "
        f"Use the real Employee_id returned by {ROUTES['EMPLOYEE_LOGIN']}."
    )


def list_members(parent_id):
    return get_db().execute(
        "SELECT id, username, created_at FROM EMPLOYEES WHERE Parent_id = ? "
        "ORDER BY username",
        (parent_id,),
    ).fetchall()


def default_settings_values(parent_id=None):
    row = None if parent_id is None else get_db().execute(
        "SELECT * FROM SETTINGS WHERE Parent_id = ? AND Employee_id = 0",
        (parent_id,),
    ).fetchone()
    policy = _policy_values(row or DEFAULT_FLAGS)
    return {**policy, "API_KEY": (row["API_KEY"] or "") if row else "",
            "MODEL_NAME": (row["MODEL_NAME"] or DEFAULT_MODEL) if row else DEFAULT_MODEL,
            "PROVIDER": _provider_of(row) if row else "auto", "API_BASE": _base_of(row) if row else "",
            "CONTEXT_MESSAGES": _context_of(row) if row else DEFAULT_CONTEXT_MESSAGES}


def _policy_values(row):
    actions = rule_actions(row)
    return {**{flag: action != "allow" for flag, action in actions.items()},
            **{field: actions[flag] for flag, field in ACTION_FIELDS.items()},
            "restore_redactions": bool(_value(row, "restore_redactions", 0))}


def _value(row, name, default=""):
    """Read a column that older databases may not have yet."""
    try:
        value = row[name]
    except (IndexError, KeyError):
        return default
    return default if value is None else value


def _provider_of(row):
    return _value(row, "PROVIDER", "auto") or "auto"


def _base_of(row):
    return _value(row, "API_BASE", "") or ""


def _context_of(row):
    """Previous messages that may travel with the next prompt, clamped."""
    try:
        value = int(_value(row, "CONTEXT_MESSAGES", DEFAULT_CONTEXT_MESSAGES))
    except (TypeError, ValueError):
        return DEFAULT_CONTEXT_MESSAGES
    return max(0, min(MAX_CONTEXT_MESSAGES, value))


def context_messages(row):
    """The saved context size for a settings row, tolerating older schemas."""
    return _context_of(row)


def create_default_settings(parent_id, employee_id, *, inherit=False, commit=True):
    """Snapshot the template at enrolment only. Repair missing rows with app defaults."""
    db = get_db()
    exists = db.execute(
        "SELECT 1 FROM SETTINGS WHERE Parent_id = ? AND Employee_id = ?",
        (parent_id, employee_id),
    ).fetchone()
    if exists:
        return
    d = default_settings_values(parent_id if inherit else None)
    columns = (*POLICY_FIELDS, *CONTEXT_FIELDS, *CONNECTION_FIELDS)
    placeholders = ", ".join("?" for _ in columns)
    db.execute(
        f"INSERT OR IGNORE INTO SETTINGS (Parent_id, Employee_id, {', '.join(columns)}) "
        f"SELECT ?, ?, {placeholders} WHERE "
        "(? = 0 AND EXISTS (SELECT 1 FROM ADMINS WHERE id=?)) OR "
        "EXISTS (SELECT 1 FROM EMPLOYEES WHERE id=? AND Parent_id=?)",
        (parent_id, employee_id, *(d[column] for column in columns),
         employee_id, parent_id, employee_id, parent_id),
    )
    if commit:
        db.commit()


def get_settings(parent_id, employee_id):
    create_default_settings(parent_id, employee_id)
    row = get_db().execute(
        "SELECT * FROM SETTINGS WHERE Parent_id = ? AND Employee_id = ?",
        (parent_id, employee_id),
    ).fetchone()
    if row is None:
        raise ApiError("That account no longer exists.", 404)
    return row


def settings_payload(parent_id, employee_id, row):
    """The settings as sent to the browser.

    The stored key is never returned — only a mask — so an XSS or a stray
    screenshot cannot leak it.
    """
    return {
        "Parent_id": str(parent_id),
        "Employee_id": str(employee_id),
        **_policy_values(row),
        "API_KEY": "",
        "API_KEY_MASK": mask_stored_key(row["API_KEY"]),
        "MODEL_NAME": row["MODEL_NAME"] or DEFAULT_MODEL,
        "PROVIDER": _provider_of(row),
        "API_BASE": _base_of(row),
        "CONTEXT_MESSAGES": _context_of(row),
    }


def settings_updates(data):
    """Validate the fields a caller is allowed to change.

    Return only approved column names and values. Invalid settings raise a 400.
    """
    from web import non_empty_str

    updates = {}
    for flag, field in ACTION_FIELDS.items():
        if flag in data and not isinstance(data[flag], bool):
            raise ApiError(f"'{flag}' must be true or false.", 400)
        if field in data:
            action = data[field]
            if action not in ACTIONS:
                raise ApiError(f"'{field}' must be allow, warn, redact or block.", 400)
            if flag == "check3" and action == "redact":
                raise ApiError("Prompt injection does not support redaction. Choose allow, warn or block.", 400)
            updates[field] = action
            updates[flag] = int(action != "allow")
        elif flag in data:
            updates[flag] = int(data[flag])
            updates[field] = legacy_action(data[flag])
    if "restore_redactions" in data:
        if not isinstance(data["restore_redactions"], bool):
            raise ApiError("'restore_redactions' must be true or false.", 400)
        updates["restore_redactions"] = int(data["restore_redactions"])
    if "CONTEXT_MESSAGES" in data:
        updates["CONTEXT_MESSAGES"] = _clean_context(data["CONTEXT_MESSAGES"])
    if "API_KEY" in data:
        if not isinstance(data["API_KEY"], str):
            raise ApiError("'API_KEY' must be a string.", 400)
        if data["API_KEY"].strip():
            updates["API_KEY"] = encrypt_secret(data["API_KEY"].strip())
    if "CLEAR_API_KEY" in data:
        if not isinstance(data["CLEAR_API_KEY"], bool):
            raise ApiError("'CLEAR_API_KEY' must be true or false.", 400)
        if data["CLEAR_API_KEY"]:
            updates["API_KEY"] = ""
    if "MODEL_NAME" in data:
        if not non_empty_str(data["MODEL_NAME"]):
            raise ApiError("'MODEL_NAME' must be a non-empty string.", 400)
        updates["MODEL_NAME"] = data["MODEL_NAME"].strip()[:200]
    if "PROVIDER" in data:
        updates["PROVIDER"] = _clean_provider(data["PROVIDER"])
    if "API_BASE" in data:
        updates["API_BASE"] = _clean_base(data["API_BASE"])
    return updates


def _clean_context(value):
    """A whole number of earlier messages, between the two published bounds."""
    problem = f"'CONTEXT_MESSAGES' must be a whole number between 0 and {MAX_CONTEXT_MESSAGES}."
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        raise ApiError(problem, 400)
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ApiError(problem, 400) from None
    if number < 0 or number > MAX_CONTEXT_MESSAGES:
        raise ApiError(problem, 400)
    return number


def _clean_provider(value):
    """A provider is one of the registry's keys, or 'auto'."""
    from providers import get

    text = str(value or "").strip().lower()
    if text == "auto":
        return "auto"
    if get(text) is None:
        raise ApiError("Select a provider supported by this gateway.", 400)
    return text


def _clean_base(value):
    """An optional custom address. Empty clears it; otherwise it is checked.

    The check matters: this is a URL a user types and the server is what
    would fetch it, so an unchecked value turns the gateway into a way to
    reach things inside the network.
    """
    from providers import ProviderError, validate_base_url

    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return validate_base_url(text)
    except ProviderError as exc:
        raise ApiError(str(exc), 400)


def save_settings(parent_id, employee_id, updates):
    db = get_db()
    create_default_settings(parent_id, employee_id, commit=False)
    if updates:
        sets = ", ".join(f"{k} = ?" for k in updates)
        db.execute(
            f"UPDATE SETTINGS SET {sets} WHERE Parent_id = ? AND Employee_id = ?",
            (*updates.values(), parent_id, employee_id),
        )


def provider_and_base(settings_row):
    """(provider, api_base) for a settings row, tolerating older schemas."""
    return _provider_of(settings_row), _base_of(settings_row)
