"""OpenAI-compatible proxy endpoints for external & in-house AI apps.

Drop-in `/v1/chat/completions` and `/v1/models` routes let any OpenAI SDK,
IDE assistant, or in-house AI application point its base URL at CyberSyn and
inherit the workspace's Shadow AI destination checks, DLP/PII screening,
prompt-injection guardrails, redaction/restoration, and audit logging.
"""

import secrets
import time

from flask import Blueprint, jsonify, request

import ai_client
from auth import admin_from_token, member_from_token
from block_log import record_activity, record_block
from chat_store import bump_answered
from config import DB_FILE, DEFAULT_MODEL, MAX_PROMPT_CHARS
from db import get_db
from errors import ChatError
from members import get_settings, provider_and_base
from policy import action_settings, redaction_only
from providers import get as get_provider
from redaction import _substitute, restore
from scanning import apply_redactions, screen
from secret_store import decrypt_secret
from shadow_ai import resolved_provider, unapproved_destination
from web import get_json_dict

openai_proxy = Blueprint("openai_proxy", __name__)

_ALLOWED_ROLES = ("system", "developer", "user", "assistant", "tool")
_SCREENED_ROLES = ("system", "developer", "user")


def _openai_error(message, status, *, err_type="invalid_request_error", code=None, extra=None):
    body = {"error": {"message": message, "type": err_type, "code": code}}
    if extra:
        body["cybersyn"] = extra
    return jsonify(body), status


