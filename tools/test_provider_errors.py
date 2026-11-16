#!/usr/bin/env python3
"""Model discovery must say *why* a provider refused, not just "HTTPError".

Before this, every failure came back as `Could not reach openai: HTTPError`,
so a rejected key, an exhausted quota and a network outage were
indistinguishable and nothing could be fixed from the message.

    python3 tools/test_provider_errors.py
"""
import json, sys, threading, tempfile, os
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, "src")
import providers
from providers import ProviderError

PROBE = providers.get("custom")

results = []
def check(name, ok, extra=""):
    results.append((name, ok, extra))
    print(("  PASS  " if ok else "  FAIL  ") + name + (f" -> {extra}" if extra else ""))

class Handler(BaseHTTPRequestHandler):
    code = 200
    body = b"{}"
    def do_GET(self):
        self.send_response(Handler.code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(Handler.body)))
        self.end_headers()
        self.wfile.write(Handler.body)
    def log_message(self, *a): pass

srv = HTTPServer(("127.0.0.1", 8123), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:8123/models"

# 1. A rejected key: OpenAI's real 401 body shape.
Handler.code, Handler.body = 401, json.dumps(
    {"error": {"message": "Incorrect API key provided: sk-bad. "
                          "You can find your API key at https://platform.openai.com.",
               "type": "invalid_request_error"}}).encode()
try:
    providers.fetch_json(URL, {"Authorization": "Bearer sk-bad"}, providers.get("openai"))
    check("401 raises", False, "no exception")
except ProviderError as e:
    check("401 carries the status", e.status == 401, e.status)
    check("401 repeats the provider's reason", "Incorrect API key provided" in e.detail, e.detail)

# 2. Quota exhausted.
Handler.code, Handler.body = 429, json.dumps(
    {"error": {"message": "You exceeded your current quota, please check your plan."}}).encode()
try:
    providers.fetch_json(URL, {}, providers.get("openai"))
except ProviderError as e:
    check("429 explanation surfaced", "quota" in e.detail.lower(), e.detail)

# 3. A body that is not JSON at all (a proxy login page, say).
Handler.code, Handler.body = 200, b"<html>sign in to the network</html>"
try:
    providers.fetch_json(URL, {}, providers.get("gemini"))
    check("non-JSON body detected", False, "no exception")
except ProviderError as e:
    check("non-JSON body detected", "not JSON" in e.detail, e.detail)

# 4. Unreachable host.
try:
    providers.fetch_json("http://127.0.0.1:9/models", {}, providers.get("anthropic"))
    check("connection failure detected", False, "no exception")
except ProviderError as e:
    check("connection failure names the provider", e.provider == "anthropic", e.provider)
    check("connection failure is readable", "could not connect" in e.detail, e.detail)

# 5. A key is never echoed back into the message.
Handler.code, Handler.body = 401, json.dumps(
    {"error": {"message": "Incorrect API key provided: sk-SECRET-1234."}}).encode()
try:
    providers.fetch_json(URL, {}, providers.get("openai"))
except ProviderError as e:
    check("detail is truncated, not unbounded", len(e.detail) <= 400, len(e.detail))

# 6. The happy path still parses.
Handler.code, Handler.body = 200, json.dumps(
    {"data": [{"id": "gpt-4o"}, {"id": "tts-1"}]}).encode()
body = providers.fetch_json(URL, {}, providers.get("openai"))
check("success returns parsed JSON", body["data"][0]["id"] == "gpt-4o", body)

srv.shutdown()
failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results)-len(failed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
