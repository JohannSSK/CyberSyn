#!/usr/bin/env python3
"""Security boundaries and migrations, using real HTTP requests to a throwaway SQLite gateway."""

import contextlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
TMP = tempfile.TemporaryDirectory()
os.environ.update(CYBERSYN_DB_FILE=str(Path(TMP.name) / "test.db"), CYBERSYN_KEY_FILE=str(Path(TMP.name) / "keys/key"))
import admin_session
import ai_client
import auth
import chat_store
import config
import db
import gunicorn_conf
import rate_limit
import secret_store
from app import app
from scanning import MAX_SCREEN_BUDGET
from config import DB_FILE, ROUTES
from errors import ApiError, ChatError
from routes import chat_api

CREDENTIALS = {"username": "owner", "password": "  Owner password 123  "}
PW = "  Staff 123  "
HEADERS = {"X-CyberSyn-Request": "1", "X-CyberSyn-Session": "cookie"}


class Gateway(unittest.TestCase):
    def setUp(self):
        rate_limit.reset()
        self.api = app.test_client(use_cookies=False)
        self.browser = app.test_client()
        with contextlib.closing(db.connect()) as con, con:
            for table in ("ADMINS", "EMPLOYEES", "SETTINGS", "ADMIN_SESSIONS", "EMPLOYEE_SESSIONS", "CHATS"):
                con.execute(f"DELETE FROM {table}")
        r = self.post("ADMIN", method="add", **CREDENTIALS)
        self.assertEqual(r.status_code, 201, r.json)
        self.pid, self.admin = int(r.json["Parent_id"]), r.json["session_token"]
        self.eid = self.add("staff")
        r = self.post("EMPLOYEE_LOGIN", Parent_id=self.pid, username="staff", password=PW)
        self.ids = {"Parent_id": self.pid, "Employee_id": self.eid, "session_token": r.json["session_token"]}

    def post(self, route, **body):
        return self.api.post(ROUTES[route], json=body)

    def add(self, username):
        r = self.post("EMPLOYEE", method="add", token=self.admin, Parent_id=self.pid, username=username, password=PW)
        self.assertEqual(r.status_code, 201, r.json)
        return int(r.json["Employee_id"])

    def grant(self, scope="once"):
        return self.post("ADMIN_APPROVE", scope=scope, **CREDENTIALS).json["admin_token"]

    def edit(self, **changes):
        return self.post("SETTINGS", **dict(self.ids, **changes))

    def browse(self, route, body, **kwargs):
        return self.browser.post(ROUTES[route], json=body, headers=HEADERS, **kwargs)

    def test_cookie_transition_csrf_and_logout(self):
        with patch.dict(os.environ, CYBERSYN_COOKIE_SECURE="1"):
            login = self.browse("ADMIN_LOGIN", CREDENTIALS)
        cookie = login.headers["Set-Cookie"]
        self.assertTrue(all(flag in cookie for flag in ("HttpOnly", "SameSite=Lax", "Secure", "Path=/", "Max-Age=604800")))
        self.assertNotIn("session_token", login.json)
        admin = self.browser.get_cookie(auth.ADMIN_COOKIE).value
        self.assertEqual(self.browse("ADMIN_SESSION", {}).status_code, 200)
        self.assertEqual(self.browser.post(ROUTES["ADMIN_SESSION"], json={}).status_code, 403)
        cross = dict(HEADERS, Origin="https://other.invalid")
        self.assertEqual(self.browser.post(ROUTES["ADMIN_LOGOUT"], json={}, headers=cross).status_code, 403)
        member = self.browse("EMPLOYEE_LOGIN", dict(Parent_id=self.pid, username="staff", password=PW))
        self.assertNotIn("session_token", member.json)
        self.assertIsNone(self.browser.get_cookie(auth.ADMIN_COOKIE))
        self.assertIsNone(auth.admin_from_token(DB_FILE, admin))
        self.assertTrue(self.browser.get_cookie(auth.MEMBER_COOKIE).http_only)
        ids = dict(Parent_id=self.pid, Employee_id=self.eid)
        self.assertEqual(self.browse("CHATS", ids).status_code, 200)
        self.assertEqual(self.browser.post(ROUTES["CHATS"], json=ids).status_code, 403)
        self.assertEqual(self.browser.post(ROUTES["CHATS"], json=ids, headers=cross).status_code, 403)
        self.assertEqual(self.browse("EMPLOYEE_LOGOUT", {}).status_code, 200)
        self.assertIsNone(self.browser.get_cookie(auth.MEMBER_COOKIE))
        self.assertEqual(self.browse("CHATS", ids).status_code, 401)

    def test_approval_pools_expiry_scope_and_atomic_once(self):
        for i in range(30):
            once = admin_session.create_session(DB_FILE, self.pid, "approval_once")
        self.assertIsNotNone(auth.admin_from_token(DB_FILE, self.admin))
        with contextlib.closing(db.connect()) as con:
            rows = con.execute("SELECT expires_at FROM ADMIN_SESSIONS WHERE purpose='approval_once'").fetchall()
            self.assertEqual(len(rows), 20)
            self.assertLessEqual(datetime.fromisoformat(rows[-1][0]), datetime.now(timezone.utc) + timedelta(minutes=5))
        with ThreadPoolExecutor(2) as pool:
            status = list(pool.map(lambda _: self.edit(admin_token=once, block_code=True).status_code, range(2)))
        self.assertEqual(sorted(status), [200, 401])
        page = self.browse("ADMIN_APPROVE", dict(CREDENTIALS, scope="page"))
        self.assertNotIn("admin_token", page.json)
        token = self.browser.get_cookie(auth.PAGE_COOKIE).value
        self.assertIsNone(self.browser.get_cookie(auth.ADMIN_COOKIE))
        self.assertTrue(self.browse("OVERRIDE_CHECK", {"Parent_id": self.pid}).json["allowed"])
        self.assertEqual(self.browse("TEAM", {}).status_code, 200)
        self.assertEqual(self.edit(admin_token=token, check2=False).status_code, 401)
        self.assertEqual(self.post("ADMIN_SESSION", token=token).status_code, 401)
        self.assertEqual(self.post("TEAM", token=self.grant()).status_code, 401)
        self.browse("ADMIN_LOGOUT", {"scope": "page"})
        self.assertFalse(self.post("OVERRIDE_CHECK", Parent_id=self.pid, admin_token=token).json["allowed"])
        expired = self.grant("page")
        with contextlib.closing(db.connect()) as con, con:
            when = con.execute("SELECT expires_at FROM ADMIN_SESSIONS WHERE token_hash=?", (auth._hash(expired),)).fetchone()[0]
            self.assertLessEqual(datetime.fromisoformat(when), datetime.now(timezone.utc) + timedelta(minutes=15))
            con.execute("UPDATE ADMIN_SESSIONS SET expires_at=? WHERE token_hash=?", ("2000-01-01T00:00:00+00:00", auth._hash(expired)))
        self.assertEqual(self.post("TEAM", token=expired).status_code, 401)

    def unlock_owner_page(self):
        r = self.browse("ADMIN_APPROVE", dict(CREDENTIALS, scope="page"))
        self.assertEqual(r.status_code, 200, r.json)
        return self.browser.get_cookie(auth.PAGE_COOKIE).value

    def assert_workspace(self, username, members, **body):
        # /stats and the removal picker use different endpoints.
        for route in ("TEAM", "TEAM_LIST"):
            with self.subTest(route=route):
                r = self.browse(route, body)
                self.assertEqual(r.status_code, 200, r.json)
                self.assertEqual([m["username"] for m in r.json["members"]], members)
                if route == "TEAM":
                    self.assertEqual(r.json["admin"], username)

    def test_member_page_to_different_admin_login(self):
        other = dict(username="second", password=PW)
        r = self.post("ADMIN", method="add", token=self.admin, **other)
        self.assertEqual(r.status_code, 201, r.json)
        added = self.post("EMPLOYEE", method="add", token=r.json["session_token"], Parent_id=r.json["Parent_id"],
                          username="colleague", password=PW)
        self.assertEqual(added.status_code, 201, added.json)
        self.assertEqual(self.browse("EMPLOYEE_LOGIN", dict(Parent_id=self.pid, username="staff", password=PW)).status_code, 200)
        grant = self.unlock_owner_page()
        self.assertEqual(self.browser.post(ROUTES["TEAM_LIST"], json={}).status_code, 403)
        self.assertEqual(self.browse("ADMIN_LOGIN", dict(other, password="wrong")).status_code, 401)
        self.assertEqual(self.browser.get_cookie(auth.PAGE_COOKIE).value, grant)
        self.assert_workspace("owner", ["staff"])
        self.assertEqual(self.browse("ADMIN_LOGIN", other).status_code, 200)
        self.assertIsNone(self.browser.get_cookie(auth.PAGE_COOKIE))
        self.assertEqual(self.post("TEAM", token=grant).status_code, 401)
        self.assert_workspace("second", ["colleague"])

    def test_primary_cookie_selects_workspace_when_both_grants_are_live(self):
        r = self.browse("ADMIN", dict(method="add", token=self.admin, username="second", password=PW))
        self.assertEqual(r.status_code, 201, r.json)
        # Issue a live page grant *after* primary login: clearing it at login
        # alone cannot make this test pass.
        page = self.unlock_owner_page()
        self.assert_workspace("second", [])
        self.assertFalse(self.browse("OVERRIDE_CHECK", {"Parent_id": self.pid}).json["allowed"])
        self.assert_workspace("owner", ["staff"], token=page)  # explicit credential still wins
        for route in ("TEAM", "TEAM_LIST"):
            self.assertEqual(self.browse(route, {"token": "invalid"}).status_code, 401)
            self.assertEqual(self.browser.post(ROUTES[route], json={}).status_code, 403)
            cross = dict(HEADERS, Origin="https://other.invalid")
            self.assertEqual(self.browser.post(ROUTES[route], json={}, headers=cross).status_code, 403)
        self.browser.set_cookie(auth.ADMIN_COOKIE, "invalid")
        self.assertEqual(self.browse("TEAM", {}).status_code, 401)  # don't switch identities on validation failure

    def test_fresh_login_after_rotation_with_stale_page_cookie(self):
        page = self.unlock_owner_page()
        new = dict(CREDENTIALS, password="Replacement 321")
        # Rotate in a separate client so the first browser still has the old cookie.
        r = self.post("ADMIN_PASSWORD", token=self.admin, current_password=CREDENTIALS["password"], new_password=new["password"])
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(self.browse("TEAM", {}).status_code, 401)
        self.assertEqual(self.browse("ADMIN_LOGIN", new).status_code, 200)
        self.assertIsNone(self.browser.get_cookie(auth.PAGE_COOKIE))
        self.assert_workspace("owner", ["staff"])
        self.browser.set_cookie(auth.PAGE_COOKIE, page)  # even a retained stale cookie can't mask the new login
        self.assert_workspace("owner", ["staff"])

    def test_create_and_remove_retire_only_the_presented_page_grant(self):
        independent = self.grant("page")
        other = dict(username="second", password=PW)
        for method, status in (("add", 201), ("remove", 200)):
            page = self.unlock_owner_page()
            r = self.browse("ADMIN", dict(other, method=method, token=self.admin))
            self.assertEqual(r.status_code, status, r.json)
            self.assertIsNone(self.browser.get_cookie(auth.PAGE_COOKIE))
            self.assertEqual(self.post("TEAM", token=page).status_code, 401)
            self.assertEqual(self.post("TEAM", token=independent).status_code, 200)
        self.assertEqual(self.post("ADMIN_SESSION", token=self.admin).status_code, 200)

    def test_source_policy_is_individual_inherited_only_by_new_members(self):
        other = self.add("before")
        self.assertFalse(self.edit().json["block_code"])
        for extra in ({}, {"block_code": True}):
            self.assertEqual(self.edit(Employee_id=0, **extra).status_code, 401)
        for value in (False, -1, "bad", 0.0):
            self.assertEqual(self.edit(Employee_id=value).status_code, 400)
        updated = self.edit(admin_token=self.grant(), block_code=True, check1=False, check2=False,
                            check3=False, API_KEY="fixture", also_default=True)
        self.assertTrue(updated.json["block_code"])
        for eid, expected in ((other, False), (0, True), (self.add("after"), True)):
            self.assertEqual(self.edit(Employee_id=eid, admin_token=self.admin).json["block_code"], expected)
        # Real context scanner + saved DB policy; no external model or key needed.
        with patch.object(chat_api, "complete", return_value="reply") as complete:
            code = "def total(items):\n    return sum(items)"
            got = self.post("CHAT", **self.ids, prompt=code, block_code=False)
            self.assertEqual(got.json["block_info"]["main_cause"], "computer source code")
            complete.assert_not_called()
            self.edit(admin_token=self.grant(), block_code=False)
            got = self.post("CHAT", **self.ids, prompt=code)
            self.assertEqual(got.json["reply_message"], "reply")
            self.edit(admin_token=self.grant(), block_code=True)
            regen = self.post("CHAT_REGENERATE", **self.ids, chat_id=got.json["chat_id"], message_id=got.json["message_id"])
            self.assertTrue(regen.json["blocked"])
            self.assertEqual(complete.call_count, 1)

    def test_default_connection_keeps_the_key_and_destination_together(self):
        self.edit(Employee_id=0, admin_token=self.admin, PROVIDER="groq", API_KEY="original-default")
        self.edit(admin_token=self.admin, PROVIDER="custom", API_KEY="member-fixture",
                  API_BASE="https://127.0.0.1/member/v1")
        # As in Settings, save a connection without retyping its saved secret.
        self.edit(admin_token=self.grant(), MODEL_NAME="openai/local-model", also_default=True)
        eid = self.add("later")
        saved = self.edit(admin_token=self.admin, Employee_id=eid).json
        self.assertEqual((saved["PROVIDER"], saved["API_BASE"], saved["API_KEY_MASK"]),
                         ("custom", "https://127.0.0.1/member/v1", "****ture"))
        # A read/repair of an existing member must not silently import a later template.
        with contextlib.closing(db.connect()) as con, con:
            con.execute("DELETE FROM SETTINGS WHERE Parent_id=? AND Employee_id=?", (self.pid, self.eid))
        self.assertFalse(self.edit().json["API_KEY_MASK"])

    def test_blocks_and_overrides_never_log_secrets(self):
        self.edit(admin_token=self.admin, API_KEY="fixture")
        secret = "sk-proj-SYNTHETIC-TEST-ONLY"
        info = {"stage": "check1", "main_cause": "API_KEY", "line": 1, "snippet": secret, "matches": []}
        with patch.object(config, "LOG_PROMPT_PREVIEW", True), patch.object(chat_api, "screen", return_value=info), patch.object(chat_api, "complete", return_value="ok"):
            self.assertTrue(self.post("CHAT", **self.ids, prompt=secret).json["blocked"])
            once = self.grant()
            send = dict(self.ids, bypass=True, admin_token=once, prompt=secret)
            self.assertEqual(self.post("CHAT", **send).json["reply_message"], "ok")
            self.assertEqual(self.post("CHAT", **send).status_code, 401)
        with contextlib.closing(db.connect()) as con:
            for table in ("BLOCK_LOG", "ACTIVITY_LOG"):
                rows = con.execute(f"SELECT * FROM {table} WHERE Parent_id=?", (self.pid,)).fetchall()
                self.assertNotIn(secret, repr([tuple(row) for row in rows]))
            self.assertIn("approved by owner", con.execute("SELECT detail FROM ACTIVITY_LOG WHERE Parent_id=? AND kind='override'", (self.pid,)).fetchone()[0])
        timeline = self.post("TEAM", token=self.admin).json["timeline"]
        self.assertEqual([row["detail"] for row in timeline if row["kind"] == "override"], ["approved by owner"])
        self.assertEqual([row["detail"] for row in timeline if row["kind"] == "blocked"], ["API_KEY"])

    def test_limits_and_prompt_free_activity(self):
        self.edit(admin_token=self.admin, API_KEY="fixture", check1=False, check2=False, check3=False)
        with patch.object(chat_api, "complete", return_value="ok"):
            self.assertEqual(self.post("CHAT", **self.ids, prompt="x"*(config.MAX_PROMPT_CHARS+1)).status_code, 400)
            reply = self.post("CHAT", **self.ids, prompt="sensitive ordinary text").json
            ids = dict(self.ids, chat_id=reply["chat_id"], message_id=reply["message_id"])
            self.assertEqual(self.post("MESSAGE_EDIT", **ids, text="sensitive edit").status_code, 200)
            self.assertEqual(self.post("CHAT_REGENERATE", **ids).status_code, 200)
            self.assertEqual(self.post("MESSAGE_EDIT", **ids, text="x"*(config.MAX_PROMPT_CHARS+1)).status_code, 400)
            with patch.object(chat_api, "MAX_PROMPT_CHARS", 4):
                self.assertEqual(self.post("CHAT_REGENERATE", **ids).status_code, 400)
        for cid in (True, 0, -1, "abc"):
            self.assertEqual(self.post("CHATS_OPEN", **self.ids, chat_id=cid).status_code, 400)
        with contextlib.closing(db.connect()) as con:
            rows = con.execute("SELECT detail FROM ACTIVITY_LOG WHERE Parent_id=?", (self.pid,)).fetchall()
            self.assertNotIn("sensitive", str([r[0] for r in rows]))
        self.assertEqual(self.post("ADMIN_LOGIN", username="x", password="x"*257).status_code, 400)
        self.assertEqual(self.post("ADMIN_LOGIN", username="x"*65, password="x").status_code, 400)
        self.assertEqual(self.post("ADMIN_LOGIN", username="x", password="x"*(256*1024)).status_code, 413)

    def test_password_rotation_and_deletion(self):
        self.assertEqual(self.post("EMPLOYEE", token=self.admin, method="add", Parent_id=self.pid,
                                   username="weak", password="weak").status_code, 400)
        password = "  Replacement 321  "
        self.assertEqual(self.post("EMPLOYEE_ACCOUNT", **self.ids, action="password", current_password=PW, new_password="weak").status_code, 400)
        changed = self.post("EMPLOYEE_ACCOUNT", **self.ids, action="password", current_password=PW, new_password=password)
        fresh = changed.json["session_token"]
        self.assertIn("HttpOnly", changed.headers["Set-Cookie"])
        self.assertIsNone(auth.member_from_token(DB_FILE, self.ids["session_token"]))
        self.assertIsNotNone(auth.member_from_token(DB_FILE, fresh))
        self.assertEqual(self.post("EMPLOYEE_LOGIN", Parent_id=self.pid, username="staff", password=password).status_code, 200)
        chat_store.save_exchange(DB_FILE, self.pid, self.eid, None, "hello", "ok")
        offboard = dict(method="remove", Parent_id=self.pid, username="staff", token=self.admin)
        self.assertEqual(self.post("EMPLOYEE", **offboard, admin_password=password).status_code, 401)
        self.assertEqual(self.post("EMPLOYEE", **offboard, admin_password=CREDENTIALS['password']).status_code, 200)
        self.assertIsNone(auth.member_from_token(DB_FILE, fresh))
        with contextlib.closing(db.connect()) as con:
            for table in ("SETTINGS", "CHATS", "EMPLOYEE_SESSIONS"):
                self.assertFalse(con.execute(f"SELECT 1 FROM {table} WHERE Parent_id=? AND Employee_id=?", (self.pid, self.eid)).fetchall())
        other = self.add("newstaff")
        chat_store.save_exchange(DB_FILE, self.pid, other, None, "hi", "ok")
        self.post("EMPLOYEE_LOGIN", Parent_id=self.pid, username="newstaff", password=PW)
        page = self.grant("page")
        self.assertEqual(self.post("ADMIN_PASSWORD", token=self.grant(), current_password=CREDENTIALS['password'], new_password=password).status_code, 200)
        self.assertIsNone(auth.admin_from_token(DB_FILE, self.admin))
        self.assertEqual(self.post("TEAM", token=page).status_code, 401)
        self.assertEqual(self.post("ADMIN_LOGIN", username="owner", password=password).status_code, 200)
        self.assertEqual(self.post("ADMIN", method="remove", username="owner", password=password).status_code, 200)
        with contextlib.closing(db.connect()) as con:
            for table in ("SETTINGS", "EMPLOYEES", "ADMINS", "CHATS", "ADMIN_SESSIONS", "EMPLOYEE_SESSIONS"):
                self.assertEqual(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0, table)
            self.assertTrue(con.execute("SELECT 1 FROM ACTIVITY_LOG WHERE Parent_id=?", (self.pid,)).fetchall())

    def test_limit_and_live_member_lookup(self):
        tokens = [auth.create_employee_session(DB_FILE, self.pid, self.eid) for _ in range(15)]
        self.assertIsNone(auth.member_from_token(DB_FILE, tokens[0]))
        self.assertTrue(auth.member_from_token(DB_FILE, tokens[-1]))
        with contextlib.closing(db.connect()) as con, con:
            con.execute("DELETE FROM EMPLOYEES WHERE id=?", (self.eid,))
        self.assertEqual(self.post("MODELS", session_token=tokens[-1]).status_code, 401)
        self.assertEqual(self.post("CHATS", **dict(self.ids, session_token=tokens[-1])).status_code, 401)

    def test_signup_guard_generic_refusals_and_rate_limit(self):
        extra = dict(method="add", username="another", password=PW)
        self.assertEqual(self.post("ADMIN", **extra).status_code, 403)
        self.assertEqual(self.post("ADMIN", **extra, token=self.admin).status_code, 201)
        self.assertEqual(self.post("ADMIN", **extra, token=self.admin).status_code, 409)
        for route in ("ADMIN_LOGIN", "ADMIN_APPROVE", "ADMIN"):
            responses = [self.post(route, method="remove", username=u, password="wrong") for u in ("owner", "absent")]
            self.assertEqual([r.status_code for r in responses], [401, 401])
            self.assertEqual(responses[0].json, responses[1].json)
        rate_limit.reset()
        for _ in range(10):
            self.assertEqual(self.post("ADMIN_APPROVE", username="owner", password="wrong").status_code, 401)
        limited = self.post("ADMIN_LOGIN", **CREDENTIALS)
        self.assertEqual(limited.status_code, 429)
        self.assertIn("Retry-After", limited.headers)
        self.assertFalse(limited.json["success"])

    def test_limiter_counts_parallel_attempts_and_does_not_trust_headers(self):
        def attempt(n):
            client = app.test_client(use_cookies=False)
            return client.post(ROUTES["ADMIN_LOGIN"], json={"username": f"u{n}", "password": "incorrect"},
                               headers={"X-Forwarded-For": f"192.0.2.{n+1}"}).status_code
        with patch('routes.admin_api.credentials_match', return_value=False), ThreadPoolExecutor(6) as pool:
            codes = list(pool.map(attempt, range(14)))
            self.assertEqual((codes.count(401), codes.count(429)), (10,4))
            with patch.dict(os.environ, CYBERSYN_TRUST_PROXY="1"):
                self.assertEqual(attempt(15), 401)

    def test_sqlite_seed_clear_and_atomic_updates(self):
        with contextlib.closing(db.connect()) as con:
            self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(con.execute("PRAGMA busy_timeout").fetchone()[0], 10000)
            self.assertEqual(con.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("INSERT INTO EMPLOYEES (Parent_id,username,password) VALUES (?,?,?)", (self.pid,"staff","fixture"))
        self.edit(API_BASE="http://127.0.0.1:11434/v1", API_KEY="tiny", admin_token=self.admin)
        self.assertEqual(self.edit().json["API_KEY_MASK"], "********")
        self.assertEqual(self.edit(CLEAR_API_KEY=True, admin_token=self.admin, API_BASE="").json["API_KEY_MASK"], "")
        self.assertEqual(self.edit().json["API_BASE"], "")
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertNotEqual(db.seed("seeded", "weak"), 0)
            self.assertEqual(db.seed("seeded", PW), 0)
            with contextlib.closing(db.connect()) as con, con:
                pid = con.execute("SELECT id FROM ADMINS WHERE username='seeded'").fetchone()[0]
                con.execute("DELETE FROM SETTINGS WHERE Parent_id=?", (pid,))
            self.assertEqual(db.seed("seeded"), 0)
        token = self.post("ADMIN_LOGIN", username="seeded", password=PW).json["session_token"]
        self.assertEqual(self.post("SETTINGS", Parent_id=pid, Employee_id=0, admin_token=token).status_code, 200)
        cid, entry = chat_store.save_exchange(DB_FILE, self.pid, self.eid, None, "first", "reply")
        args = (DB_FILE, self.pid, self.eid, cid)
        with ThreadPoolExecutor(8) as pool:
            work = [pool.submit(chat_store.save_exchange, *args, str(n), "ok") for n in range(16)]
            work += [pool.submit(chat_store.edit_message, *args, entry["id"], "edited"),
                     pool.submit(chat_store.replace_answer, *args, entry["id"], "new")]
            for f in work:
                self.assertIsNotNone(f.result())
        items = chat_store.get_chat(*args)["messages"]
        self.assertEqual((len(items), items[0]["prompt"], items[0]["answer"]), (17, "edited", "new"))
        chat_store.delete_chat(*args)
        self.assertEqual(chat_store.save_exchange(*args, "lost", "answer"), (None, None))

    def test_legacy_migrations_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            with contextlib.closing(db.connect(path)) as con, con:
                con.executescript("""
                    CREATE TABLE EMPLOYEES (id INTEGER PRIMARY KEY, Parent_id INTEGER, username TEXT,
                                            password TEXT, CHAT_LOGS TEXT DEFAULT '[]');
                    INSERT INTO EMPLOYEES(Parent_id,username,password) VALUES (1,'same','legacy'),(1,'same','legacy');
                    CREATE TABLE SETTINGS (Parent_id INTEGER, Employee_id INTEGER, check1 INTEGER, check2 INTEGER,
                                           check3 INTEGER, MODEL_NAME TEXT, API_KEY TEXT, PRIMARY KEY(Parent_id,Employee_id));
                    INSERT INTO SETTINGS VALUES (1,1,1,0,1,'old-model','');
                    CREATE TABLE ADMIN_SESSIONS(token_hash TEXT PRIMARY KEY, admin_id INTEGER, expires_at TEXT);
                    INSERT INTO ADMIN_SESSIONS VALUES ('old-digest',1,'2099-01-01T00:00:00+00:00');
                    CREATE TABLE DISCOVERY_EVENTS(id INTEGER PRIMARY KEY, Parent_id INTEGER, observed_at TEXT,
                        team TEXT, actor TEXT, host TEXT, tool_key TEXT, tool_name TEXT, method TEXT,
                        bytes_sent INTEGER, data_signal TEXT, imported_at TEXT);
                    INSERT INTO DISCOVERY_EVENTS VALUES (7,1,'2026-11-18','Sales','192.0.2.10',
                        'chat.deepseek.com','deepseek','DeepSeek','POST',4200,'client_data','2026-11-18');
                    CREATE TABLE ACTIVITY_LOG(kind TEXT, detail TEXT);
                    INSERT INTO ACTIVITY_LOG VALUES ('blocked','old private text'),('prompt','old private text'),('login',NULL);
                """)
            with patch.object(db, 'DB_FILE', path), self.assertLogs('db', level='WARNING') as warnings:
                db.init_db()
                db.check_schema()
            self.assertIn('Duplicate legacy member names', ' '.join(warnings.output))
            admin_session.init_table(path)
            admin_session.init_table(path)
            with contextlib.closing(db.connect(path)) as con, con:
                self.assertEqual(con.execute("SELECT purpose FROM ADMIN_SESSIONS").fetchone()[0], 'session')
                self.assertEqual(tuple(con.execute("SELECT block_code, check2, MODEL_NAME, PROVIDER, API_BASE FROM SETTINGS").fetchone()),
                                 (0, 0, 'old-model', 'auto', ''))
                self.assertEqual(con.execute("SELECT count(*) FROM ACTIVITY_LOG WHERE detail IS NULL").fetchone()[0], 3)
                self.assertEqual(con.execute("SELECT count(*) FROM EMPLOYEES").fetchone()[0], 2)
                con.execute("UPDATE EMPLOYEES SET username='unique' WHERE id=2")
                con.execute("INSERT INTO ACTIVITY_LOG VALUES ('blocked','safe category')")
            with patch.object(db, 'DB_FILE', path):
                db.init_db()
            with contextlib.closing(db.connect(path)) as con:
                self.assertEqual(con.execute("SELECT detail FROM ACTIVITY_LOG ORDER BY rowid DESC").fetchone()[0], 'safe category')
                self.assertEqual([tuple(r) for r in con.execute("SELECT id, is_sample, actor FROM DISCOVERY_EVENTS")],
                                 [(7, 0, '192.0.2.10')])
                with self.assertRaises(sqlite3.IntegrityError):
                    con.execute("UPDATE EMPLOYEES SET username='same' WHERE id=2")

    def test_a_draft_title_is_saved_only_with_the_first_successful_exchange(self):
        draft = {"prompt": "Ordinary fixture", "title": "  Team   review  "}
        with patch.object(chat_api, "complete", return_value="ok") as complete:
            no_key = self.post("CHAT", **self.ids, **draft)
            self.assertEqual((no_key.status_code, no_key.json["error_code"]), (400, "missing_api_key"))
            self.assertEqual(self.post("CHATS", **self.ids).json["chats"], [])
            complete.assert_not_called()
            self.edit(admin_token=self.admin, API_KEY="fixture", check1=False, check2=False, check3=False)
            for title in ([], "  ", None):
                self.assertEqual(self.post("CHAT", **self.ids, prompt=draft["prompt"], title=title).status_code, 400)
            complete.assert_not_called()
            result = self.post("CHAT", **self.ids, **draft)
            self.assertEqual(result.status_code, 200, result.json)
            self.assertEqual(complete.call_args.args[2], draft["prompt"])
            chat_id = result.json["chat_id"]
            result = self.post("CHAT", **self.ids, chat_id=chat_id, prompt="Another fixture", title="Not a rename")
            self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.post("CHATS", **self.ids).json["chats"][0]["title"], "Team review")
        self.assertEqual(self.post("CHATS_OPEN", **self.ids, chat_id=chat_id).json["chat"]["title"], "Team review")

    def test_conversation_context_is_opt_in_and_carries_only_sent_messages(self):
        self.edit(admin_token=self.admin, API_KEY="fixture", check1=False, check2=False, check3=False)
        with patch.object(chat_api, "complete", return_value="first answer") as complete:
            chat_id = self.post("CHAT", **self.ids, prompt="First question").json["chat_id"]
            self.assertEqual(complete.call_args.kwargs["history"], [])
        # The default stays singular: one message, this one only.
        with patch.object(chat_api, "complete", return_value="second answer") as complete:
            self.post("CHAT", **self.ids, chat_id=chat_id, prompt="Second question")
            self.assertEqual(complete.call_args.kwargs["history"], [])

        self.assertEqual(self.post("SETTINGS", **self.ids, CONTEXT_MESSAGES=2).status_code, 401)
        for bad in (21, -1, "many", True, 2.5):
            self.assertEqual(self.post("SETTINGS", **self.ids, CONTEXT_MESSAGES=bad, admin_token=self.admin).status_code, 400, bad)
        saved = self.post("SETTINGS", **self.ids, CONTEXT_MESSAGES=2, admin_token=self.admin)
        self.assertEqual((saved.status_code, saved.json["CONTEXT_MESSAGES"]), (200, 2))

        with patch.object(chat_api, "complete", return_value="third answer") as complete:
            third = self.post("CHAT", **self.ids, chat_id=chat_id, prompt="Third question").json
            # Only the most recent exchange, oldest first, then the new prompt.
            self.assertEqual(complete.call_args.kwargs["history"], [
                {"role": "user", "content": "Second question"},
                {"role": "assistant", "content": "second answer"}])

        # Regenerating an answer replays what came before it, never itself.
        with patch.object(chat_api, "complete", return_value="third answer") as complete:
            self.assertEqual(self.post("CHAT_REGENERATE", **self.ids, chat_id=chat_id,
                                       message_id=third["message_id"], prompt="Third question").status_code, 200)
            self.assertEqual(complete.call_args.kwargs["history"], [
                {"role": "user", "content": "Second question"},
                {"role": "assistant", "content": "second answer"}])

        self.edit(admin_token=self.admin, CONTEXT_MESSAGES=4, also_default=True)
        with patch.object(chat_api, "complete", return_value="fourth answer") as complete:
            self.post("CHAT", **self.ids, chat_id=chat_id, prompt="Fourth question")
            history = complete.call_args.kwargs["history"]
        self.assertEqual([item["content"] for item in history],
                         ["Second question", "second answer", "Third question", "third answer"])
        with contextlib.closing(db.connect()) as con:
            self.assertEqual(con.execute("SELECT CONTEXT_MESSAGES FROM SETTINGS WHERE Parent_id=? AND Employee_id=0",
                                         (self.pid,)).fetchone()[0], 4)

        # A prompt in another chat starts from nothing, whatever the setting says.
        with patch.object(chat_api, "complete", return_value="elsewhere") as complete:
            self.post("CHAT", **self.ids, prompt="Unrelated question")
            self.assertEqual(complete.call_args.kwargs["history"], [])

    def test_the_wire_ends_with_the_current_prompt_and_drops_junk(self):
        sent = {}

        class FakeClient:
            def completion(self, **kwargs):
                sent.clear()
                sent.update(kwargs)
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

        with patch.object(ai_client, "_client", return_value=FakeClient()):
            ai_client.complete("fixture", "gpt-4o-mini", "now", history=[
                {"role": "user", "content": "before"},
                {"role": "assistant", "content": "earlier reply"},
                {"role": "assistant", "content": ""},
                {"role": "system", "content": "not ours"},
                "not a message",
            ])
            self.assertEqual(sent["messages"], [
                {"role": "user", "content": "before"},
                {"role": "assistant", "content": "earlier reply"},
                {"role": "user", "content": "now"}])
            ai_client.complete("fixture", "gpt-4o-mini", "alone")
            # The default stays singular: one message, this one only.
            self.assertEqual(sent["messages"], [{"role": "user", "content": "alone"}])

        chat = {"messages": [{"id": "a", "prompt": "x" * 25000, "answer": "old"},
                             {"id": "b", "prompt": "short", "answer": "b"},
                             {"id": "c", "prompt": "unanswered", "answer": ""}]}
        self.assertEqual([m["content"] for m in chat_api._history(chat, None, 10)], ["short", "b"])
        self.assertEqual(len(chat_api._history(chat, None, 3)), 2)  # whole exchanges only
        self.assertEqual(chat_api._history(chat, None, 0), [])

    def test_deletion_during_completion_and_legacy_search_ids(self):
        self.edit(admin_token=self.admin, API_KEY="fixture", check1=False, check2=False, check3=False)
        args = (DB_FILE, self.pid, self.eid)
        cid, _ = chat_store.save_exchange(*args, None, "old", "ok")
        with contextlib.closing(db.connect()) as con, con:
            con.execute("UPDATE CHATS SET messages=? WHERE id=?", ('[{"prompt":"old text","answer":"ok"}]',cid))
        mid = self.post("CHATS_SEARCH", **self.ids, query="old").json["results"][0]["message_id"]
        self.assertEqual(self.post("CHATS_OPEN", **self.ids, chat_id=cid).json["chat"]["messages"][0]["id"], mid)
        for route in ("CHAT_REGENERATE", "CHAT"):
            with patch.object(chat_api, "complete", side_effect=lambda *a, **kw: chat_store.delete_chat(*args, cid) and "ok"):
                result = self.post(route, **self.ids, chat_id=cid, message_id=mid, prompt="more text")
                self.assertEqual(result.status_code, 404, result.json)
            cid, entry = chat_store.save_exchange(*args, None, "new text", "ok")
            mid = entry['id']
        self.assertEqual(len(chat_store.list_chats(*args)), 1)

    def test_ordinary_preview_is_explicit_and_errors_do_not_leak(self):
        self.edit(admin_token=self.admin, API_KEY="fixture", check1=False, check2=False, check3=False)
        text = "ordinary text " * 8
        with patch.object(config, "LOG_PROMPT_PREVIEW", True), patch.object(chat_api, "complete", return_value="ok"):
            reply = self.post("CHAT", **self.ids, prompt=text).json
            ids = dict(self.ids, chat_id=reply["chat_id"], message_id=reply["message_id"])
            self.post("MESSAGE_EDIT", **ids, text="updated ordinary text")
            self.post("CHAT_REGENERATE", **ids)
        with contextlib.closing(db.connect()) as con:
            details = dict(con.execute("SELECT kind,detail FROM ACTIVITY_LOG WHERE Parent_id=?", (self.pid,)))
            self.assertEqual(details["prompt"], text[:80])
            self.assertEqual(details["regenerated"], details["message_edited"])
            self.assertEqual(details["message_edited"], "updated ordinary text")
        with patch.object(chat_api, 'complete', side_effect=ValueError('private diagnostic')), self.assertLogs(app.logger, 'ERROR') as log:
            result = self.post("CHAT", **self.ids, prompt="ordinary")
        self.assertEqual(result.status_code, 500)
        self.assertNotIn('private diagnostic', str(result.json) + str(log.output))

    def test_completion_revalidates_legacy_base(self):
        import ai_client
        from types import SimpleNamespace
        from unittest.mock import Mock
        completion = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]))
        with patch.dict(sys.modules, litellm=SimpleNamespace(completion=completion)):
            with self.assertRaises(ChatError):
                ai_client.complete("fixture-key", "gpt-4o-mini", "hi", api_base="http://metadata")
            completion.assert_not_called()
            ai_client.complete("fixture-key", "gpt-4o-mini", "hi", api_base="http://127.0.0.1:9876/custom/v1")
        self.assertEqual(completion.call_args.kwargs['api_base'], "http://127.0.0.1:9876/custom/v1")
        self.assertEqual(completion.call_args.kwargs['messages'], [{"role":"user", "content":"hi"}])
        self.assertEqual(completion.call_args.kwargs["num_retries"], 0)

    def test_completion_uses_selected_provider_not_the_model_spelling(self):
        import ai_client
        from types import SimpleNamespace
        from unittest.mock import Mock
        completion = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]))
        with patch.dict(sys.modules, litellm=SimpleNamespace(completion=completion)):
            ai_client.complete("fixture", "claude-example", "hi", provider="custom", api_base="http://127.0.0.1/v1")
            self.assertEqual(completion.call_args.kwargs["model"], "openai/claude-example")
            ai_client.complete("fixture", "local-model", "hi", provider="groq")
            self.assertEqual(completion.call_args.kwargs["model"], "groq/local-model")
            with self.assertRaises(ChatError):
                ai_client.complete("fixture", "gpt-4o-mini", "hi", provider="custom")
            self.assertEqual(completion.call_count, 2)

    def test_server_configuration_and_secret_store(self):
        headers = self.api.get("/settings").headers
        self.assertIn("font-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(gunicorn_conf.workers, 1)
        self.assertGreaterEqual(gunicorn_conf.timeout, MAX_SCREEN_BUDGET + config.OPENAI_TIMEOUT + 45)
        self.assertIn(f'data-request-timeout="{ceil(MAX_SCREEN_BUDGET) + config.OPENAI_TIMEOUT + 30}"',
                      self.api.get("/workspace").get_data(as_text=True))
        with tempfile.TemporaryDirectory() as tmp, patch.object(secret_store, 'KEY_FILE', Path(tmp)/'private/key'):
            with ThreadPoolExecutor(6) as pool:
                values = list(pool.map(secret_store.encrypt_secret, ["stored"]*10))
            self.assertEqual(secret_store.KEY_FILE.stat().st_mode & 0o777, 0o600)
            self.assertTrue(all(secret_store.decrypt_secret(v) == "stored" for v in values))
        with patch.dict(os.environ, CYBERSYN_KEY="invalidκ"), self.assertRaises(ApiError) as raised:
            secret_store.encrypt_secret("test")
        self.assertNotIn("invalidκ", str(raised.exception))
        import ai_client
        from types import SimpleNamespace
        with patch.dict(sys.modules, litellm=SimpleNamespace(completion=lambda **kw: (_ for _ in ()).throw(ValueError(kw['api_key'])))):
            with self.assertRaises(ChatError) as error:
                ai_client.complete("secret-value", "model", "hello")
            self.assertNotIn("secret-value", str(error.exception))

    def test_message_edit_and_history_respect_active_block_policy(self):
        self.edit(admin_token=self.admin, API_KEY="fixture", CONTEXT_MESSAGES=4,
                  check1=False, check2=False, check3=False)
        with patch.object(chat_api, "complete", return_value="ok"):
            first = self.post("CHAT", **self.ids, prompt="Benign start").json
        self.edit(admin_token=self.admin, check1=True)
        blocked_edit = self.post("MESSAGE_EDIT", **self.ids, chat_id=first["chat_id"],
                                 message_id=first["message_id"], text="My API key is sk-proj-" + "x" * 22)
        self.assertEqual(blocked_edit.status_code, 403, blocked_edit.json)

        # Previous messages in context must not block a clean new prompt.
        chat_store.edit_message(DB_FILE, self.pid, self.eid, first["chat_id"], first["message_id"],
                                "Leaked key sk-proj-" + "y" * 22)
        with patch.object(chat_api, "complete", return_value="ok") as complete:
            follow = self.post("CHAT", **self.ids, chat_id=first["chat_id"], prompt="Continue")
            self.assertEqual(follow.status_code, 200, follow.json)
            self.assertFalse(follow.json.get("blocked"), follow.json)
            complete.assert_called_once()

    def test_openai_compatible_proxy_routes(self):
        import ai_client
        self.edit(admin_token=self.admin, API_KEY="fixture", MODEL_NAME="gpt-4o-mini",
                  action_check1="redact", action_check2="block", action_check3="block", restore_redactions=True)
        headers = {"Authorization": f"Bearer {self.ids['session_token']}"}
        self.assertEqual(self.api.get("/v1/models").status_code, 401)
        models = self.api.get("/v1/models", headers=headers)
        self.assertEqual(models.status_code, 200)
        self.assertEqual(models.json["data"][0]["id"], "gpt-4o-mini")

        # Unapproved vendor model blocked by Shadow AI policy.
        blocked_tool = self.api.post("/v1/chat/completions", headers=headers, json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "Hello"}],
        })
        self.assertEqual(blocked_tool.status_code, 403, blocked_tool.json)
        self.assertEqual(blocked_tool.json["cybersyn"]["main_cause"], "UNAPPROVED_AI_TOOL")

        # Multi-message PII redaction + restoration.
        with patch.object(ai_client, "complete_messages", side_effect=lambda *a, **kw:
                          f"Reply to {a[2][0]['content']} and {a[2][1]['content']}") as comp:
            res = self.api.post("/v1/chat/completions", headers=headers, json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": "Email alice@example.com"},
                    {"role": "user", "content": "Email bob@example.com"},
                ],
            })
        self.assertEqual(res.status_code, 200, res.json)
        sent_msgs = comp.call_args.args[2]
        self.assertNotIn("alice@example.com", sent_msgs[0]["content"])
        self.assertNotIn("bob@example.com", sent_msgs[1]["content"])
        self.assertNotEqual(sent_msgs[0]["content"], sent_msgs[1]["content"])
        reply_text = res.json["choices"][0]["message"]["content"]
        self.assertIn("alice@example.com", reply_text)
        self.assertIn("bob@example.com", reply_text)

    def test_chat_photo_ocr_route(self):
        import io
        import ocr
        # Unauthenticated upload fails with 401.
        anon = self.api.post(ROUTES["CHAT_PHOTO"], data={
            "Parent_id": str(self.pid),
            "Employee_id": str(self.eid),
            "photo": (io.BytesIO(b"not-an-image"), "bad.png"),
        }, content_type="multipart/form-data")
        self.assertEqual(anon.status_code, 401)

        # Missing/invalid image fails cleanly with 400.
        bad = self.api.post(ROUTES["CHAT_PHOTO"], data={
            "Parent_id": str(self.pid),
            "Employee_id": str(self.eid),
            "session_token": self.ids["session_token"],
            "photo": (io.BytesIO(b"not-an-image"), "bad.png"),
        }, content_type="multipart/form-data")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.json.get("error_code"), "invalid_photo")

        # Empty OCR returns exact "There's no text to parse in this prompt." message.
        with patch.object(ocr, "extract_text", side_effect=ocr.OcrNoTextError(ocr.NO_TEXT_ERROR)):
            no_text = self.api.post(ROUTES["CHAT_PHOTO"], data={
                "Parent_id": str(self.pid),
                "Employee_id": str(self.eid),
                "session_token": self.ids["session_token"],
                "photo": (io.BytesIO(b"\x89PNG\r\n\x1a\n"), "blank.png"),
            }, content_type="multipart/form-data")
        self.assertEqual(no_text.status_code, 400)
        self.assertEqual(no_text.json.get("error_code"), "no_photo_text")
        self.assertEqual(no_text.json.get("error_message"), "There's no text to parse in this prompt.")

        # Successful OCR returns extracted text.
        with patch.object(ocr, "extract_text", return_value="Hello from image"):
            good = self.api.post(ROUTES["CHAT_PHOTO"], data={
                "Parent_id": str(self.pid),
                "Employee_id": str(self.eid),
                "session_token": self.ids["session_token"],
                "photo": (io.BytesIO(b"\x89PNG\r\n\x1a\n"), "note.png"),
            }, content_type="multipart/form-data")
        self.assertEqual(good.status_code, 200)
        self.assertEqual(good.json.get("text"), "Hello from image")


if __name__ == '__main__':
    unittest.main(verbosity=2)
