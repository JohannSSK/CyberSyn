#!/usr/bin/env python3
"""Model discovery: does the route use the key already saved for the member?

The bug this guards: /api/admin/employee/models demanded a freshly pasted
API_KEY, but the settings field only ever holds a mask ("****abcd"), so the
list could never be refreshed once a key had been saved. The route now falls
back to the member's stored key.

    python3 tools/test_models.py
"""
import os, sys, tempfile

DB = tempfile.mktemp(suffix=".db")
os.environ["CYBERSYN_DB_FILE"] = DB
sys.path.insert(0, "src")

from app import create_app
import db as db_module

db_module.seed()   # creates admin johann / admin_secret_123
app = create_app()
con = app.test_client()

captured = {}
import routes.chat_api  # noqa: F401  (registered below)

# Stub the outbound call so we can see which key the route actually used.
import models_route
def fake_openai(key):
    captured["key"] = key
    return ["gpt-4o", "gpt-4o-mini"]
models_route.openai_models = fake_openai

results = []
def check(name, ok, extra=""):
    results.append((name, ok, extra))
    print(("  PASS  " if ok else "  FAIL  ") + name + (f" -> {extra}" if extra and not ok else ""))

r = con.post("/api/admin/login", json={"username": "johann", "password": "admin_secret_123"})
check("admin signs in", r.status_code == 200, r.get_json())
admin = r.get_json()
admin_token, parent_id = admin["session_token"], int(admin["Parent_id"])

r = con.post("/api/admin/employee", json={"method": "add", "Parent_id": parent_id,
                                          "username": "mia", "password": "Passw0rd!"})
check("member created", r.status_code in (200, 201), r.get_json())

r = con.post("/api/admin/employee/login", json={"Parent_id": parent_id,
                                                "username": "mia", "password": "Passw0rd!"})
check("member signs in", r.status_code == 200, r.get_json())
member = r.get_json()

SAVED_KEY = "sk-saved-key-ABCD"
member_body = {"session_token": member["session_token"],
               "Parent_id": parent_id, "Employee_id": member["Employee_id"]}
r = con.post("/api/admin/employee/settings", json=dict(member_body, API_KEY=SAVED_KEY))
check("key saved", r.status_code == 200, r.get_json())

# The regression: no API_KEY in the body, only a session token.
r = con.post("/api/admin/employee/models", json={"session_token": member["session_token"]})
body = r.get_json()
check("models route returns 200 with no pasted key", r.status_code == 200, body)
check("route used the SAVED key", captured.get("key") == SAVED_KEY, repr(captured.get("key")))
check("models listed", body.get("models") == ["gpt-4o", "gpt-4o-mini"], body)

# A freshly pasted key still wins over the stored one.
captured.clear()
r = con.post("/api/admin/employee/models", json=dict(member_body, API_KEY="sk-pasted-XYZ"))
check("pasted key takes precedence", captured.get("key") == "sk-pasted-XYZ", repr(captured.get("key")))

# No key anywhere -> a clear 400, not a crash.
con.post("/api/admin/employee", json={"method": "add", "Parent_id": parent_id,
                                      "username": "nokey", "password": "Passw0rd!"})
r2 = con.post("/api/admin/employee/login", json={"Parent_id": parent_id,
                                                 "username": "nokey", "password": "Passw0rd!"})
tk = r2.get_json()["session_token"]
r = con.post("/api/admin/employee/models", json={"session_token": tk})
check("no key anywhere -> 400", r.status_code == 400, r.get_json())

# Anonymous callers are still refused.
r = con.post("/api/admin/employee/models", json={})
check("anonymous refused", r.status_code == 401, r.get_json())

os.unlink(DB)
failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
