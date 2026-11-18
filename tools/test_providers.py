#!/usr/bin/env python3
"""Provider discovery and address safety.

The bug this guards: discovery guessed the provider from the shape of the
key and fell back to OpenAI for anything it did not recognise. A Google key
that did not match the expected prefix was sent to api.openai.com, which
rejected it, and the app reported the key as invalid. Discovery now contacts only
a prefix-matched provider, or the one explicitly selected.

Also covers the address checks, because the base-URL field lets someone
point this server at an address of their choosing.

    python3 tools/test_providers.py
"""
import sys

sys.path.insert(0, "src")

import providers  # noqa: E402

results = []


def check(name, ok, extra=""):
    results.append((name, ok))
    print(("  PASS  " if ok else "  FAIL  ") + name
          + (f" -> {extra}" if extra and not ok else ""))


# --------------------------------------------------------------------------
# Parsing: every provider answers in one of a handful of shapes
# --------------------------------------------------------------------------

# Only the socket is stubbed; parsing, filtering and qualification all run
# for real, so these check the code that ships rather than a copy of it.
SERVED = {}
CONTACTED = []
real_fetch = providers.fetch_json


def serve(url, body=None, error=None):
    SERVED[url] = (body, error)


def fake_fetch_json(url, headers, provider, timeout=None):
    CONTACTED.append(provider.key)
    served = None
    for pattern, payload in SERVED.items():
        if pattern in url:
            served = payload
            break
    if served is None:
        raise providers.ProviderError(provider.key, "the provider rejected the key",
                                      status=401)
    body, error = served
    if error:
        raise providers.ProviderError(provider.key, error[0], status=error[1])
    return body


providers.fetch_json = fake_fetch_json


openai_body = {
    "data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"},
             {"id": "text-embedding-3-large"}, {"id": "tts-1"},
             {"id": "dall-e-3"}, {"id": "whisper-1"}]
}
gemini_body = {
    "models": [
        {"name": "models/gemini-2.0-flash",
         "supportedGenerationMethods": ["generateContent", "countTokens"]},
        {"name": "models/gemini-1.5-pro",
         "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/text-embedding-004",
         "supportedGenerationMethods": ["embedContent"]},
        {"name": "models/imagen-3.0-generate-001",
         "supportedGenerationMethods": ["predict"]},
    ]
}
anthropic_body = {"data": [{"id": "claude-3-5-sonnet-20241022"},
                           {"id": "claude-3-opus-20240229"}]}
together_body = [
    {"id": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "type": "chat"},
    {"id": "BAAI/bge-large-en-v1.5", "type": "embedding"},
]
cohere_body = {"models": [{"name": "command-r-plus", "endpoints": ["chat"]},
                          {"name": "embed-english-v3.0", "endpoints": ["embed"]}]}
ollama_body = {"models": [{"name": "llama3.2:latest"}, {"name": "mistral:latest"}]}

serve("api.openai.com", openai_body)
serve("generativelanguage.googleapis.com", gemini_body)
serve("api.anthropic.com", anthropic_body)
serve("api.together.xyz", together_body)
serve("api.cohere.com", cohere_body)
serve("11434", ollama_body)

check("openai: chat models only",
      providers.get("openai").list_models("k") == ["gpt-4o", "gpt-4o-mini"],
      providers.get("openai").list_models("k"))
check("gemini: only generateContent models",
      providers.get("gemini").list_models("k") == ["gemini-1.5-pro", "gemini-2.0-flash"],
      providers.get("gemini").list_models("k"))
check("anthropic parsed", len(providers.get("anthropic").list_models("k")) == 2)
check("together: bare array, chat only",
      providers.get("together").list_models("k") ==
      ["meta-llama/Llama-3.3-70B-Instruct-Turbo"])
check("cohere: chat endpoints only",
      providers.get("cohere").list_models("k") == ["command-r-plus"])
