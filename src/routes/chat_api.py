"""Both initial sends and regenerations go through the same outbound gate."""

from flask import Blueprint

from ai_client import complete
from auth import admin_from_token, require_member
from block_log import record_activity, record_block
from chat_store import bump_answered, get_chat, replace_answer, save_exchange
from config import DB_FILE, DEFAULT_MODEL, MAX_PROMPT_CHARS, ROUTES
from db import get_db
from errors import ApiError, ChatError
from members import employee_row, get_settings, not_found_employee_message, provider_and_base
from policy import action_settings, redaction_only
from providers import get as get_provider
from redaction import TAGS, TAG_ALIASES, restore, retained_redactions
from scanning import apply_redactions, build_block_info, screen
from secret_store import decrypt_secret
from shadow_ai import resolved_provider, unapproved_destination
from web import activity_detail, chat_response, get_json_dict, non_empty_str, to_int

chat_api = Blueprint("chat_api", __name__)
AUDIT_CAUSES = TAGS | TAG_ALIASES.keys() | {
    "PROMPT_INJECTION", "legal contract or NDA", "internal company financial data",
    "confidential HR, payroll, or customer records", "leaked internal company document or confidential record",
    "UNAPPROVED_AI_TOOL",
}


def _authorise_override(data, parent_id):
    admin = admin_from_token(DB_FILE, data.get("admin_token"), parent_id=parent_id, consume=True)
    if admin is None:
        raise ChatError("Overriding a block needs a valid administrator session. Ask an administrator to approve this message.", 401)
    return admin


def _audit_detail(info, prompt):
    cause = info["main_cause"] if info["main_cause"] in AUDIT_CAUSES else "unknown"
    line = info.get("line")
    return cause, f"{info['stage']} · {cause} (line {line if type(line) is int else '-'}, {len(prompt)} chars)"


def _blocked(pid, eid, info, prompt, message=None):
    cause, detail = _audit_detail(info, prompt)
    record_block(DB_FILE, pid, eid, info["stage"], cause)
    record_activity(DB_FILE, pid, eid, "blocked", detail)
    message = message or (f"Blocked by {info['stage']} ({info['main_cause']}): "
                          f"'{info['snippet']}' on line {info['line']}")
    return chat_response(False, True, message=message, block_info=info, warned=False, redacted=False, action="block")


def _tool_block(pid, eid, tool, prompt):
    info = build_block_info("policy", {"main_cause": "UNAPPROVED_AI_TOOL"})
    info["tool_name"] = tool["name"]
    return _blocked(pid, eid, info, prompt, f"{tool['name']} is unapproved in this workspace.")


def _bool(data, field):
    value = data.get(field, False)
    if not isinstance(value, bool):
        raise ChatError(f"'{field}' must be true or false.", 400)
    return value


