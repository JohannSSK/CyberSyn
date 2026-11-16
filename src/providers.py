"""Every AI provider the gateway can reach, in one registry.

Three facts belong together for each provider — where its model list lives,
how to authenticate, and what LiteLLM calls each model — because getting any
one of them wrong produces a key that appears to be "rejected". Keeping them
side by side is what stops them drifting apart.

Discovery does not guess from the shape of the key. A prefix only decides the
order providers are tried in; the provider that answers is the provider that
is used. That matters because most providers hand out `sk-`-shaped keys, so
any prefix rule eventually sends a valid key to the wrong endpoint and reports
it as invalid.
"""

import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

# Long enough for a slow provider, short enough that a dead one is not a wait.
TIMEOUT = 20
# Probing tries several providers, so each attempt gets a tighter budget.
PROBE_TIMEOUT = 8
# A model list is a few kilobytes; anything larger is not one.
MAX_BYTES = 4 * 1024 * 1024

# Model families that cannot hold a chat conversation.
NON_CHAT = (
    "tts", "image", "embedding", "lyria", "veo", "imagen", "aqa",
    "robotics", "live", "audio", "computer-use", "transcribe", "realtime",
    "search", "moderation", "dall", "whisper", "davinci", "babbage",
    "rerank", "moderate", "classify", "embed",
)


class ProviderError(Exception):
    """A provider call failed, carrying enough detail to act on."""

    def __init__(self, provider, detail, status=None):
        super().__init__(detail)
        self.provider = provider          # our key, e.g. "gemini"
        self.label = None                 # filled in by the registry
        self.detail = detail
        self.status = status

    def __str__(self):
        return f"{self.label or self.provider}: {self.detail}"


# --------------------------------------------------------------------------
# Parsing — every provider answers in one of a handful of shapes
# --------------------------------------------------------------------------

def _data_ids(body, _provider):
    """OpenAI's shape: {"data": [{"id": "gpt-4o"}]}."""
    return [m["id"] for m in body.get("data", []) if isinstance(m, dict) and m.get("id")]


def _named_models(body, _provider):
    """{"models": [{"name": "..."}]}."""
    return [m["name"] for m in body.get("models", []) if isinstance(m, dict) and m.get("name")]


def _bare_list(body, _provider):
    """Together's shape: a bare JSON array of model objects."""
    if not isinstance(body, list):
        return []
    return [m["id"] for m in body if isinstance(m, dict) and m.get("id")]


def _gemini(body, _provider):
    names = []
    for model in body.get("models", []):
        if not isinstance(model, dict):
            continue
        # Gemini lists embeddings and MusicGen alongside the chat models;
        # only the ones that accept generateContent are any use here.
        methods = model.get("supportedGenerationMethods") or []
        if "generateContent" not in methods:
            continue
        name = str(model.get("name", "")).split("/")[-1]
        if name:
            names.append(name)
    return names


def _together(body, provider):
    names = []
    for model in body.get("data", []) if isinstance(body, dict) else body or []:
        if not isinstance(model, dict) or not model.get("id"):
            continue
        if model.get("type") not in (None, "", "chat", "text"):
            continue
        names.append(model["id"])
    return names


def _cohere(body, _provider):
    names = []
    for model in body.get("models", []):
        if not isinstance(model, dict) or not model.get("name"):
            continue
        endpoints = model.get("endpoints") or []
        if endpoints and "chat" not in endpoints:
            continue
        names.append(model["name"])
    return names


def _ollama(body, _provider):
    return [m["name"] for m in body.get("models", [])
            if isinstance(m, dict) and m.get("name")]


# --------------------------------------------------------------------------
# Address safety
# --------------------------------------------------------------------------