check("ollama parsed", len(providers.get("ollama").list_models()) == 2)

# --------------------------------------------------------------------------
# Detection: the provider that answers is the one that is used
# --------------------------------------------------------------------------

# Only Gemini answers. Every other endpoint refuses, which is what happens
# in reality when a key is tried against the wrong provider.
SERVED.clear()
serve("generativelanguage.googleapis.com", gemini_body)

# The exact case that used to fail: a Google key that does not look like one.
CONTACTED.clear()
try:
    providers.detect("AizaSyNotTheUsualPrefix-xxxx")
    check("unknown format requires selection", False)
except providers.ProviderError as exc:
    check("unknown format requires selection without contacting anyone", "dropdown" in exc.detail and not CONTACTED)
provider, models, errors = providers.detect("AIzaSyExample")
check("a Google key is not sent to OpenAI",
      provider is not None and provider.key == "gemini",
      provider.key if provider else [str(e) for e in errors])
check("gemini models come back",
      models == ["gemini-1.5-pro", "gemini-2.0-flash"], models)
check("gemini names are qualified for litellm",
      provider.qualify(models[0]) == "gemini/gemini-1.5-pro", models)

# A key of an unrecognised shape still finds its provider.
SERVED.clear()
serve("api.groq.com", {"data": [{"id": "llama-3.3-70b-versatile"}]})
provider, models, _ = providers.detect("gsk_unknownshape")
check("a groq-shaped key finds groq",
      provider is not None and provider.key == "groq",
      provider.key if provider else "none")
check("groq model qualified for litellm",
      models and provider.qualify(models[0]) == "groq/llama-3.3-70b-versatile", models)

# Naming a provider explicitly never probes the others.
SERVED.clear()
provider, models, errors = providers.detect("sk-anything", "openai")
check("an unknown provider only tries the one named",
      provider is None and [e.provider for e in errors] == ["openai"],
      [e.provider for e in errors])

SERVED.clear()
serve("api.anthropic.com", anthropic_body)
serve("api.openai.com", anthropic_body)
provider, models, _ = providers.detect("sk-ambiguous", "anthropic")
check("an explicit provider is honoured even when another would answer",
      provider is not None and provider.key == "anthropic",
      provider.key if provider else "none")

# Nothing answers at all: the message has to name a provider and a reason.
SERVED.clear()
serve("api.openai.com", None, error=("Incorrect API key provided", 401))
serve("api.anthropic.com", None, error=("invalid x-api-key", 401))
provider, models, errors = providers.detect("sk-nothing")
check("total failure returns no models", provider is None and not models)
check("every attempt is reported", len(errors) == 1, len(errors))
best = providers.best_error(errors)
check("the refusal is preferred over a timeout",
      best is not None and best.status == 401, best)
check("the message names the provider",
      str(best).startswith(("OpenAI", "Anthropic")), str(best))
check("the message repeats what the provider said",
      "Incorrect API key" in str(best) or "invalid x-api-key" in str(best),
      str(best))

# A timeout is a worse explanation than a real refusal.
SERVED.clear()
serve("api.openai.com", None, error=("no answer within 8s", None))
serve("api.anthropic.com", None, error=("invalid x-api-key", 401))
_, _, errors = providers.detect("sk-mixed")
check("a matched timeout does not try an unrelated provider",
      [e.provider for e in errors] == ["openai"] and providers.best_error(errors).status is None,
      [str(e) for e in errors])

# --------------------------------------------------------------------------
# Address safety
# --------------------------------------------------------------------------

def base_ok(url):
    try:
        providers.validate_base_url(url)
        return True
    except providers.ProviderError:
        return False


check("https base accepted", base_ok("https://api.example.com/v1"))
check("port and path preserved", base_ok("https://api.example.com:8443/v1"))
check("an unresolvable name is allowed to fail on its own",
      base_ok("https://does-not-reserve.invalid"))