def _exchange(data, pid, eid, prompt, chat_id, entry):
    confirm_warn = _bool(data, "confirm_warn")
    bypass = _bool(data, "bypass")
    admin = _authorise_override(data, pid) if bypass else None
    saved = get_settings(pid, eid)
    model = (saved["MODEL_NAME"] or DEFAULT_MODEL).strip()
    provider, base = provider_and_base(saved)
    connection = get_provider(resolved_provider(provider, model))
    if connection and not base:
        base = connection.default_base or base

    def denied_tool():
        return None if bypass else unapproved_destination(get_db(), pid, provider, base, model)

    tool = denied_tool()
    if tool:
        return _tool_block(pid, eid, tool, prompt)
    api_key = decrypt_secret(saved["API_KEY"]).strip()
    if not api_key and (not connection or connection.needs_key):
        raise ChatError("No API_KEY provided.", 400)

    if bypass:
        actions = redaction_only(saved)
        outcome = screen(prompt, actions) if "redact" in actions.values() else None
    else:
        outcome = screen(prompt, action_settings(saved))
    outcome = outcome or {}
    if outcome.get("blocked") or outcome.get("stage"):  # legacy block_info
        return _blocked(pid, eid, outcome, prompt)
    warning = outcome.get("warn_info")
    if warning and not confirm_warn:
        record_activity(DB_FILE, pid, eid, "warned", _audit_detail(warning, prompt)[1])
        return chat_response(False, message="Review the flagged details before sending this message.",
                             warned=True, redacted=False, action="warn", warn_info=warning)

    redaction = apply_redactions(prompt, outcome.get("redact_matches"))
    sent = redaction.prompt if redaction else prompt
    redaction_info = redaction.info if redaction else (retained_redactions(sent, entry) if entry else None)
    # Tool policy may have changed during screening. Recheck the destination
    # just before a send, without holding a DB lock across provider I/O.
    tool = denied_tool()
    if tool:
        return _tool_block(pid, eid, tool, prompt)
    if bypass:
        record_block(DB_FILE, pid, eid, "override", f"approved by {admin['username']}")
        record_activity(DB_FILE, pid, eid, "override", f"approved by {admin['username']} ({len(prompt)} chars)")
    if confirm_warn:
        detail = _audit_detail(warning, prompt)[1] if warning else "No warning under current policy"
        record_activity(DB_FILE, pid, eid, "warn_proceeded", detail)

    # Bracketed tokens are sent verbatim. No reverse map or original value
    # is given to the provider (not even an instruction containing one).
    answer = complete(api_key, model, sent, api_base=base, provider=provider)
    stored_answer = redaction.un_restored_reply(answer) if redaction else answer
    reply = stored_answer
    if redaction and saved["restore_redactions"]:
        reply = restore(stored_answer, redaction.mapping)
    restored = reply != stored_answer
    del redaction  # drop both raw-value maps before storing or logging anything
    private = bool(bypass or confirm_warn or redaction_info or (entry and entry.get("metadata_only")))

    if entry is None:
        created = chat_id is None
        chat_id, message = save_exchange(DB_FILE, pid, eid, chat_id, sent, stored_answer,
                                         redaction_info=redaction_info, metadata_only=private)
        if message is None:
            raise ChatError("That chat was not found for this team member.", 404)
        bump_answered(DB_FILE, pid, eid)
        if created:
            record_activity(DB_FILE, pid, eid, "chat_created")
        message_id = message["id"]
        extra = {}
        kind = "prompt"
    else:
        message_id = entry["id"]
        messages = replace_answer(DB_FILE, pid, eid, chat_id, message_id, stored_answer,
                                  expected_prompt=entry["prompt"], sent_prompt=sent,
                                  redaction_info=redaction_info, metadata_only=private)
        if messages is None:
            raise ChatError("That message was not found in this chat.", 404)
        extra = {"messages": messages}
        kind = "regenerated"
    record_activity(DB_FILE, pid, eid, kind, activity_detail(chat_id, sent, preview=not private))
    if redaction_info:
        record_activity(DB_FILE, pid, eid, "redacted",
                        f"redacted {redaction_info['count']} item(s): {', '.join(redaction_info['categories'])}")
        extra.update(redacted_prompt=sent, redaction_info=dict(redaction_info, restored=restored))
    return chat_response(False, reply=reply, action="redact" if redaction_info else "allow", warned=False,
                         redacted=bool(redaction_info), chat_id=chat_id, message_id=message_id, **extra)


def _handle(*, regenerate=False):
    data = get_json_dict()
    if data is None:
        return chat_response(True, message="Request body must be a JSON object.", status=400)
    try:
        pid, eid = to_int(data.get("Parent_id")), to_int(data.get("Employee_id"))
        if pid is None or eid is None:
            field = "Parent_id" if pid is None else "Employee_id"
            raise ChatError(f"'{field}' must be a positive integer.", 400)
        if require_member(DB_FILE, data)[0] is None:
            raise ChatError("Your session has ended. Sign in again to continue.", 401)
        if employee_row(pid, eid) is None:
            raise ChatError(not_found_employee_message(pid, eid), 404)

        chat_id = to_int(data.get("chat_id"))
        chat = entry = None
        if regenerate or data.get("chat_id") is not None:
            if chat_id is None:
                raise ChatError("'chat_id' must be a positive integer.", 400)
            chat = get_chat(DB_FILE, pid, eid, chat_id)
            if chat is None:
                raise ChatError("That chat was not found." if regenerate else "That chat was not found for this team member.", 404)
        if regenerate:
            entry = next((item for item in chat["messages"] if item.get("id") == data.get("message_id")), None)
            if entry is None:
                raise ChatError("That message was not found in this chat.", 404)
            if not non_empty_str(entry.get("prompt")):
                raise ChatError("Only a message you sent can be regenerated.", 400)
        # An optional draft lets a caller screen an edit without persisting it
        # first. Old callers still regenerate the saved (possibly edited) text.
        prompt = data.get("prompt", entry["prompt"] if entry else None)
        if not non_empty_str(prompt):
            raise ChatError("'prompt' must be a non-empty string.", 400)
        if len(prompt) > MAX_PROMPT_CHARS:
            raise ChatError(f"Prompt exceeds {MAX_PROMPT_CHARS} characters.", 400)
        try:
            prompt.encode("utf-8")
        except UnicodeError:
            raise ChatError("Prompt must be valid UTF-8 text.", 400) from None
        return _exchange(data, pid, eid, prompt, chat_id, entry)
    except ApiError as exc:
        return chat_response(True, message=exc.message, status=exc.status)


@chat_api.post(ROUTES["CHAT"])
def employee_chat():
    return _handle()


@chat_api.post(ROUTES["CHAT_REGENERATE"])
def regenerate():
    return _handle(regenerate=True)
