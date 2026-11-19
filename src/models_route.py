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
from providers import ProviderError, best_error, choices, detect, get as get_provider, validate_base_url
from secret_store import decrypt_secret
from web import get_json_dict

models_api = Blueprint("models_api", __name__)


def _identity(data):
    token = data.get("session_token")
    member = member_from_token(DB_FILE, token)
    admin = None if member else admin_from_token(DB_FILE, token)
    return member, admin


@models_api.post(ROUTES["MODELS"])
def list_models():
    data = get_json_dict() or {}
    member, admin = _identity(data)
    if member is None and admin is None:
        return {"models": [], "message": "Your session has ended. Sign in again."}, 401
    pid = member["Parent_id"] if member else admin["id"]
    key = str(data.get("API_KEY") or "").strip()
    saved = None if key else get_settings(pid, member["Employee_id"] if member else 0)
    requested = str(data.get("provider", saved["PROVIDER"] if saved else "auto") or "auto").strip().lower()
    base = str(data.get("API_BASE", saved["API_BASE"] if saved else "") or "").strip()
    target_provider = get_provider(requested) if requested not in ("", "auto") else None
    needs_key = target_provider.needs_key if target_provider else True
    try:
        if base:
            base = validate_base_url(base)
        if saved:
            key = decrypt_secret(saved["API_KEY"]).strip()
            if not key and needs_key:
                return {"models": [], "message": "Paste an API key first."}, 400
            old_base = validate_base_url(saved["API_BASE"]) if saved["API_BASE"] else ""
            old_provider = saved["PROVIDER"] or "auto"
            if key:
                if base != old_base and base.startswith("http://"):
                    return {"models": [], "message": "Save this HTTP base with administrator approval first."}, 403
                if base != old_base or requested != old_provider or data.get("admin_token"):
                    approved = admin_from_token(DB_FILE, data.get("admin_token", data.get("session_token")),
                                                parent_id=pid, consume=True)
                    if not approved:
                        status = 401 if data.get("admin_token") else 403
                        return {"models": [], "message": "Using the saved key at another destination needs administrator approval."}, status
        provider, models, errors = detect(key, requested, base)
    except ProviderError as exc:
        return {"models": [], "provider": exc.provider, "status": exc.status, "message": str(exc)}, 400

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
    member, admin = _identity(data)
    if member is None and admin is None:
        return {"providers": [], "message": "Your session has ended. Sign in again."}, 401
    return {"providers": choices(), "message": None}


def register(app):
    app.register_blueprint(models_api)
