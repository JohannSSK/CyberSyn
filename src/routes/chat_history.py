"""Chat history routes.

Chat history is a member's own content. These routes deliberately refuse an
administrator's token: an administrator sets policy, but reading what
someone wrote to an AI is a different power, and not one this app grants.
"""

from flask import Blueprint

import chat_store
from auth import require_member
from block_log import record_activity
from config import DB_FILE, ROUTES
from errors import ApiError
from web import fail, get_json_dict, ok

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
    try:
        return int(data.get("chat_id"))
    except (TypeError, ValueError):
        return None


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
    text = str(data.get("text") or "").strip()
    if not message_id:
        return fail("message_id is required.", 400)
    if not text:
        return fail("The message cannot be empty.", 400)

    messages = chat_store.edit_message(
        DB_FILE, ids[0], ids[1], chat_id, message_id, text
    )
    if messages is None:
        return fail("That message was not found.", 404)
    record_activity(DB_FILE, ids[0], ids[1], "message_edited", text[:80])
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
