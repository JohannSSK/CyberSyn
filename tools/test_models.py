#!/usr/bin/env python3
"""Model discovery: does the route use the key already saved for the member?

The bug this guards: /api/admin/employee/models demanded a freshly pasted
API_KEY, but the settings field only ever holds a mask ("****abcd"), so the
list could never be refreshed once a key had been saved. The route now falls
back to the member's stored key.

    python3 tools/test_models.py
"""
import os
import sys
import tempfile

DB = tempfile.mktemp(suffix=".db")
os.environ["CYBERSYN_DB_FILE"] = DB
os.environ["CYBERSYN_KEY_FILE"] = DB + ".key"
sys.path.insert(0, "src")

import providers  # noqa: E402

from config import ROUTES  # noqa: E402
from app import create_app  # noqa: E402
import db as db_module  # noqa: E402

db_module.seed("tester", "test-pw-123")   # no default account exists
app = create_app()
con = app.test_client(use_cookies=False)

captured = {}
import routes.chat_api  # noqa: F401  (registered below)


# Stub the one outbound call so we can see which key and which address the
# route actually used. Everything above it is the real code path.
def fake_fetch_json(url, headers, provider, timeout=None):
    captured["url"] = url
    captured["headers"] = headers
    captured["provider"] = provider.key
    if "openai.com" not in url:
        raise providers.ProviderError(provider.key, "the provider returned HTTP 401",
                                      status=401)
    return {
        "data": [
            {"id": "gpt-4o"},
            {"id": "gpt-4o-mini"},
            {"id": "text-embedding-3-large"},   # not a chat model
            {"id": "tts-1"},                    # not a chat model
        ]
    }


providers.fetch_json = fake_fetch_json

results = []


def check(name, ok, extra=""):
    results.append((name, ok, extra))
    print(("  PASS  " if ok else "  FAIL  ") + name
          + (f" -> {extra}" if extra and not ok else ""))


r = con.post(ROUTES["ADMIN_LOGIN"], json={"username": "tester", "password": "test-pw-123"})
check("admin signs in", r.status_code == 200, r.get_json())
admin = r.get_json()
admin_token, parent_id = admin["session_token"], int(admin["Parent_id"])

r = con.post(ROUTES["EMPLOYEE"], json={"method": "add", "Parent_id": parent_id,
                                          "username": "mia", "password": "Passw0rd!",
                                          "token": admin_token})
check("member created", r.status_code in (200, 201), r.get_json())

r = con.post(ROUTES["EMPLOYEE_LOGIN"], json={"Parent_id": parent_id,
                                                "username": "mia", "password": "Passw0rd!"})
check("member signs in", r.status_code == 200, r.get_json())
member = r.get_json()

SAVED_KEY = "sk-saved-key-ABCD"
member_body = {"session_token": member["session_token"],
               "Parent_id": parent_id, "Employee_id": member["Employee_id"]}

# Saving is an administrator action now, so it carries the admin's approval.
r = con.post(ROUTES["SETTINGS"],
             json=dict(member_body, API_KEY=SAVED_KEY, admin_token=admin_token))
check("key saved with administrator approval", r.status_code == 200, r.get_json())

r = con.post(ROUTES["SETTINGS"], json=dict(member_body, API_KEY="sk-nope"))
check("key saved without approval -> 401", r.status_code == 401, r.get_json())
check("refusal explains what is needed",
      "administrator" in (r.get_json().get("error_message") or "").lower(),
      r.get_json())

# The regression: no API_KEY in the body, only a session token.
captured.clear()
r = con.post(ROUTES["MODELS"], json={"session_token": member["session_token"]})
body = r.get_json()
check("models route returns 200 with no pasted key", r.status_code == 200, body)
check("route used the SAVED key",
      (captured.get("headers") or {}).get("Authorization") == "Bearer " + SAVED_KEY,
      repr(captured.get("headers")))
check("models listed, chat models only",
      body.get("models") == ["gpt-4o", "gpt-4o-mini"], body)
check("provider reported back", body.get("provider") == "openai", body)

# A freshly pasted key still wins over the stored one.
captured.clear()
r = con.post(ROUTES["MODELS"], json=dict(member_body, API_KEY="sk-pasted-XYZ"))
check("pasted key takes precedence",
      (captured.get("headers") or {}).get("Authorization") == "Bearer sk-pasted-XYZ",
      repr(captured.get("headers")))

# Reading settings needs no approval; only changing them does.
r = con.post(ROUTES["SETTINGS"], json=member_body)
check("settings can be read without approval", r.status_code == 200, r.get_json())

# No key anywhere -> a clear 400, not a crash.
con.post(ROUTES["EMPLOYEE"], json={"method": "add", "Parent_id": parent_id,
                                      "username": "nokey", "password": "Passw0rd!",
                                      "token": admin_token})
r2 = con.post(ROUTES["EMPLOYEE_LOGIN"], json={"Parent_id": parent_id,
                                                 "username": "nokey", "password": "Passw0rd!"})
tk = r2.get_json()["session_token"]
r = con.post(ROUTES["MODELS"], json={"session_token": tk})
check("no key anywhere -> 400", r.status_code == 400, r.get_json())

# Anonymous callers are still refused.
r = con.post(ROUTES["MODELS"], json={})
check("anonymous refused", r.status_code == 401, r.get_json())

r = con.post(ROUTES["PROVIDERS"], json={})
check("anonymous cannot list providers", r.status_code == 401, r.get_json())

r = con.post(ROUTES["PROVIDERS"], json=member_body)
names = [p["key"] for p in r.get_json().get("providers", [])]
check("provider list is offered", r.status_code == 200 and "auto" in names, r.get_json())
check("gemini is offered", "gemini" in names, names)
check("groq is offered", "groq" in names, names)

# A member's own session may not quietly change policy.
r = con.post(ROUTES["SETTINGS"], json=dict(member_body, check1=False))
check("turning a check off needs approval", r.status_code == 401, r.get_json())

# Invalid addresses are refused before any provider handler sees a credential.
for base in ("http://169.254.169.254", "file:///not-opened", "http://[::ffff:169.254.169.254]/"):
    captured.clear()
    r = con.post(ROUTES["MODELS"], json=dict(member_body, provider="openai", API_BASE=base))
    check("named provider cannot skip URL validation: " + base, r.status_code == 400 and not captured)

con.post(ROUTES["SETTINGS"], json=dict(member_body, PROVIDER="openai", admin_token=admin_token))
for change in ({"API_BASE": "https://other.invalid"}, {"provider": "anthropic"}, {"provider": "auto"}):
    captured.clear()
    r = con.post(ROUTES["MODELS"], json=dict(member_body, **change))
    check("saved key bound to destination " + str(change), r.status_code == 403 and not captured)

token = con.post(ROUTES["ADMIN_APPROVE"], json={"username": "tester", "password": "test-pw-123"}).json["admin_token"]
body = dict(member_body, API_BASE="https://openai.com.invalid", admin_token=token)
check("one approved alternative HTTPS destination", con.post(ROUTES["MODELS"], json=body).status_code == 200)
captured.clear()
check("discovery approval cannot be replayed", con.post(ROUTES["MODELS"], json=body).status_code == 401 and not captured)
check("even a session cannot send a saved key to a new HTTP base", con.post(ROUTES["MODELS"],
      json=dict(member_body, API_BASE="http://other.invalid", admin_token=admin_token)).status_code == 403)
os.unlink(DB + ".key")
os.unlink(DB)
failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