check("localhost accepted (Ollama)", base_ok("http://localhost:11434"))
check("loopback IP accepted", base_ok("http://127.0.0.1:8000"))
check("LAN address accepted", base_ok("http://192.168.1.50:11434"))
check("cloud metadata refused", not base_ok("http://169.254.169.254/latest/meta-data"))
check("metadata hostname refused", not base_ok("http://metadata.google.internal/"))
check("ftp refused", not base_ok("ftp://example.com"))
check("file refused", not base_ok("file:///etc/passwd"))
check("credentials in URL refused", not base_ok("https://user:pw@example.com"))
check("empty refused", not base_ok(""))
check("no host refused", not base_ok("https://"))

for prefix, service in (("sk-proj-", "openai"), ("sk-ant-", "anthropic"), ("sk-or-", "openrouter"),
                        ("gsk_", "groq"), ("AIza", "gemini"), ("xai-", "xai")):
    CONTACTED.clear()
    providers.detect(prefix + "fixture")
    check("only matched service contacted: " + prefix, CONTACTED == [service], CONTACTED)
base = "https://api.example.com:8443/llm/v1"
check("base path preserved", providers.validate_base_url(base) == base)
check("version path not doubled", providers.get("custom").endpoint(base) == base + "/models")
from unittest.mock import patch
import socket
import urllib.request
for address in ("[::ffff:169.254.169.254]", "100.100.100.200", "192.0.0.192", "[fd00:ec2::254]",
                "255.255.255.255", "224.0.0.1", "0.0.0.0", "[::]", "metadata", "instance-data"):
    check("special address refused: " + address, not base_ok("http://" + address))
# Exercise transition-address parsing without IPv6 connectivity or DNS.
import ipaddress
for ip in ("2002:a9fe:a9fe::1", "2001:0:4136:e378:8000:63bf:5601:5601"):
    check("link-local embedded in transition address is refused", bool(providers._address_reason(ipaddress.ip_address(ip))))
for suffix in ("?", "#", "?q=1", "#section"):
    check("base forbids query/fragment delimiters: " + suffix, not base_ok("http://127.0.0.1/prefix" + suffix))
with patch.object(providers, "ALLOW_PRIVATE_BASE", False):
    check("private-address opt out", not base_ok("http://127.0.0.1") and not base_ok("http://192.168.0.10"))
for url in ("file:///not-opened", "ftp://localhost", "http://[::ffff:169.254.169.254]/"):
    with patch.object(providers._OPENER, "open") as opened:
        try:
            real_fetch(url, {}, providers.get("custom"))
            check("fetch rejects " + url, False)
        except providers.ProviderError:
            check("fetch rejects " + url, not opened.called)
req = urllib.request.Request("https://127.0.0.1/models", headers={
    "Authorization": "test", "x-api-key": "test", "x-goog-api-key": "test"})
for url in ("http://127.0.0.1/models", "https://127.0.0.2/models", "https://127.0.0.1:8443/models"):
    redir = providers._SafeRedirect().redirect_request(req, None, 302, "Found", {}, url)
    check("redirect removes all credentials: " + url, not redir.header_items())
# Mock the resolver and socket: even if DNS changes, no unvalidated socket opens.
def address(ip):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]
with patch.object(socket, "getaddrinfo", side_effect=[address("8.8.8.8"), address("169.254.169.254")]), patch.object(socket, "socket") as sock:
    providers.validate_base_url("https://provider.invalid")
    try:
        providers._pinned_socket(("provider.invalid", 443), 4, None)
        check("rebinding refused", False)
    except providers.ProviderError:
        check("rebound host refused before TCP", not sock.called)
with patch.object(socket, "getaddrinfo", return_value=address("8.8.8.8")), patch.object(socket, "socket") as sock:
    providers._pinned_socket(("provider.invalid", 443), 4, None)
    check("connect uses the validated numeric sockaddr", sock.return_value.connect.call_args.args == (("8.8.8.8", 443),))

