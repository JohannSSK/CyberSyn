"""Every AI provider the gateway can reach, in one registry.

Three facts belong together for each provider — where its model list lives,
how to authenticate, and what LiteLLM calls each model — because getting any
one of them wrong produces a key that appears to be "rejected". Keeping them
side by side is what stops them drifting apart.

Automatic discovery stays within recognized key prefixes. Unknown or ambiguous
formats need an explicit provider choice; keys are never broadcast.
"""

import http.client
import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from config import ALLOW_PRIVATE_BASE

# Long enough for a slow provider, short enough that a dead one is not a wait.
TIMEOUT = 20
# Automatic, prefix-scoped discovery gets a tighter budget.
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

_METADATA = {"metadata.google.internal", "metadata.goog", "metadata", "instance-data", "instance-data.ec2.internal"}
_DENIED_IPS = {ipaddress.ip_address(ip) for ip in
               ("100.100.100.200", "192.0.0.192", "fd00:ec2::254", "255.255.255.255")}


def _address_reason(addr):
    if addr.is_link_local or addr in _DENIED_IPS:
        return "that address is a link-local/metadata or broadcast address"
    if addr.is_unspecified or addr.is_multicast:
        return "unspecified and multicast addresses are not allowed"
    embedded = []
    if isinstance(addr, ipaddress.IPv6Address):
        embedded = [a for a in (addr.ipv4_mapped, addr.sixtofour, *(addr.teredo or ())) if a is not None]
    for inner in embedded:
        reason = _address_reason(inner)
        if reason:
            return reason
    if not ALLOW_PRIVATE_BASE and not addr.is_global:
        return "private and non-public addresses are disabled on this gateway"
    return None


def _resolve(host, port):
    if not host or host.lower().rstrip(".") in _METADATA:
        raise ProviderError("custom", "that host is missing or is a cloud metadata service")
    # A forbidden literal stays forbidden even on a host without DNS/IPv6.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and (reason := _address_reason(literal)):
        raise ProviderError("custom", reason)
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not infos:
        raise socket.gaierror("no provider addresses")
    for _, _, _, _, sockaddr in infos:
        reason = _address_reason(ipaddress.ip_address(sockaddr[0]))
        if reason:
            raise ProviderError("custom", reason)
    return infos


def _blocked_reason(hostname, require_dns=False):
    try:
        _resolve(hostname, None)
    except ProviderError as exc:
        return exc.detail
    except socket.gaierror:
        # Saving an offline hostname is OK. Making a request to one is not.
        if require_dns:
            return "the provider hostname could not be resolved"
    except (UnicodeError, ValueError, OSError):
        return "invalid provider hostname"
    return None


def _url_parts(text, *, query=False, require_dns=False):
    try:
        parts = urllib.parse.urlsplit(text)
        port = parts.port  # validate the port even when only saving the address
        host = parts.hostname
    except ValueError:
        raise ProviderError("custom", "invalid provider URL or port") from None
    if (parts.scheme not in ("http", "https") or not host or not parts.netloc or port == 0 or
            parts.username is not None or "\\" in text or "%" in parts.netloc or
            any(ord(c) <= 32 or ord(c) == 127 for c in text)):
        raise ProviderError("custom", "enter an HTTP or HTTPS URL with a host and no credentials")
    if "#" in text or ("?" in text and not query):
        raise ProviderError("custom", "the base URL must not contain a query or fragment")
    reason = _blocked_reason(host, require_dns)
    if reason:
        raise ProviderError("custom", reason)
    return parts


def validate_base_url(raw, *, require_dns=False):
    text = (raw or "").strip()
    if len(text) > 500:
        raise ProviderError("custom", "that URL is too long")
    parts = _url_parts(text, require_dns=require_dns)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _pinned_socket(address, timeout, source_address):
    # Keep the original connection.host for Host, certificate validation and
    # SNI. Only the TCP socket uses the checked numeric sockaddr, never a second
    # resolution of the hostname (including when a request follows a redirect).
    last = OSError("no address resolved")
    for family, kind, proto, _, sockaddr in _resolve(*address):
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            sock.close()
            last = exc
    raise last