def _bearer_token():
    auth_header = (request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return (request.headers.get("X-CyberSyn-Token") or "").strip()


def _authenticate():
    token = _bearer_token()
    if not token:
        return None
    return member_from_token(DB_FILE, token)


def _extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return None


@openai_proxy.get("/v1/models")
def proxy_models():
    member = _authenticate()
    if member is None:
        return _openai_error("Invalid or missing CyberSyn seat token.", 401,
                             err_type="authentication_error", code="invalid_api_key")
    saved = get_settings(member["Parent_id"], member["Employee_id"])
    seat_model = (saved["MODEL_NAME"] or DEFAULT_MODEL).strip()
    return jsonify({
        "object": "list",
        "data": [{
            "id": seat_model,
            "object": "model",
            "created": int(time.time()),
            "owned_by": (saved["PROVIDER"] or "cybersyn"),
        }],
    })


@openai_proxy.post("/v1/chat/completions")
def proxy_chat_completions():
    member = _authenticate()
    if member is None:
        return _openai_error("Invalid or missing CyberSyn seat token.", 401,
                             err_type="authentication_error", code="invalid_api_key")
    pid, eid = member["Parent_id"], member["Employee_id"]

    data = get_json_dict()
    if data is None:
        return _openai_error("Request body must be a JSON object.", 400)
    if data.get("stream") is True:
        return _openai_error("Streaming is not supported on this CyberSyn proxy endpoint; set stream=false.", 400)

    raw_messages = data.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        return _openai_error("'messages' must be a non-empty list.", 400)

    normalized = []
    total_chars = 0
    for item in raw_messages:
        if not isinstance(item, dict):
            return _openai_error("Each message must be an object with 'role' and 'content'.", 400)
        role = item.get("role")
        if role not in _ALLOWED_ROLES:
            return _openai_error(f"Unsupported message role: {role!r}.", 400)
        text = _extract_text(item.get("content"))
        if text is None:
            return _openai_error("Each message must include string or text content.", 400)
        total_chars += len(text)
        if total_chars > MAX_PROMPT_CHARS:
            return _openai_error(f"Combined messages exceed {MAX_PROMPT_CHARS} characters.", 400)
        normalized.append({"role": role, "content": text})

    if not any(m["content"].strip() for m in normalized):
        return _openai_error("Messages contain no text.", 400)

    bypass_token = (request.headers.get("X-CyberSyn-Bypass-Token") or data.get("cybersyn_bypass_token") or "").strip()
    admin = None
    if bypass_token:
        admin = admin_from_token(DB_FILE, bypass_token, parent_id=pid, consume=True)
        if admin is None:
            return _openai_error("Invalid or expired administrator override token.", 401,
                                 err_type="authentication_error", code="invalid_override_token")
    bypass = admin is not None

    confirm_warn = (
        str(request.headers.get("X-CyberSyn-Confirm-Warn") or "").strip().lower() in ("1", "true", "yes")
        or bool(data.get("cybersyn_confirm_warn"))
    )

    saved = get_settings(pid, eid)
    seat_model = (saved["MODEL_NAME"] or DEFAULT_MODEL).strip()
    req_model = str(data.get("model") or "").strip()
    target_model = seat_model if req_model in ("", "default", "cybersyn") else req_model
    provider, base = provider_and_base(saved)
    connection = get_provider(resolved_provider(provider, target_model))
    if connection and not base:
        base = connection.default_base or base

    def denied_tool():
        if bypass:
            return None
        db = get_db()
        tool = unapproved_destination(db, pid, provider, base, target_model)
        if tool:
            return tool
        if req_model and req_model not in ("default", "cybersyn"):
            return unapproved_destination(db, pid, "auto", "", target_model)
        return None

    tool = denied_tool()
    if tool:
        record_block(DB_FILE, pid, eid, "policy", "UNAPPROVED_AI_TOOL")
        return _openai_error(
            f"{tool['name']} is unapproved in this workspace.", 403,
            err_type="cybersyn_policy_error", code="unapproved_ai_tool",
            extra={"blocked": True, "action": "block", "stage": "policy",
                   "main_cause": "UNAPPROVED_AI_TOOL", "tool_name": tool["name"]},
        )

    api_key = decrypt_secret(saved["API_KEY"]).strip()
    if not api_key and (not connection or connection.needs_key):
        return _openai_error("No API_KEY configured for this CyberSyn seat.", 400, code="missing_api_key")

    actions = redaction_only(saved) if bypass else action_settings(saved)
    active = any(action != "allow" for action in actions.values())
    screened_messages = []
    combined_mapping = {}
    combined_private = {}
    redaction_categories = set()
    redaction_total = 0

    for msg in normalized:
        content = msg["content"]
        if not active or msg["role"] not in _SCREENED_ROLES or not content.strip():
            screened_messages.append(msg)
            continue
        try:
            outcome = screen(content, actions) or {}
        except ChatError as exc:
            return _openai_error(exc.message, exc.status, code=exc.payload.get("error_code"))
        if outcome.get("blocked") or outcome.get("stage"):
            stage = outcome.get("stage") or "policy"
            cause = outcome.get("main_cause") or "policy"
            record_block(DB_FILE, pid, eid, stage, cause)
            return _openai_error(
                f"Blocked by CyberSyn ({stage}: {cause}).", 403,
                err_type="cybersyn_policy_error", code="policy_blocked",
                extra={"blocked": True, "action": "block", **outcome},
            )
        warning = outcome.get("warn_info")
        if warning and not confirm_warn:
            cause = warning.get("main_cause") or "policy"
            record_activity(DB_FILE, pid, eid, "warned", f"{warning.get('stage')}: {cause}")
            return _openai_error(
                "Message paused for review by CyberSyn policy.", 409,
                err_type="cybersyn_policy_warning", code="policy_warning",
                extra={"blocked": False, "warned": True, "action": "warn", "warn_info": warning},
            )
        redaction = apply_redactions(content, outcome.get("redact_matches"))
        if redaction:
            prompt_out = redaction.prompt
            token_remap = {}
            for tok, raw in list(redaction.mapping.items()):
                existing = combined_mapping.get(tok)
                if existing is not None and existing != raw:
                    tag = tok[1:].rsplit("_", 1)[0]
                    n = 1
                    while True:
                        candidate = f"[{tag}_{n}]"
                        if candidate not in combined_mapping and candidate not in redaction.mapping and candidate not in prompt_out:
                            break
                        n += 1
                    token_remap[tok] = candidate
                    combined_mapping[candidate] = raw
                    combined_private[raw] = candidate
                else:
                    combined_mapping[tok] = raw
                    combined_private[raw] = tok
            if token_remap:
                prompt_out = _substitute(prompt_out, token_remap)
            for raw, tok in redaction.private_values.items():
                combined_private.setdefault(raw, token_remap.get(tok, tok))
            redaction_categories.update(redaction.info.get("categories") or ())
            redaction_total += redaction.info.get("count", 0)
            screened_messages.append({"role": msg["role"], "content": prompt_out})
        else:
            screened_messages.append(msg)

    tool = denied_tool()
    if tool:
        record_block(DB_FILE, pid, eid, "policy", "UNAPPROVED_AI_TOOL")
        return _openai_error(
            f"{tool['name']} is unapproved in this workspace.", 403,
            err_type="cybersyn_policy_error", code="unapproved_ai_tool",
            extra={"blocked": True, "action": "block", "stage": "policy",
                   "main_cause": "UNAPPROVED_AI_TOOL", "tool_name": tool["name"]},
        )

    if bypass:
        approval = f"approved by {admin['username']} (proxy)"
        record_block(DB_FILE, pid, eid, "override", approval, activity_detail=approval)
    if confirm_warn:
        record_activity(DB_FILE, pid, eid, "warn_proceeded", "proxy confirm_warn")

    try:
        answer = ai_client.complete_messages(api_key, target_model, screened_messages,
                                             api_base=base, provider=provider)
    except ChatError as exc:
        return _openai_error(exc.message, exc.status, err_type="upstream_error",
                             code=exc.payload.get("error_code"))

    stored_answer = _substitute(answer, combined_private) if combined_private else answer
    reply = restore(stored_answer, combined_mapping) if (combined_mapping and saved["restore_redactions"]) else stored_answer
    restored = reply != stored_answer
    redaction_info = {
        "count": redaction_total,
        "categories": sorted(redaction_categories),
        "placeholders": sorted(combined_mapping),
        "restored": restored,
    } if redaction_total else None
    del combined_mapping, combined_private

    bump_answered(DB_FILE, pid, eid)
    record_activity(DB_FILE, pid, eid, "prompt", f"proxy ({total_chars} chars)")
    if redaction_info:
        cats = ", ".join(redaction_info["categories"])
        record_activity(DB_FILE, pid, eid, "redacted", f"proxy ({redaction_info['count']}: {cats})")

    return jsonify({
        "id": f"chatcmpl-cybersyn-{secrets.token_hex(12)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": target_model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": reply},
            "finish_reason": "stop",
        }],
        "cybersyn": {
            "action": "redact" if redaction_info else "allow",
            "redacted": bool(redaction_info),
            "restored": restored,
            "redaction_info": redaction_info,
        },
    })
