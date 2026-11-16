"""Live model discovery.

Asks a provider which models the pasted key can reach, so the member picks
from a real list instead of guessing a name.

This route makes an outbound call using the caller's key, so it requires a
live session — otherwise it would be an open relay for anyone who finds the
port.
"""

import json
import urllib.request

from flask import Blueprint

from auth import admin_from_token, member_from_token
from config import DB_FILE
from members import get_settings
from secret_store import decrypt_secret
from web import get_json_dict

models_api = Blueprint("models_api", __name__)

# Model families that cannot hold a chat conversation.
SKIP = ("tts", "image", "embedding", "lyria", "veo", "imagen", "aqa",
        "robotics", "live", "audio", "computer-use", "transcribe", "realtime",
        "search", "instruct", "moderation", "dall", "whisper", "davinci",
        "babbage")

TIMEOUT = 15


def fetch_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.load(resp)


def openai_models(key):
    body = fetch_json(
        "https://api.openai.com/v1/models", {"Authorization": "Bearer " + key}
    )
    names = [m["id"] for m in body.get("data", [])]
    chat = [n for n in names if not any(s in n for s in SKIP)]
    return sorted(chat) or sorted(names)


def anthropic_models(key):
    body = fetch_json(
        "https://api.anthropic.com/v1/models?limit=100",
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    return sorted(m["id"] for m in body.get("data", []))


def gemini_models(key):
    body = fetch_json(
        "https://generativelanguage.googleapis.com/v1beta/models?key=" + key, {}
    )
    names = [
        m["name"].split("/")[-1]
        for m in body.get("models", [])
        if "generateContent" in (m.get("supportedGenerationMethods") or [])
    ]
    return ["gemini/" + n for n in sorted(names)
            if n.startswith("gemini") and not any(s in n for s in SKIP)]


def guess_provider(key):
    if key.startswith("sk-ant-"):
        return "anthropic"
    if key.startswith("AIza"):
        return "gemini"
    return "openai"


@models_api.post("/api/admin/employee/models")
def list_models():
    data = get_json_dict() or {}
    token = data.get("session_token")
    member = member_from_token(DB_FILE, token)
    admin = None if member else admin_from_token(DB_FILE, token)
    if member is None and admin is None:
        return {"models": [], "message": "Your session has ended. Sign in again."}, 401

    key = str(data.get("API_KEY") or "").strip()
    if not key:
        # No key pasted: use the one already saved for this member. The field
        # only ever holds a mask, so asking the caller to re-paste a saved key
        # made the list impossible to refresh after the first save.
        parent_id = member["Parent_id"] if member else admin["id"]
        employee_id = member["Employee_id"] if member else 0
        key = decrypt_secret(get_settings(parent_id, employee_id)["API_KEY"] or "").strip()
        if not key:
            return {"models": [], "message": "Paste an API key first."}, 400

    provider = str(data.get("provider") or guess_provider(key)).strip().lower()
    try:
        if provider == "anthropic":
            models = anthropic_models(key)
        elif provider == "gemini":
            models = gemini_models(key)
        else:
            models = openai_models(key)
    except Exception as exc:
        return {
            "models": [],
            "message": f"Could not reach {provider}: {type(exc).__name__}",
        }, 502

    if not models:
        return {"models": [], "message": "That key returned no usable models."}, 200
    return {"models": models, "message": None}


def register(app):
    app.register_blueprint(models_api)
