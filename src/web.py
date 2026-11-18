"""Request parsing and JSON response shapes.

Every route in the app answers with JSON, and several of the shapes are
fixed by the front end (which reads `error`, `error_message`, `reason`,
`reply_message`...). Defining them once here keeps those contracts in one
place instead of scattered across the route modules.
"""

from flask import jsonify, request

import config
from config import NULL
from errors import ApiError


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def get_json_dict():
    """Return the request body as a dict, or None if it is not one."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def require_body():
    """Return the body dict, or raise a 400 that fits the generic shape."""
    data = get_json_dict()
    if data is None:
        raise ApiError("Request body must be a JSON object.", 400)
    return data


def to_int(value):
    """Return a positive int from an int or digit string, otherwise None."""
    if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit() and len(value.strip()) <= 19:
        value = int(value.strip())
    return value if type(value) is int and 1 <= value < 2**63 else None


def non_empty_str(value):
    return isinstance(value, str) and value.strip() != ""


def password_field(data, name):
    value = data.get(name)
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise ApiError(f"'{name}' must contain 1 to 256 characters.", 400)
    return value  # whitespace is part of the credential


def clean_str(value, field, limit=None):
    """Validate a non-empty string field, raising a 400 if it is not one."""
    if not non_empty_str(value):
        raise ApiError(f"'{field}' must be a non-empty string.", 400)
    text = value.strip()
    if limit is not None and len(value) > limit:
        raise ApiError(f"'{field}' must be at most {limit} characters.", 400)
    return text


# --------------------------------------------------------------------------
# Response shapes
# --------------------------------------------------------------------------

def fail(message, status=400, **extra):
    """The default error shape: `error` plus `error_message`."""
    body = {"error": True, "error_message": message}
    body.update(extra)
    return jsonify(body), status


def fail_admin_login(reason, status):
    """/api/admin/login answers with `success` and `reason`, not `error`."""
    return jsonify({"success": False, "Parent_id": NULL, "reason": reason}), status


def fail_admin(message, status):
    """/api/admin adds `Parent_id` to the default shape."""
    return jsonify(
        {"error": True, "Parent_id": NULL, "error_message": message}
    ), status


def fail_employee_login(message, status):
    """/api/admin/employee/login adds Employee_id and CHAT_LOGS."""
    return jsonify(
        {"error": True, "Employee_id": NULL, "CHAT_LOGS": [],
         "error_message": message}
    ), status


def chat_response(error=False, blocked=False, reply=NULL, message=NULL,
                  block_info=NULL, status=200, **extra):
    """The chat route's response shape."""
    body = {
        "error": error,
        "blocked": blocked,
        "reply_message": reply,
        "error_message": message,
        "block_info": block_info,
    }
    body.update(extra)
    return jsonify(body), status


def ok(**body):
    """A success response in the default shape."""
    payload = {"error": False, "error_message": NULL}
    payload.update(body)
    return jsonify(payload)


def activity_detail(chat_id, text, preview=True):
    if preview and config.LOG_PROMPT_PREVIEW:
        return text[:80]
    return f"chat {chat_id} ({len(text)} chars)"
