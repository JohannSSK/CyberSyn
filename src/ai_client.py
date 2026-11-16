"""The outbound call to the AI provider.

This is the only place in the app that sends a prompt off the machine. Every
caller has already been through the privacy checks, which is what makes the
"nothing leaves until it is screened" claim true rather than aspirational.
"""

import time

from config import DEFAULT_MODEL, OPENAI_TIMEOUT
from errors import ChatError
from providers import normalise_model


def complete(api_key, model, prompt, api_base=None, provider=None):
    """Send one prompt and return the model's reply text.

    Raises ChatError(502) on any provider failure, so the route can report it
    without leaking a stack trace to the browser.
    """
    started = time.time()
    name = normalise_model(model) or DEFAULT_MODEL
    print(f"AI call model={name!r} provider={provider or '-'} "
          f"base={api_base or '-'} key_len={len(api_key or '')}", flush=True)
    try:
        from litellm import completion

        kwargs = {
            "model": name,
            "messages": [{"role": "user", "content": prompt}],
            "api_key": api_key or None,
            "timeout": OPENAI_TIMEOUT,
        }
        # Only ever set when the member configured a self-hosted or
        # OpenAI-compatible endpoint; the hosted providers use LiteLLM's own.
        if api_base:
            kwargs["api_base"] = api_base
        resp = completion(**kwargs)
        return resp.choices[0].message.content or ""
    except Exception as exc:
        print(
            f"AI call failed after {round(time.time() - started, 1)}s: "
            f"{type(exc).__name__}: {str(exc)[:300]}",
            flush=True,
        )
        raise ChatError(f"AI API Error: {exc}", 502)