def _blocked_reason(hostname):
    """Why a host may not be used as an API base, or None if it may.

    This runs on a URL a user typed, so it exists to stop that URL being
    pointed at something it should not reach: a cloud metadata service, or
    a host reached through credentials smuggled into the URL.

    Loopback and private ranges are deliberately allowed. This is a
    self-hosted gateway and a model server on the same machine or the same
    LAN — Ollama being the common case — is the whole point of the setting.
    """
    if not hostname:
        return "the URL has no host"
    host = hostname.strip().strip("[]").lower()
    if host in ("metadata.google.internal", "metadata.goog"):
        return "that host is a cloud metadata service"
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        # A name rather than a literal. Resolving it is best effort: behind
        # a split-horizon DNS or with no network at all the lookup fails,
        # and a name that cannot be resolved is one nothing can be fetched
        # from either. What matters is refusing the names that do resolve
        # somewhere they should not.
        try:
            addresses = [ipaddress.ip_address(info[4][0])
                         for info in socket.getaddrinfo(host, None)]
        except (socket.gaierror, UnicodeError, ValueError):
            return None
    for address in addresses:
        # 169.254.0.0/16 is link-local, which is where 169.254.169.254
        # (the AWS/GCP/Azure metadata endpoint) lives. Reachable from any
        # server and it hands out credentials, so it is refused outright.
        if address.is_link_local:
            return "that address is a link-local/metadata address"
    return None


def validate_base_url(raw):
    """Check a user-supplied API base URL, returning a clean absolute URL.

    Raises ProviderError with a plain-language reason, because the message is
    shown to whoever typed the URL.
    """
    text = (raw or "").strip()
    if not text:
        raise ProviderError("custom", "enter the base URL for that provider")
    if len(text) > 500:
        raise ProviderError("custom", "that URL is too long")
    parts = urllib.parse.urlsplit(text)
    if parts.scheme not in ("http", "https"):
        raise ProviderError("custom", "the base URL must start with http:// or https://")
    # "https://expected.com@evil.internal/" parses with evil.internal as the
    # host, so a URL carrying credentials is refused rather than unwrapped.
    if parts.username or parts.password:
        raise ProviderError("custom", "the base URL must not contain a username or password")
    if not parts.hostname:
        raise ProviderError("custom", "the base URL has no host")
    reason = _blocked_reason(parts.hostname)
    if reason:
        raise ProviderError("custom", reason)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, "", "", ""))


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Re-check each redirect against the same rules as the original URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        if parts.scheme not in ("http", "https"):
            raise urllib.error.URLError(ProviderError(
                "custom", "the server redirected to a non-HTTP address"))
        reason = _blocked_reason(parts.hostname or "")
        if reason:
            raise urllib.error.URLError(ProviderError(
                "custom", "the server redirected somewhere that is not allowed: " + reason))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirect)


