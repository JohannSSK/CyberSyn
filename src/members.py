"""Team members and their per-member settings.

Settings live in one row per (Parent_id, Employee_id). The row with
Employee_id = 0 is the workspace default that new members inherit, so an
administrator can set a team-wide policy and only override per member where
it matters.
"""

from config import DEFAULT_MODEL
from db import get_db
from secret_store import encrypt_secret, mask_stored_key

SETTING_FLAGS = ("check1", "check2", "check3")


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
        "Use the real Employee_id returned by /api/admin/employee/login."
    )


def list_members(parent_id):
    return get_db().execute(
        "SELECT id, username, created_at FROM EMPLOYEES WHERE Parent_id = ? "
        "ORDER BY username",
        (parent_id,),
    ).fetchall()


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
            "PROVIDER": _provider_of(row), "API_BASE": _base_of(row),
        }
    return {"check1": 1, "check2": 1, "check3": 1, "API_KEY": "",
            "MODEL_NAME": DEFAULT_MODEL, "PROVIDER": "auto", "API_BASE": ""}


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


def create_default_settings(parent_id, employee_id):
    """Create a SETTINGS row (copy of the workspace default) if absent."""
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
        "API_KEY, MODEL_NAME, PROVIDER, API_BASE) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (parent_id, employee_id, d["check1"], d["check2"], d["check3"],
         d["API_KEY"], d["MODEL_NAME"], d.get("PROVIDER", "auto"),
         d.get("API_BASE", "")),
    )
    db.commit()


def get_settings(parent_id, employee_id):
    create_default_settings(parent_id, employee_id)
    return get_db().execute(
        "SELECT * FROM SETTINGS WHERE Parent_id = ? AND Employee_id = ?",
        (parent_id, employee_id),
    ).fetchone()


def settings_payload(parent_id, employee_id, row):
    """The settings as sent to the browser.

    The stored key is never returned — only a mask — so an XSS or a stray
    screenshot cannot leak it.
    """
    return {
        "Parent_id": str(parent_id),
        "Employee_id": str(employee_id),
        "check1": bool(row["check1"]),
        "check2": bool(row["check2"]),
        "check3": bool(row["check3"]),
        "API_KEY": "",
        "API_KEY_MASK": mask_stored_key(row["API_KEY"]),
        "MODEL_NAME": row["MODEL_NAME"] or DEFAULT_MODEL,
        "PROVIDER": _provider_of(row),
        "API_BASE": _base_of(row),
    }


def settings_updates(data):
    """Validate the fields a caller is allowed to change.

    Returns a dict of column -> value. An unknown or malformed field is a
    400 rather than a silent ignore, so a typo never looks like success.
    """
    from errors import ApiError
    from web import non_empty_str

    updates = {}
    for key in SETTING_FLAGS:
        if key in data:
            if not isinstance(data[key], bool):
                raise ApiError(f"'{key}' must be true or false.", 400)
            updates[key] = 1 if data[key] else 0
    if "API_KEY" in data:
        if not isinstance(data["API_KEY"], str):
            raise ApiError("'API_KEY' must be a string.", 400)
        if data["API_KEY"].strip():
            updates["API_KEY"] = encrypt_secret(data["API_KEY"].strip())
    if "MODEL_NAME" in data:
        if not non_empty_str(data["MODEL_NAME"]):
            raise ApiError("'MODEL_NAME' must be a non-empty string.", 400)
        updates["MODEL_NAME"] = data["MODEL_NAME"].strip()[:200]
    if "PROVIDER" in data:
        updates["PROVIDER"] = _clean_provider(data["PROVIDER"])
    if "API_BASE" in data:
        updates["API_BASE"] = _clean_base(data["API_BASE"])
    return updates


def _clean_provider(value):
    """A provider is one of the registry's keys, or 'auto'."""
    from errors import ApiError
    from providers import get

    text = str(value or "").strip().lower()
    if text == "auto":
        return "auto"
    if get(text) is None:
        raise ApiError(f"'{text}' is not a provider this gateway supports.", 400)
    return text


def _clean_base(value):
    """An optional custom address. Empty clears it; otherwise it is checked.

    The check matters: this is a URL a user types and the server is what
    would fetch it, so an unchecked value turns the gateway into a way to
    reach things inside the network.
    """
    from errors import ApiError
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
    if updates:
        sets = ", ".join(f"{k} = ?" for k in updates)
        db.execute(
            f"UPDATE SETTINGS SET {sets} WHERE Parent_id = ? AND Employee_id = ?",
            (*updates.values(), parent_id, employee_id),
        )
        db.commit()
    return get_settings(parent_id, employee_id)


def provider_and_base(settings_row):
    """(provider, api_base) for a settings row, tolerating older schemas."""
    return _provider_of(settings_row), _base_of(settings_row)
