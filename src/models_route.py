"""Live model discovery.

Asks a provider which models the pasted key can reach, so the member picks
from a real list instead of guessing a name.

This route makes an outbound call using the caller's key, so it requires a
live session — otherwise it would be an open relay for anyone who finds the
port.
"""

from flask import Blueprint

from auth import admin_from_token, member_from_token
from config import DB_FILE, ROUTES
from members import get_settings
from providers import (ProviderError, best_error, choices, detect, get,
                       validate_base_url)
from secret_store import decrypt_secret
from web import get_json_dict

models_api = Blueprint("models_api", __name__)


def _stored_key(member, admin):
    """The key already saved for this member, decrypted."""
    parent_id = member["Parent_id"] if member else admin["id"]
    employee_id = member["Employee_id"] if member else 0
    return decrypt_secret(get_settings(parent_id, employee_id)["API_KEY"] or "").strip()


@models_api.post(ROUTES["MODELS"])
def list_models():
    data = get_json_dict() or {}
    token = data.get("session_token")
    member = member_from_token(DB_FILE, token)
    admin = None if member else admin_from_token(DB_FILE, token)
    if member is None and admin is None:
        return {"models": [], "message": "Your session has ended. Sign in again."}, 401

    key = str(data.get("API_KEY") or "").strip()
    if not key:
        # No key pasted: use the one already saved. The field only ever holds
        # a mask, so demanding a re-paste made the list impossible to refresh
        # after the first save.
        key = _stored_key(member, admin)
        if not key:
            return {"models": [], "message": "Paste an API key first."}, 400

    requested = str(data.get("provider") or "auto").strip().lower()
    base = str(data.get("API_BASE") or "").strip()

    # Only a named provider may take a custom address, and it is checked
    # before the request goes out: this is a URL a user typed, and the server
    # is what would be making the call.
    if base and requested in ("auto", "custom", ""):
        named = get(requested) if requested not in ("auto", "") else get("custom")
        try:
            base = validate_base_url(base)
        except ProviderError as exc:
            exc.label = named.label
            return {"models": [], "provider": named.key, "message": str(exc)}, 400

    try:
        provider, models, errors = detect(key, requested or "auto", base)
    except ProviderError as exc:
        exc.label = (get(exc.provider) or get("custom")).label
        return {"models": [], "provider": exc.provider, "status": exc.status,
                "message": str(exc)}, 400

    if provider is None:
        failure = best_error(errors)
        return {
            "models": [],
            "message": str(failure) if failure else "That key returned no models.",
            "tried": [e.provider for e in errors],
        }, 502

    # Names come back namespaced for LiteLLM ("groq/llama-3.3-70b"), so the
    # name the member picks is the name that gets used to send the prompt.
    return {
        "models": [provider.qualify(m) for m in models],
        "provider": provider.key,
        "provider_label": provider.label,
        "message": None,
    }


@models_api.post(ROUTES["PROVIDERS"])
def list_providers():
    """The providers the connection page offers.

    A session is required because it tells the browser which addresses this
    deployment is willing to call.
    """
    data = get_json_dict() or {}
    token = data.get("session_token")
    member = member_from_token(DB_FILE, token)
    admin = None if member else admin_from_token(DB_FILE, token)
    if member is None and admin is None:
        return {"providers": [], "message": "Your session has ended. Sign in again."}, 401
    return {"providers": choices(), "message": None}


def register(app):
    app.register_blueprint(models_api)