def fetch_json(url, headers, provider, timeout=TIMEOUT):
    """GET `url` and parse the JSON body, turning failure into ProviderError."""
    request = urllib.request.Request(
        url, headers=dict(headers or {}, **{"User-Agent": "CyberSyn/1.0"})
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        # The provider's own explanation is the useful part: "Incorrect API
        # key provided", "You exceeded your current quota", and so on.
        detail = ""
        try:
            body = exc.read(2048).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - the body is a nicety, not a need
            body = ""
        if body:
            try:
                parsed = json.loads(body)
                error = parsed.get("error") or {}
                detail = (error.get("message") if isinstance(error, dict)
                          else str(error)) or parsed.get("message", "")
            except ValueError:
                detail = body.strip().splitlines()[0][:200]
        raise ProviderError(
            provider.key, detail or f"the provider returned HTTP {exc.code}",
            status=exc.code,
        )
    except urllib.error.URLError as exc:
        # _SafeRedirect raises URLError(ProviderError) for a bad redirect.
        if isinstance(exc.reason, ProviderError):
            raise exc.reason
        raise ProviderError(provider.key, f"could not connect ({exc.reason})")
    except TimeoutError:
        raise ProviderError(provider.key, f"no answer within {timeout}s")
    except OSError as exc:
        raise ProviderError(provider.key, f"could not connect ({exc})")

    if len(raw) > MAX_BYTES:
        raise ProviderError(provider.key, "the model list was too large")
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise ProviderError(provider.key,
                            "the provider returned something that was not JSON")


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------

class Provider:
    """One reachable AI provider."""

    def __init__(self, key, label, models_url=None, models_path="/v1/models",
                 headers=None, parse=None, prefixes=(), litellm_prefix="",
                 needs_key=True, default_base=None, requires_base=False,
                 key_hint=""):
        self.key = key
        self.label = label
        self.models_url = models_url
        self.models_path = models_path
        self.headers = headers or (lambda _key: {})
        self.parse = parse or _data_ids
        self.prefixes = tuple(prefixes)
        self.litellm_prefix = litellm_prefix
        self.needs_key = needs_key
        self.default_base = default_base
        self.requires_base = requires_base
        self.key_hint = key_hint

    def qualify(self, model_id):
        """The name LiteLLM needs for this model."""
        if not self.litellm_prefix or model_id.startswith(self.litellm_prefix):
            return model_id
        return self.litellm_prefix + model_id

    def endpoint(self, base_url=None):
        """Where to ask for the model list."""
        base = (base_url or self.default_base or "").rstrip("/")
        if base:
            return base + self.models_path
        return self.models_url

    def list_models(self, api_key=None, base_url=None, timeout=TIMEOUT):
        """Ask this provider which chat models the key can reach."""
        if self.needs_key and not (api_key or "").strip():
            raise ProviderError(self.key, "no API key to try")
        url = self.endpoint(base_url)
        if not url:
            raise ProviderError(self.key, "no address to ask")
        body = fetch_json(url, self.headers(api_key or ""), self, timeout=timeout)
        names = [str(n) for n in self.parse(body, self) if str(n).strip()]
        chat = [n for n in names if not any(s in n.lower() for s in NON_CHAT)]
        return sorted(set(chat)) or sorted(set(names))

    def matches(self, api_key):
        """Does the key look like one of this provider's? A hint, not a proof."""
        return any((api_key or "").startswith(p) for p in self.prefixes)


def _bearer(api_key):
    return {"Authorization": "Bearer " + api_key}


class _Cohere(Provider):
    """Cohere's newer chat models need a different LiteLLM namespace."""

    def qualify(self, model_id):
        if model_id.startswith(("cohere/", "cohere_chat/")):
            return model_id
        if model_id.startswith("command"):
            return "cohere_chat/" + model_id
        return "cohere/" + model_id


PROVIDERS = [
    Provider("openai", "OpenAI",
             models_url="https://api.openai.com/v1/models",
             headers=_bearer, prefixes=("sk-proj-", "sk-"), key_hint="sk-…"),
    Provider("anthropic", "Anthropic",
             models_url="https://api.anthropic.com/v1/models?limit=100",
             headers=lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"},
             prefixes=("sk-ant-",), litellm_prefix="anthropic/", key_hint="sk-ant-…"),
    # The key goes in a header, never the query string: a URL is logged by
    # proxies and browsers, and this key is the customer's.
    Provider("gemini", "Google Gemini",
             models_url="https://generativelanguage.googleapis.com/v1beta/models",
             headers=lambda k: {"x-goog-api-key": k},
             parse=_gemini, prefixes=("AIza",), litellm_prefix="gemini/",
             key_hint="AIza…"),
    Provider("openrouter", "OpenRouter",
             models_url="https://openrouter.ai/api/v1/models",
             models_path="/api/v1/models", headers=_bearer,
             prefixes=("sk-or-",), litellm_prefix="openrouter/", key_hint="sk-or-v1-…"),
    Provider("groq", "Groq",
             models_url="https://api.groq.com/openai/v1/models",
             models_path="/openai/v1/models", headers=_bearer,
             prefixes=("gsk_",), litellm_prefix="groq/", key_hint="gsk_…"),
    Provider("mistral", "Mistral AI",
             models_url="https://api.mistral.ai/v1/models",
             headers=_bearer, litellm_prefix="mistral/"),
    Provider("together", "Together AI",
             models_url="https://api.together.xyz/v1/models",
             headers=_bearer, parse=_together, litellm_prefix="together_ai/"),
    Provider("deepseek", "DeepSeek",
             models_url="https://api.deepseek.com/models",
             models_path="/models", headers=_bearer, litellm_prefix="deepseek/"),
    Provider("xai", "xAI (Grok)",
             models_url="https://api.x.ai/v1/models", headers=_bearer,
             prefixes=("xai-",), litellm_prefix="xai/", key_hint="xai-…"),
    _Cohere("cohere", "Cohere",
            models_url="https://api.cohere.com/v1/models",
            headers=_bearer, parse=_cohere),
    Provider("ollama", "Ollama (local)",
             models_path="/api/tags", parse=_ollama, needs_key=False,
             default_base="http://localhost:11434", litellm_prefix="ollama/"),
    Provider("custom", "Custom (OpenAI-compatible)",
             headers=_bearer, requires_base=True),
]

BY_KEY = {p.key: p for p in PROVIDERS}


def get(key):
    return BY_KEY.get((key or "").strip().lower())


def choices():
    """What the settings page offers: auto, then each provider by name."""
    return [{"key": "auto", "label": "Detect automatically"}] + [
        {"key": p.key, "label": p.label, "hint": p.key_hint,
         "needs_key": p.needs_key, "needs_base": p.requires_base or bool(p.default_base)}
        for p in PROVIDERS
    ]


def detect(api_key, provider_key=None, base_url=None, timeout=PROBE_TIMEOUT):
    """Find which provider the key belongs to and list its chat models.

    With `provider_key` given, only that provider is tried — the caller has
    already said which it is, and a wrong guess elsewhere is just noise.
    Otherwise every provider is tried, prefix matches first, and the one that
    answers is used.

    Returns (provider, models, errors). On total failure `provider` is None
    and `errors` carries one ProviderError per attempt, most likely first.
    """
    chosen = get(provider_key) if provider_key and provider_key != "auto" else None
    if chosen is not None:
        if chosen.requires_base and not (base_url or "").strip():
            raise ProviderError(chosen.key, "enter the base URL for that provider")
        try:
            return chosen, chosen.list_models(api_key, base_url, timeout=TIMEOUT), []
        except ProviderError as exc:
            # Same shape as the probing path, so the caller needs one branch.
            exc.label = chosen.label
            return None, [], [exc]

    ordered = [p for p in PROVIDERS if p.matches(api_key)]
    ordered += [p for p in PROVIDERS
                if p not in ordered and p.key != "custom" and not p.requires_base]
    if api_key:
        ordered = [p for p in ordered if p.needs_key] or ordered

    errors = []
    for provider in ordered:
        # A provider whose shape the key matches gets the full timeout; the
        # rest are only being ruled out.
        budget = TIMEOUT if provider.matches(api_key) else timeout
        try:
            models = provider.list_models(api_key, None, timeout=budget)
        except ProviderError as exc:
            exc.label = provider.label
            errors.append(exc)
            continue
        if models:
            return provider, models, errors
        errors.append(ProviderError(provider.key, "no chat models on this key"))
    return None, [], errors


def best_error(errors):
    """The message most likely to explain the failure."""
    if not errors:
        return None
    for exc in errors:                       # a real refusal beats a timeout
        if exc.status in (401, 403):
            return exc
    for exc in errors:                       # then the provider's own words
        if exc.status is not None:
            return exc
    return errors[0]


def normalise_model(name):
    """Make an existing stored model name safe for LiteLLM.

    Names saved before providers were explicit can be bare (`gemini-1.5-pro`
    rather than `gemini/gemini-1.5-pro`), which LiteLLM reads as an OpenAI
    model. A name that already carries a provider prefix is left alone.
    """
    text = (name or "").strip()
    if not text or "/" in text:
        return text
    lower = text.lower()
    if lower.startswith("gemini"):
        return "gemini/" + text
    if lower.startswith("claude"):
        return "anthropic/" + text
    return text
