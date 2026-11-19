#!/usr/bin/env python3
"""End-to-end smoke test against a running CyberSyn instance.

Use a disposable database. The test creates accounts, checks authorization,
searches history, reads statistics, imports a synthetic discovery sample and loads pages. With a configured key it
also sends a prompt and edits/deletes the answer; without one it verifies the
no-key refusal. No provider or scanner is mocked by this script.

    python3 tools/smoke.py                     # http://127.0.0.1:5000
    python3 tools/smoke.py http://host:port
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


REGISTRY = json.loads((Path(__file__).resolve().parents[1] / "includes" / "constants.json").read_text())


def default_base():
    """The address the app listens on, from includes/constants.json."""
    host, port = REGISTRY["HOST"], REGISTRY["PORT"]
    # 0.0.0.0 is a bind address, not somewhere to connect to.
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    return f"http://{host}:{port}"


BASE = (sys.argv[1] if len(sys.argv) > 1 else default_base()).rstrip("/")

PASSED = []
FAILED = []


def call(path, payload):
    req = urllib.request.Request(
        BASE + REGISTRY["ROUTES"][path],
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, {"raw": body}


def check(label, condition, detail=""):
    if condition:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}  {detail}")


# The app ships with no accounts, so the test creates the one it needs.
# These are test fixtures for whatever database BASE points at — override
# them with the environment when running against a real one.
ADMIN_USER = os.environ.get("CYBERSYN_SMOKE_USER", "smoke_admin")
ADMIN_PASS = os.environ.get("CYBERSYN_SMOKE_PASSWORD", "Smoke-Test-Pw-123")


def main():
    print(f"CyberSyn smoke test against {BASE}\n")

    # ---- sign in -----------------------------------------------------
    # The app ships with no accounts, so the test creates its own rather
    # than depending on one having been seeded by hand.
    status, admin = call("ADMIN_LOGIN",
                         {"username": ADMIN_USER, "password": ADMIN_PASS})
    if not admin.get("success"):
        added = call("ADMIN", {"method": "add", "username": ADMIN_USER,
                                    "password": ADMIN_PASS})
        status, admin = call("ADMIN_LOGIN",
                             {"username": ADMIN_USER, "password": ADMIN_PASS})
        if not admin.get("success"):
            print(f"  note: {ADMIN_USER} exists with a different password. "
                  f"Set CYBERSYN_SMOKE_USER / CYBERSYN_SMOKE_PASSWORD, or "
                  f"point BASE at a fresh database. ({added})")
    check("admin signs in", status == 200 and admin.get("success"), admin)
    if not admin.get("success"):
        return report()
    admin_token = admin["session_token"]
    parent_id = int(admin["Parent_id"])

    name = "smoke_user"
    call("EMPLOYEE",
         {"method": "remove", "Parent_id": parent_id, "username": name,
          "admin_password": ADMIN_PASS, "token": admin_token})
    status, _ = call("EMPLOYEE",
                     {"method": "add", "Parent_id": parent_id, "username": name,
                      "password": "Passw0rd!", "token": admin_token})
    check("team member added", status in (200, 201), status)

    status, login = call("EMPLOYEE_LOGIN",
                         {"workspace": ADMIN_USER, "username": name, "password": "Passw0rd!"})
    check("member signs in directly by workspace and gets a scoped session",
          status == 200 and login.get("Parent_id") == str(parent_id) and bool(login.get("session_token")), login)
    if not login.get("session_token"):
        return report()
    member_token = login["session_token"]
    employee_id = int(login["Employee_id"])

    def member(path, **payload):
        payload.setdefault("Parent_id", parent_id)
        payload.setdefault("Employee_id", employee_id)
        payload.setdefault("session_token", member_token)
        return call(path, payload)

    # ---- settings ----------------------------------------------------
    # Changing policy is an administrator action now, so the write carries
    # the administrator's approval; the read does not need one.
    status, grant = call("ADMIN_APPROVE", {"username": ADMIN_USER, "password": ADMIN_PASS, "scope": "once"})
    check("administrator approves once", status == 200)
    status, settings = member("SETTINGS",
                              MODEL_NAME="gpt-4o-mini", action_check1="warn", admin_token=grant.get("admin_token"))
    check("settings expose the action and its legacy flag", status == 200 and settings.get("check1") is True and
          settings.get("action_check1") == "warn", settings)
    check("api key never returned in the clear",
          settings.get("API_KEY") == "" and "API_KEY_MASK" in settings, settings)

    # ---- a clean message ---------------------------------------------
    status, chat = member("CHAT",
                          prompt="What is the capital of Greece?")
    if chat.get("error_message") == "No API_KEY provided.":
        # Correct behaviour with no key configured: the guard fires first.
        check("message refuses to send without a key", True)
        chat_id = None
    elif status == 502:
        print("  SKIP  sending a message (no AI provider reachable)")
        chat_id = None
    else:
        check("message accepted", status == 200 and not chat.get("error"), chat)
        chat_id = chat.get("chat_id")

    # ---- search -------------------------------------------------------
    status, found = member("CHATS_SEARCH", query="capital")
    check("chat search works", status == 200 and "results" in found, found)

    # ---- per-message edit / delete ------------------------------------
    if chat_id:
        _, opened = member("CHATS_OPEN", chat_id=chat_id)
        messages = (opened.get("chat") or {}).get("messages") or []
        check("chat reopens with messages", bool(messages), opened)
        if messages:
            mid = messages[0].get("id")
            status, edited = member("MESSAGE_EDIT",
                                    chat_id=chat_id, message_id=mid,
                                    text="What is the capital of France?")
            check("a single message can be edited",
                  status == 200 and bool(edited.get("messages")), edited)
            status, removed = member("MESSAGE_DELETE",
                                     chat_id=chat_id, message_id=mid)
            check("a single message can be deleted",
                  status == 200 and "messages" in removed, removed)

    # ---- photo OCR route ----------------------------------------------
    import base64
    import struct
    import zlib

    def _png_chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)
    raw_scanlines = b"\x00" + b"\xff" * (8 * 3)
    tiny_png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw_scanlines * 8))
        + _png_chunk(b"IEND", b"")
    )
    status, photo_res = member("CHAT_PHOTO", photo=base64.b64encode(tiny_png).decode("ascii"))
    check("photo upload rejects blank image with exact no-text message",
          status == 400 and photo_res.get("error_code") == "no_photo_text" and
          photo_res.get("error_message") == "There's no text to parse in this prompt.",
          (status, photo_res))

    # ---- authorisation still holds ------------------------------------
    status, _ = call("CHATS",
                     {"Parent_id": parent_id, "Employee_id": employee_id})
    check("history still refuses an anonymous caller", status == 401, status)

    status, _ = call("CHAT",
                     {"Parent_id": parent_id, "Employee_id": employee_id,
                      "prompt": "hello", "bypass": True,
                      "session_token": member_token})
    check("override still refuses a member token", status == 401, status)

    status, _ = call("SETTINGS",
                     {"Parent_id": parent_id, "Employee_id": employee_id,
                      "check1": False})
    check("settings still refuse an anonymous caller", status == 401, status)

    # ---- statistics ---------------------------------------------------
    status, stats = call("TEAM", {"token": admin_token})
    check("statistics load for the administrator",
          status == 200 and not stats.get("error"), stats)
    if status == 200:
        check("statistics carry a per-day trend", len(stats.get("trend", [])) > 0)
        check("statistics carry a timestamped timeline",
              "timeline" in stats, list(stats)[:8])
        check("statistics refuse a non-administrator",
              call("TEAM", {"token": member_token})[0] == 401)
        check("member trends are per member",
              all("trend" in m for m in stats.get("members", [])))

    # ---- offline, synthetic Shadow AI discovery -------------------------
    target = {"Parent_id": parent_id}
    status, discovery = call("SHADOW_AI", dict(target, token=admin_token))
    check("Shadow AI inventory loads for the workspace", status == 200 and len(discovery.get("inventory", [])) >= 16)
    status, page = call("ADMIN_APPROVE", dict(target, username=ADMIN_USER, password=ADMIN_PASS, scope="page"))
    page_token = page.get("admin_token")
    check("page approval can read discovery but cannot import", status == 200 and
          call("SHADOW_AI", dict(target, token=page_token))[0] == 200 and
          call("SHADOW_AI_IMPORT", dict(target, admin_token=page_token, sample=True))[0] == 401)
    status, imported = call("SHADOW_AI_IMPORT", dict(target, admin_token=admin_token, sample=True))
    check("sample import returns both detected and ignored counts", status == 200 and
          imported.get("ai_events_added", 0) > 0 and imported.get("non_ai_ignored", 0) > 0, imported)
    status, sales = call("SHADOW_AI", dict(target, token=admin_token, days=7, team="Sales", status="unapproved", data_signal="client_data"))
    check("filtered sample shows Sales client-data events to unapproved AI", status == 200 and
          sales.get("summary", {}).get("client_data_to_unapproved", 0) > 0)
    status, cleared = call("SHADOW_AI_IMPORT", dict(target, admin_token=admin_token, clear=True))
    check("clear removes only the discovery records", status == 200 and cleared.get("events_cleared", 0) > 0 and
          cleared.get("summary", {}).get("total_events") == 0, cleared)

    # ---- page routes ---------------------------------------------------
    print()
    for path in ("/", "/workspace", "/profile", "/settings", "/stats",
                 "/team", "/shadow-ai", "/help"):
        try:
            with urllib.request.urlopen(BASE + path, timeout=30) as resp:
                check(f"page {path} renders", resp.status == 200, resp.status)
        except Exception as exc:
            check(f"page {path} renders", False, exc)

    return report()


def report():
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("Failed:")
        for name in FAILED:
            print("  -", name)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
