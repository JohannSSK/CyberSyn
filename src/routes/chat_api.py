"""The screened chat route — the heart of the product.

Order matters here: authorise, then screen, then send. A prompt that fails
any check never leaves the machine, and a failure inside a check is treated
the same as a block (fail closed).
"""

from flask import Blueprint

from ai_client import complete
from auth import admin_from_token, require_member
from block_log import record_activity, record_block
from chat_store import bump_answered, save_exchange
from config import CHECKS, DB_FILE, DEFAULT_MODEL
from errors import ApiError, ChatError
from web import chat_response, get_json_dict, non_empty_str, to_int
from members import employee_row, get_settings, not_found_employee_message
from scanning import screen
from secret_store import decrypt_secret

chat_api = Blueprint("chat_api", __name__)


def _flags(data, saved):
    """Per-request check toggles win over the member's saved settings."""
    flags = {}
    for key in ("check1", "check2", "check3"):
        if key in data:
            if not isinstance(data[key], bool):
                raise ChatError(f"'{key}' must be true or false.", 400)
            flags[key] = data[key]
        else:
            flags[key] = bool(saved[key])
    return flags


def _authorise_override(data, parent_id):
    """An override needs a live administrator session for this workspace.

    The browser collects the approval; this is what enforces it.
    """
    admin = admin_from_token(DB_FILE, data.get("admin_token"))
    if admin is None or int(admin["id"]) != parent_id:
        raise ChatError(
            "Overriding a block needs a valid administrator session. "
            "Ask an administrator to approve this message.",
            401,
        )


@chat_api.post("/api/admin/employee/chat")
def employee_chat():
    data = get_json_dict()
    if data is None:
        return chat_response(True, message="Request body must be a JSON object.",
                             status=400)
    try:
        parent_id = to_int(data.get("Parent_id"))
        employee_id = to_int(data.get("Employee_id"))
        if parent_id is None:
            raise ChatError("'Parent_id' must be a positive integer.", 400)
        if employee_id is None:
            raise ChatError("'Employee_id' must be a positive integer.", 400)

        # Authorised before the member lookup, so an outsider cannot use this
        # route to discover which member IDs exist.
        if require_member(DB_FILE, data)[0] is None:
            raise ChatError("Your session has ended. Sign in again to continue.", 401)

        bypass = data.get("bypass", False)
        if not isinstance(bypass, bool):
            raise ChatError("'bypass' must be true or false.", 400)
        if bypass:
            _authorise_override(data, parent_id)

        emp = employee_row(parent_id, employee_id)
        if emp is None:
            raise ChatError(not_found_employee_message(parent_id, employee_id), 404)

        prompt = data.get("prompt")
        if not non_empty_str(prompt):
            raise ChatError("'prompt' must be a non-empty string.", 400)

        from chat_store import get_chat

        chat_id = to_int(data.get("chat_id"))
        if data.get("chat_id") is not None:
            if chat_id is None or get_chat(DB_FILE, parent_id, employee_id, chat_id) is None:
                raise ChatError("That chat was not found for this team member.", 404)

        saved = get_settings(parent_id, employee_id)
        flags = _flags(data, saved)

        model = data.get("MODEL_NAME")
        if not non_empty_str(model):
            model = saved["MODEL_NAME"] or DEFAULT_MODEL
        model = model.strip()

        api_key = decrypt_secret(saved["API_KEY"]).strip()
        if not api_key:
            raise ChatError("No API_KEY provided.", 400)

        if bypass:
            # Kept in the audit trail, but the message was sent, so the
            # dashboard counts it as answered rather than blocked.
            record_block(DB_FILE, parent_id, employee_id, "override",
                         "administrator approved")
            record_activity(DB_FILE, parent_id, employee_id, "override",
                            f"approved: {prompt[:80]}")
        else:
            info = screen(prompt, flags)
            if info is not None:
                record_block(DB_FILE, parent_id, employee_id, info["stage"],
                             info["main_cause"])
                record_activity(DB_FILE, parent_id, employee_id, "blocked",
                                f"{info['main_cause']}: {prompt[:80]}")
                message = (
                    f"Blocked by {info['stage']} ({info['main_cause']}): "
                    f"'{info['snippet']}' on line {info['line']}"
                )
                return chat_response(False, True, message=message, block_info=info)

        answer = complete(api_key, model, prompt)

        created = chat_id is None
        chat_id, entry = save_exchange(DB_FILE, parent_id, employee_id, chat_id,
                                       prompt, answer)
        bump_answered(DB_FILE, parent_id, employee_id)
        if created:
            record_activity(DB_FILE, parent_id, employee_id, "chat_created")
        record_activity(DB_FILE, parent_id, employee_id, "prompt", prompt[:80])
        return chat_response(False, reply=answer, chat_id=chat_id,
                             message_id=entry["id"])

    except (ChatError, ApiError) as exc:
        return chat_response(True, message=exc.message, status=exc.status)


@chat_api.post("/api/admin/employee/chat/regenerate")
def regenerate():
    """Ask the model for a different answer to the last prompt.

    The prompt was screened when it was first sent; re-running it changes
    only the answer, so it goes straight to the provider.
    """
    from chat_store import get_chat, replace_answer

    data = get_json_dict()
    if data is None:
        return chat_response(True, message="Request body must be a JSON object.",
                             status=400)
    try:
        parent_id = to_int(data.get("Parent_id"))
        employee_id = to_int(data.get("Employee_id"))
        chat_id = to_int(data.get("chat_id"))
        message_id = data.get("message_id")
        if parent_id is None or employee_id is None or chat_id is None:
            raise ChatError("Parent_id, Employee_id and chat_id are required.", 400)
        if require_member(DB_FILE, data)[0] is None:
            raise ChatError("Your session has ended. Sign in again to continue.", 401)

        chat = get_chat(DB_FILE, parent_id, employee_id, chat_id)
        if chat is None:
            raise ChatError("That chat was not found.", 404)

        entry = next(
            (m for m in chat["messages"] if m.get("id") == message_id), None
        )
        if entry is None:
            raise ChatError("That message was not found in this chat.", 404)
        if not non_empty_str(entry.get("prompt")):
            raise ChatError("Only a message you sent can be regenerated.", 400)

        saved = get_settings(parent_id, employee_id)
        api_key = decrypt_secret(saved["API_KEY"]).strip()
        if not api_key:
            raise ChatError("No API_KEY provided.", 400)

        answer = complete(api_key, saved["MODEL_NAME"] or DEFAULT_MODEL,
                          entry["prompt"])
        messages = replace_answer(DB_FILE, parent_id, employee_id, chat_id,
                                  message_id, answer)
        record_activity(DB_FILE, parent_id, employee_id, "regenerated",
                        entry["prompt"][:80])
        return chat_response(False, reply=answer, messages=messages)

    except (ChatError, ApiError) as exc:
        return chat_response(True, message=exc.message, status=exc.status)
