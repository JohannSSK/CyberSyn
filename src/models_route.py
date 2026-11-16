"""Live model discovery.

Asks a provider which models the pasted key can reach, so the member picks
from a real list instead of guessing a name.

This route makes an outbound call using the caller's key, so it requires a
live session — otherwise it would be an open relay for anyone who finds the
port.
"""

import json
import urllib.error
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

TIMEOUT = 20


class ProviderError(Exception):
    """A provider call failed, carrying enough detail to act on.

    The old code reported only the exception's class name, so a rejected key
    and a network outage both came back as "Could not reach openai: HTTPError"
    and there was nothing to fix from.
    """

    def __init__(self, provider, detail, status=None):
        super().__init__(detail)
        self.provider = provider
        self.detail = detail
        self.status = status


def fetch_json(url, headers, provider):
    """GET JSON, turning every transport or HTTP failure into ProviderError."""
    request = urllib.request.Request(
        url, headers=dict(headers, **{"User-Agent": "CyberSyn/1.0"})
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # The provider's own explanation is the useful part: "Incorrect API
        # key provided", "You exceeded your current quota", and so on.
        detail = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:400]
        except Exception:  # noqa: BLE001 - the body is a nicety, not a need
            body = ""
        if body:
            try:
                parsed = json.loads(body)
                detail = (parsed.get("error") or {}).get("message", "") or \
                    parsed.get("message", "")
            except ValueError:
                detail = body.strip().splitlines()[0][:200] if body.strip() else ""
        raise ProviderError(
            provider,
            detail or f"the provider returned HTTP {exc.code}",
            status=exc.code,
        )
    except urllib.error.URLError as exc:
        raise ProviderError(provider, f"could not connect ({exc.reason})")
    except json.JSONDecodeError:
        raise ProviderError(provider, "the provider returned something that was not JSON")
    except TimeoutError:
        raise ProviderError(provider, f"no answer within {TIMEOUT}s")


def openai_models(key):
    body = fetch_json(
        "https://api.openai.com/v1/models",
        {"Authorization": "Bearer " + key},
        "openai",
    )
    names = [m["id"] for m in body.get("data", [])]
    chat = [n for n in names if not any(s in n for s in SKIP)]
    return sorted(chat) or sorted(names)


def anthropic_models(key):
    body = fetch_json(
        "https://api.anthropic.com/v1/models?limit=100",
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
        "anthropic",
    )
    return sorted(m["id"] for m in body.get("data", []))


def gemini_models(key):
    body = fetch_json(
        "https://generativelanguage.googleapis.com/v1beta/models?key=" + key,
        {},
        "gemini",
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
    except ProviderError as exc:
        # Name the provider and repeat what it said, so the message tells the
        # member whether the key, the account or the network is at fault.
        return {
            "models": [],
            "provider": exc.provider,
            "status": exc.status,
            "message": f"{exc.provider}: {exc.detail}",
        }, 502
    except Exception as exc:  # noqa: BLE001 - never leak a trace to the client
        return {
            "models": [],
            "provider": provider,
            "message": f"{provider}: {type(exc).__name__}",
        }, 502

    if not models:
        return {"models": [], "message": "That key returned no usable models."}, 200
    return {"models": models, "message": None}


def register(app):
    app.register_blueprint(models_api)
