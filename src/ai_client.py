"""The outbound call to the AI provider.

This is the only place in the app that sends a prompt off the machine. Every
caller has applied the member’s saved checks or verified an administrator’s
explicit override.
"""

import logging
import time

from config import DEFAULT_MODEL, OPENAI_TIMEOUT
from errors import ChatError
from providers import get, normalise_model, validate_base_url


def _client():
    # LiteLLM's own diagnostics can include submitted messages and provider
    # responses. Keep the gateway's sanitized, type-only error log instead.
    for name in ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy"):
        logging.getLogger(name).disabled = True
    import litellm

    litellm.suppress_debug_info = True
    litellm.set_verbose = False
    litellm.log_raw_request_response = False
    litellm.turn_off_message_logging = True
    litellm.redact_messages_in_exceptions = True
    return litellm


def preload():
    """Import the provider client on the warm-up thread if available."""
    try:
        _client()
        return True
    except Exception:  # warm-up must never stop startup
        return False


def complete(api_key, model, prompt, api_base=None, provider=None):
    """Send one prompt and return the model's reply text.

    Raises ChatError(502) on any provider failure, so the route can report it
    without leaking a stack trace to the browser.
    """
    started = time.monotonic()
    name = (model or "").strip() or DEFAULT_MODEL
    if provider and provider != "auto":
        selected = get(provider)
        if selected is None or (selected.requires_base and not api_base):
            raise ChatError("Check the saved provider and its base URL in Settings.", 400)
        # A model ID is not a destination. A custom gateway may serve models
        # named after a different vendor; send its key only to the saved provider.
        name = selected.qualify(name)
        if selected.key in ("openai", "custom") and not name.startswith("openai/"):
            name = "openai/" + name
    else:
        name = normalise_model(name)  # preserve legacy, auto-provider settings
    try:
        client = _client()
        kwargs = {
            "model": name,
            "messages": [{"role": "user", "content": prompt}],
            "api_key": api_key or None,
            "timeout": OPENAI_TIMEOUT,
            "num_retries": 0,  # one completion budget after screening, not a chain of retries
        }
        # Revalidate even a previously saved base, including named providers.
        if api_base:
            kwargs["api_base"] = validate_base_url(api_base, require_dns=True)
        resp = client.completion(**kwargs)
        return resp.choices[0].message.content or ""
    except Exception as exc:
        # Third-party exceptions can include headers, prompt text or the key.
        logging.getLogger(__name__).warning("Provider call failed after %.1fs (%s)",
                                            time.monotonic() - started, type(exc).__name__)
        raise ChatError("AI API Error: the provider request failed. Check the saved key, model and base URL.", 502) from None
