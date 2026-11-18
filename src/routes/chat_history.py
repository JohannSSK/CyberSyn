"""Chat history routes.

Chat history is a member's own content. These routes deliberately refuse an
administrator's token: an administrator sets policy, but reading what
someone wrote to an AI is a different power, and not one this app grants.
"""

from flask import Blueprint

import chat_store
from auth import require_member
from block_log import record_activity
from config import DB_FILE, DEFAULT_MODEL, MAX_PROMPT_CHARS, ROUTES
from db import get_db
from errors import ApiError
from members import get_settings, provider_and_base
from policy import redaction_only, rule_actions
from scanning import apply_redactions, screen
from shadow_ai import unapproved_destination
from web import activity_detail, fail, get_json_dict, ok, to_int

chat_history = Blueprint("chat_history", __name__)


def _member(data):
    """Authorise and return (parent_id, employee_id)."""
    ids = require_member(DB_FILE, data)
    if ids[0] is None:
        raise ApiError("Your session has ended. Sign in again.", 401)
    return ids[0], ids[1]


def _ids(data):
    ids = require_member(DB_FILE, data)
    if ids[0] is None:
        return None
    return ids[0], ids[1]


def _chat_id(data):
    return to_int(data.get("chat_id"))


@chat_history.post(ROUTES["CHATS"])
def chats_list():
    data = get_json_dict() or {}
    ids = _ids(data)
    if ids is None:
        return fail("Your session has ended. Sign in again.", 401)
    return ok(chats=chat_store.list_chats(DB_FILE, ids[0], ids[1]))


@chat_history.post(ROUTES["CHATS_OPEN"])
def chats_open():
    data = get_json_dict() or {}
    ids = _ids(data)
    chat_id = _chat_id(data)
    if ids is None:
        return fail("Your session has ended. Sign in again.", 401)
    if chat_id is None:
        return fail("chat_id is required.", 400)
    chat = chat_store.get_chat(DB_FILE, ids[0], ids[1], chat_id)
    if chat is None:
        return fail("That chat was not found.", 404)
    return ok(chat=chat)


@chat_history.post(ROUTES["CHATS_DELETE"])
def chats_delete():
    data = get_json_dict() or {}
    ids = _ids(data)
    chat_id = _chat_id(data)
    if ids is None:
        return fail("Your session has ended. Sign in again.", 401)
    if chat_id is None:
        return fail("chat_id is required.", 400)
    if not chat_store.delete_chat(DB_FILE, ids[0], ids[1], chat_id):
        return fail("That chat was not found.", 404)
    record_activity(DB_FILE, ids[0], ids[1], "chat_deleted", f"chat {chat_id}")
    return ok(deleted=chat_id)


@chat_history.post(ROUTES["CHATS_RENAME"])
def chats_rename():
    data = get_json_dict() or {}
    ids = _ids(data)
    chat_id = _chat_id(data)
    if ids is None:
        return fail("Your session has ended. Sign in again.", 401)
    if chat_id is None:
        return fail("chat_id is required.", 400)
    title = " ".join(str(data.get("title") or "").split())[:80]
    if not title:
        return fail("Title cannot be empty.", 400)
    if not chat_store.rename_chat(DB_FILE, ids[0], ids[1], chat_id, title):
        return fail("That chat was not found.", 404)
    return ok(chat_id=chat_id, title=title)


@chat_history.post(ROUTES["CHATS_SEARCH"])
def chats_search():
    """Search this member's own messages."""
    data = get_json_dict() or {}
    ids = _ids(data)
    if ids is None:
        return fail("Your session has ended. Sign in again.", 401)
    query = str(data.get("query") or "").strip()
    if not query:
        return ok(results=[])
    results = chat_store.search(DB_FILE, ids[0], ids[1], query)
    return ok(results=results)


@chat_history.post(ROUTES["MESSAGE_EDIT"])
def message_edit():
    data = get_json_dict() or {}
    ids = _ids(data)
    chat_id = _chat_id(data)
    if ids is None:
        return fail("Your session has ended. Sign in again.", 401)
    if chat_id is None:
        return fail("chat_id is required.", 400)
    message_id = data.get("message_id")
    text = data.get("text")
    if not isinstance(text, str) or len(text) > MAX_PROMPT_CHARS:
        return fail(f"Message must be text of at most {MAX_PROMPT_CHARS} characters.", 400)
    text = text.strip()
    if not message_id:
        return fail("message_id is required.", 400)
    if not text:
        return fail("The message cannot be empty.", 400)

    # A local edit is not a send. Still, never introduce a raw value that
    # this seat's redaction rules already require us to keep out of history.
    saved = get_settings(*ids)
    rules = redaction_only(saved)
    outcome = screen(text, rules) if "redact" in rules.values() else None
    redaction = apply_redactions(text, (outcome or {}).get("redact_matches"))
    messages = chat_store.edit_message(DB_FILE, *ids, chat_id, message_id, text, redaction=redaction)
    del redaction
    if messages is None:
        return fail("That message was not found.", 404)
    entry = next(message for message in messages if message.get("id") == message_id)
    # An unscreened edit must not become an audit preview for a later
    # block, warning or override. Preserve opt-in previews of ordinary edits
    # only when no screen or destination policy applies.
    preview = not entry.get("metadata_only") and all(action == "allow" for action in rule_actions(saved).values())
    if preview:
        provider, base = provider_and_base(saved)
        preview = unapproved_destination(get_db(), ids[0], provider, base, saved["MODEL_NAME"] or DEFAULT_MODEL) is None
    record_activity(DB_FILE, *ids, "message_edited", activity_detail(chat_id, entry["prompt"], preview=preview))
    return ok(messages=messages)


@chat_history.post(ROUTES["MESSAGE_DELETE"])
def message_delete():
    data = get_json_dict() or {}
    ids = _ids(data)
    chat_id = _chat_id(data)
    if ids is None:
        return fail("Your session has ended. Sign in again.", 401)
    if chat_id is None:
        return fail("chat_id is required.", 400)
    message_id = data.get("message_id")
    if not message_id:
        return fail("message_id is required.", 400)

    messages = chat_store.delete_message(DB_FILE, ids[0], ids[1], chat_id, message_id)
    if messages is None:
        return fail("That message was not found.", 404)
    record_activity(DB_FILE, ids[0], ids[1], "message_deleted")
    return ok(messages=messages)