class _PinnedConnection:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _pinned_socket


class _HTTPConnection(_PinnedConnection, http.client.HTTPConnection):
    pass


class _HTTPSConnection(_PinnedConnection, http.client.HTTPSConnection):
    pass


class _HTTP(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_HTTPConnection, req)


class _HTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPSConnection, req, context=self._context)


def _origin(parts):
    return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = _url_parts(newurl, query=True)
        target = super().redirect_request(req, fp, code, msg, headers, newurl)
        if target and _origin(parts) != _origin(urllib.parse.urlsplit(req.full_url)):
            for header in list(target.headers):
                if header.lower() in ("authorization", "x-api-key", "x-goog-api-key"):
                    target.remove_header(header)
        return target


_OPENER = urllib.request.OpenerDirector()
for handler in (_HTTP(), _HTTPS(), urllib.request.HTTPDefaultErrorHandler(),
                urllib.request.HTTPErrorProcessor(), _SafeRedirect()):
    _OPENER.add_handler(handler)


def fetch_json(url, headers, provider, timeout=TIMEOUT):
    """GET `url` and parse the JSON body, turning failure into ProviderError."""
    _url_parts(url, query=True)
    request = urllib.request.Request(
        url, headers=dict(headers or {}, **{"User-Agent": "CyberSyn/1.0"})
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        # The body is untrusted: providers sometimes echo credentials or
        # fragments that no exact-string redactor can reliably recognize.
        exc.close()
        detail = {401: "Incorrect API key provided. Check the key and provider.",
                  403: "The key does not have access to this provider's models.",
                  429: "The provider's rate limit or quota was reached."}
        raise ProviderError(provider.key, detail.get(exc.code, f"the provider returned HTTP {exc.code}"),
                            status=exc.code) from None
    except TimeoutError:
        raise ProviderError(provider.key, f"no answer within {timeout}s") from None
    except (OSError, http.client.HTTPException, ValueError):
        raise ProviderError(provider.key, "could not connect to the provider") from None

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
        base = base_url or self.default_base
        if base:
            base = validate_base_url(base)
            if self.models_path.endswith("/models") and base.endswith(("/v1", "/v1beta")):
                return base + "/models"
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
        try:
            names = [n for n in self.parse(body, self) if isinstance(n, str) and n.strip()]
        except (AttributeError, KeyError, TypeError, ValueError):
            raise ProviderError(self.key, "the provider returned an unexpected model list format") from None
        chat = [n for n in names if not any(s in n.lower() for s in NON_CHAT)]
        return sorted(set(chat)) or sorted(set(names))

    def matches(self, api_key):
        """Does the key look like one of this provider's? A hint, not a proof."""
        if self.key == "openai" and (api_key or "").startswith(("sk-ant-", "sk-or-")):
            return False
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
             models_url="https://generativelanguage.googleapis.com/v1beta/models", models_path="/v1beta/models",
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
    Otherwise only a provider matching the key prefix may be contacted.
    """
    chosen = get(provider_key)
    if provider_key not in (None, "auto", "") and chosen is None:
        raise ProviderError("custom", "select a supported provider")
    if chosen is not None:
        if chosen.requires_base and not (base_url or "").strip():
            raise ProviderError(chosen.key, "enter the base URL for that provider")
        try:
            return chosen, chosen.list_models(api_key, base_url, timeout=TIMEOUT), []
        except ProviderError as exc:
            # Same shape as the probing path, so the caller needs one branch.
            exc.label = chosen.label
            return None, [], [exc]

    matches = [p for p in PROVIDERS if p.matches(api_key)]
    if len(matches) != 1:
        raise ProviderError("auto", "Could not identify the provider from the key format — select your "
                            "provider from the Provider dropdown so your key is only sent to that service.")
    provider = matches[0]
    try:
        models = provider.list_models(api_key, base_url, timeout=timeout)
    except ProviderError as exc:
        exc.label = provider.label
        return None, [], [exc]
    if not models:
        return None, [], [ProviderError(provider.key, "no chat models on this key")]
    return provider, models, []


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
