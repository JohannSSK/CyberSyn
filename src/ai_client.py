"""The outbound call to the AI provider.

This is the only place in the app that sends a prompt off the machine. Every
caller has already been through the privacy checks, which is what makes the
"nothing leaves until it is screened" claim true rather than aspirational.
"""

import time

from config import DEFAULT_MODEL, OPENAI_TIMEOUT
from errors import ChatError


def resolve_model(name):
    """LiteLLM wants Gemini models namespaced as `gemini/...`."""
    name = (name or "").strip() or DEFAULT_MODEL
    if name.startswith("gemini-"):
        return "gemini/" + name
    return name


def complete(api_key, model, prompt):
    """Send one prompt and return the model's reply text.

    Raises ChatError(502) on any provider failure, so the route can report it
    without leaking a stack trace to the browser.
    """
    started = time.time()
    print(f"AI call model={model!r} key_len={len(api_key or '')}", flush=True)
    try:
        from litellm import completion

        resp = completion(
            model=resolve_model(model),
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
            timeout=OPENAI_TIMEOUT,
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:
        print(
            f"AI call failed after {round(time.time() - started, 1)}s: "
            f"{type(exc).__name__}: {str(exc)[:300]}",
            flush=True,
        )
        raise ChatError(f"AI API Error: {exc}", 502)