# An overlap introduced by a future registry entry must not broadcast the key.
with patch.object(providers, "PROVIDERS", [providers.get("openai"), providers.get("openai")]), patch.object(providers, "fetch_json") as fetch:
    try:
        providers.detect("sk-synthetic")
        check("ambiguous prefixes need an explicit provider", False)
    except providers.ProviderError:
        check("ambiguous prefixes need an explicit provider without contacting either", not fetch.called)
for key, path in (("gemini", "/tenant/v1beta"), ("openrouter", "/tenant/api/v1"), ("groq", "/tenant/openai/v1")):
    base = "https://127.0.0.1" + path
    check(key + " preserves the supplied versioned API root", providers.get(key).endpoint(base) == base + "/models")

# The TCP peer is pinned, but HTTP Host and TLS certificate/SNI identity
# remain the provider name. No TLS session or external connection is made.
import ssl
ctx = ssl.create_default_context()
with patch.object(socket, "getaddrinfo", return_value=address("8.8.8.8")), patch.object(socket, "socket"), patch.object(ctx, "wrap_socket") as wrap:
    conn = providers._HTTPSConnection("provider.invalid", timeout=3, context=ctx)
    conn.request("GET", "/models")
    check("pinned HTTPS retains the original certificate/SNI name", wrap.call_args.kwargs["server_hostname"] == "provider.invalid")
    check("pinned HTTPS retains the original Host header", b"Host: provider.invalid\r\n" in wrap.return_value.sendall.call_args.args[0])
    conn.close()

# The refusal has to say why, since it is shown to the person who typed it.
try:
    providers.validate_base_url("http://169.254.169.254")
    check("refusal carries a reason", False, "no exception raised")
except providers.ProviderError as exc:
    check("refusal carries a reason", "link-local" in exc.detail, exc.detail)

# --------------------------------------------------------------------------
# Model names
# --------------------------------------------------------------------------

check("gemini qualified", providers.get("gemini").qualify("gemini-2.0-flash")
      == "gemini/gemini-2.0-flash")
check("groq qualified", providers.get("groq").qualify("llama3-70b")
      == "groq/llama3-70b")
check("openai stays bare", providers.get("openai").qualify("gpt-4o") == "gpt-4o")
check("already-qualified not doubled",
      providers.get("groq").qualify("groq/llama3-70b") == "groq/llama3-70b")
check("cohere chat namespace",
      providers.get("cohere").qualify("command-r-plus") == "cohere_chat/command-r-plus")

check("legacy bare gemini name repaired",
      providers.normalise_model("gemini-1.5-pro") == "gemini/gemini-1.5-pro")
check("legacy bare claude name repaired",
      providers.normalise_model("claude-3-opus-20240229")
      == "anthropic/claude-3-opus-20240229")
check("namespaced name untouched",
      providers.normalise_model("groq/llama3-70b") == "groq/llama3-70b")
check("openai name untouched", providers.normalise_model("gpt-4o-mini") == "gpt-4o-mini")

# --------------------------------------------------------------------------
# The registry is complete
# --------------------------------------------------------------------------

keys = [p.key for p in providers.PROVIDERS]
for expected in ("openai", "anthropic", "gemini", "groq", "mistral",
                 "together", "deepseek", "xai", "cohere", "ollama",
                 "openrouter", "custom"):
    check(f"{expected} in the registry", expected in keys, keys)

check("every provider sends its key when it has one",
      all(p.headers("K") for p in providers.PROVIDERS if p.needs_key),
      [p.key for p in providers.PROVIDERS if p.needs_key and not p.headers("K")])
check("ollama needs no key", providers.get("ollama").needs_key is False)
check("no provider puts the key in the URL",
      all("{key}" not in (p.models_url or "") for p in providers.PROVIDERS))
check("choices leads with auto", providers.choices()[0]["key"] == "auto")

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
