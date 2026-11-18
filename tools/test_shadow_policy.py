#!/usr/bin/env python3
"""Offline integration tests for discovery, actions and independent sign-in."""

import contextlib
import logging
import os
import socket
import sqlite3
import sys
import tempfile
import time
import unittest
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
TMP = tempfile.TemporaryDirectory()
os.environ.update(CYBERSYN_DB_FILE=str(Path(TMP.name) / "gateway.db"),
                  CYBERSYN_KEY_FILE=str(Path(TMP.name) / "keys/key"))

import auth
import chat_store
import block_log
import config
import db
import rate_limit
import scanning
from app import app
from config import DB_FILE, ROUTES
from providers import BY_KEY
from redaction import RedactionError, redact, restore
from routes import chat_api, member_api

OWNER = {"username": "demo_owner", "password": "  Synthetic owner 1  "}
MEMBER = {"username": "demo_member", "password": "  Synthetic member 2  "}
HEADERS = {"X-CyberSyn-Request": "1", "X-CyberSyn-Session": "cookie", "Origin": "http://localhost"}
ALL_ALLOW = dict(action_check1="allow", action_check2="allow", action_check3="allow", action_code="allow")
EVENT_TIME = "2026-11-18T08:00:00Z"
ADDRESS = "memo@client.example"
FIXTURE_SECRET = "synthetic-sensitive-record"


def stamp(days=0):
    return (datetime.now(timezone.utc) - timedelta(days=days, minutes=1)).isoformat()


def finding(text, value, cause, start=0):
    start = text.index(value, start)
    return dict(start_offset=start, end_offset=start + len(value), cause=cause, score=.97,
                snippet=value, line=text.count("\n", 0, start) + 1)


def verdict(*matches):
    return dict(blocked=bool(matches), matches=list(matches))


class GatewayFeatures(unittest.TestCase):
    def setUp(self):
        rate_limit.reset()
        block_log.init(DB_FILE)
        with contextlib.closing(db.connect()) as con, con:
            for table in ("ADMINS", "EMPLOYEES", "SETTINGS", "ADMIN_SESSIONS", "EMPLOYEE_SESSIONS", "CHATS",
                          "BLOCK_LOG", "ACTIVITY_LOG", "EMPLOYEE_STATS"):
                con.execute(f"DELETE FROM {table}")
        self.api = app.test_client(use_cookies=False)
        self.browser = app.test_client()
        self.pid, self.admin = self.make_owner(OWNER)
        self.eid = self.add_member()
        login = self.post("EMPLOYEE_LOGIN", Parent_id=self.pid, **MEMBER)
        self.assertEqual(login.status_code, 200, login.json)
        self.ids = dict(Parent_id=self.pid, Employee_id=self.eid, session_token=login.json["session_token"])
        self.configure(**ALL_ALLOW, API_KEY="synthetic-fixture-key-not-real")

    def post(self, route, **body):
        return self.api.post(ROUTES[route], json=body)

    def browse(self, route, **body):
        return self.browser.post(ROUTES[route], json=body, headers=HEADERS)

    def make_owner(self, credentials, **extra):
        new = self.post("ADMIN", method="add", **credentials, **extra)
        self.assertEqual(new.status_code, 201, new.json)
        return new.json["Parent_id"], new.json["session_token"]

    def add_member(self, *, parent_id=None, token=None, credentials=MEMBER):
        new = self.post("EMPLOYEE", method="add", Parent_id=parent_id or self.pid, token=token or self.admin, **credentials)
        self.assertEqual(new.status_code, 201, new.json)
        return new.json["Employee_id"]

    def approve(self, scope="once"):
        result = self.post("ADMIN_APPROVE", scope=scope, Parent_id=self.pid, **OWNER)
        self.assertEqual(result.status_code, 200, result.json)
        return result.json["admin_token"]

    def configure(self, **changes):
        result = self.post("SETTINGS", Parent_id=self.pid, Employee_id=self.eid, admin_token=self.admin, **changes)
        self.assertEqual(result.status_code, 200, result.json)
        return result.json

    def history_seed(self, text="Synthetic draft"):
        chat_id, entry = chat_store.save_exchange(DB_FILE, int(self.pid), int(self.eid), None, text, "Original reply")
        return dict(chat_id=chat_id, message_id=entry["id"])

    def send(self, route="CHAT", **body):
        return self.post(route, **self.ids, **body)

    def read_shadow(self, **filters):
        result = self.post("SHADOW_AI", token=self.admin, Parent_id=self.pid, **filters)
        self.assertEqual(result.status_code, 200, result.json)
        return result.json

    def write_shadow(self, route, **values):
        result = self.post(route, Parent_id=self.pid, **dict({"admin_token": self.admin}, **values))
        self.assertEqual(result.status_code, 200, result.json)
        return result.json

    def workspace_rows(self, table):
        with contextlib.closing(db.connect()) as con:
            return [dict(row) for row in con.execute(f"SELECT * FROM {table} WHERE Parent_id=?", (self.pid,))]

    def test_direct_sign_in_workspace_resolution_and_password_whitespace(self):
        self.assertEqual(self.post("EMPLOYEE_LOGIN", **MEMBER).json["Parent_id"], self.pid)
        generic = self.post("EMPLOYEE_LOGIN", username=MEMBER["username"], password=MEMBER["password"].strip())
        self.assertEqual(generic.status_code, 401)
        self.assertEqual(generic.json["error_message"], "Invalid employee username or password.")
        second_owner = dict(OWNER, username="demo_second_owner")
        other, other_token = self.make_owner(second_owner, token=self.admin)
        second_member = dict(MEMBER, password="  Synthetic other member 3  ")
        other_eid = self.add_member(parent_id=other, token=other_token, credentials=second_member)
        ambiguous = self.post("EMPLOYEE_LOGIN", **MEMBER)
        self.assertEqual((ambiguous.status_code, ambiguous.json["error_message"]), (400, "Enter your workspace name to sign in."))
        good = self.post("EMPLOYEE_LOGIN", workspace=second_owner["username"], **second_member)
        self.assertEqual((good.status_code, good.json["Parent_id"], good.json["Employee_id"]), (200, other, other_eid))
        with patch.object(member_api, "credentials_match", wraps=member_api.credentials_match) as verify:
            unknown = self.post("EMPLOYEE_LOGIN", workspace="not_a_workspace", **MEMBER)
            self.assertEqual((unknown.status_code, unknown.json), (401, generic.json))
            verify.assert_called_once_with(None, MEMBER["password"])
        self.assertEqual(self.post("EMPLOYEE_LOGIN", Parent_id=self.pid, workspace="demo_owner", **MEMBER).status_code, 400)
        self.assertEqual(self.post("EMPLOYEE_LOGIN", Parent_id=self.pid, **MEMBER).status_code, 200)

    def test_zero_workspaces_and_member_login_retires_both_admin_cookies(self):
        self.assertEqual(self.browse("ADMIN_LOGIN", **OWNER).status_code, 200)
        self.assertEqual(self.browse("ADMIN_APPROVE", scope="page", **OWNER).status_code, 200)
        primary = self.browser.get_cookie(auth.ADMIN_COOKIE).value
        page = self.browser.get_cookie(auth.PAGE_COOKIE).value
        login = self.browse("EMPLOYEE_LOGIN", workspace=OWNER["username"], **MEMBER)
        self.assertNotIn("session_token", login.json)
        self.assertEqual(login.json["Parent_id"], self.pid)
        self.assertIsNone(self.browser.get_cookie(auth.ADMIN_COOKIE))
        self.assertIsNone(self.browser.get_cookie(auth.PAGE_COOKIE))
        self.assertIsNone(auth.admin_from_token(DB_FILE, primary))
        self.assertIsNone(auth.admin_from_token(DB_FILE, page, page=True))
        self.assertEqual(self.post("ADMIN", method="remove", **OWNER).status_code, 200)
        with patch.object(member_api, "credentials_match", wraps=member_api.credentials_match) as verify:
            missing = self.post("EMPLOYEE_LOGIN", **MEMBER)
            self.assertEqual((missing.status_code, missing.json["error_message"]), (401, "Invalid employee username or password."))
            verify.assert_called_once_with(None, MEMBER["password"])

    def test_additive_policy_migration_preserves_legacy_flags_and_explicit_actions(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(db, "DB_FILE", Path(tmp) / "legacy.db"):
            with contextlib.closing(sqlite3.connect(db.DB_FILE)) as con, con:
                con.execute("CREATE TABLE SETTINGS (Parent_id INTEGER, Employee_id INTEGER, check1 INTEGER, check2 INTEGER, "
                            "check3 INTEGER, block_code INTEGER, API_KEY TEXT, MODEL_NAME TEXT, PRIMARY KEY(Parent_id,Employee_id))")
                con.execute("INSERT INTO SETTINGS VALUES (1, 0, 0, 1, 0, 1, '', 'fixture-model')")
            db.init_db()
            with contextlib.closing(db.connect()) as con, con:
                row = con.execute("SELECT * FROM SETTINGS").fetchone()
                self.assertEqual(tuple(row[key] for key in (*ALL_ALLOW, "restore_redactions", "MODEL_NAME")),
                                 ("allow", "block", "allow", "block", 0, "fixture-model"))
                con.execute("UPDATE SETTINGS SET action_code='warn', restore_redactions=1")
            db.init_db()
            with contextlib.closing(db.connect()) as con:
                self.assertEqual(tuple(con.execute("SELECT action_code, restore_redactions FROM SETTINGS").fetchone()), ("warn", 1))
                self.assertEqual(con.execute("SELECT count(*) FROM DISCOVERY_EVENTS").fetchone()[0], 0)

    def test_settings_validate_and_inherit_actions_and_synchronize_legacy_flags(self):
        for changes in (dict(action_check3="redact"), dict(action_check1="WARN"), dict(action_code=[]),
                        dict(restore_redactions=1), dict(action_check1="warn", check1=1)):
            self.assertEqual(self.post("SETTINGS", **self.ids, admin_token=self.admin, **changes).status_code, 400)
        self.assertEqual(self.post("SETTINGS", **self.ids, action_check1="warn").status_code, 401)
        payload = self.configure(action_check1="warn", action_check2="redact", action_check3="block", action_code="allow",
                                 check1=False, block_code=True, restore_redactions=True, also_default=True)
        self.assertTrue(payload["check1"] and payload["check2"] and payload["check3"] and payload["restore_redactions"])
        self.assertFalse(payload["block_code"])
        for eid in (0, self.add_member(credentials=dict(MEMBER, username="demo_new_member"))):
            saved = self.post("SETTINGS", Parent_id=self.pid, Employee_id=eid, token=self.approve("page")).json
            self.assertEqual([saved[k] for k in (*ALL_ALLOW, "restore_redactions")], ["warn", "redact", "block", "allow", True])
        legacy = self.configure(check1=False, check2=True, check3=False, block_code=True)
        self.assertEqual([legacy[k] for k in ALL_ALLOW], ["allow", "block", "allow", "block"])

    def test_inventory_scope_and_page_grants_cannot_write(self):
        tools = self.read_shadow()["inventory"]
        self.assertEqual(len(tools), 16)
        self.assertEqual({t["provider_key"] for t in tools if t["provider_key"]}, set(BY_KEY) - {"custom"})
        self.assertTrue(all(0 <= t["risk_score"] <= 100 and t["gdpr_summary"] for t in tools))
        page = self.approve("page")
        self.assertEqual(self.post("SHADOW_AI", admin_token=page).status_code, 200)
        self.assertEqual(self.post("SHADOW_AI", admin_token=self.approve()).status_code, 401)
        for route, args in (("SHADOW_AI_IMPORT", {"sample": True}), ("SHADOW_AI_IMPORT", {"clear": True}),
                            ("SHADOW_AI_POLICY", {"tool_key": "openai", "status": "restricted"})):
            for token in (page, self.ids["session_token"], None):
                self.assertEqual(self.post(route, Parent_id=self.pid, admin_token=token, **args).status_code, 401)
        self.browse("ADMIN_APPROVE", scope="page", **OWNER)
        self.assertEqual(self.browse("SHADOW_AI").status_code, 200)
        self.assertEqual(self.browse("ADMIN_SESSION").status_code, 401)
        self.browser.set_cookie(auth.ADMIN_COOKIE, "invalid-primary-fixture")
        self.assertEqual(self.browse("SHADOW_AI").status_code, 401)  # no fallback to the valid page grant
        self.browser.delete_cookie(auth.ADMIN_COOKIE)
        self.assertEqual(self.browse("SHADOW_AI_IMPORT", Parent_id=self.pid, sample=True).status_code, 401)
        self.assertEqual(self.browse("SHADOW_AI_POLICY", Parent_id=self.pid, tool_key="openai", status="restricted").status_code, 401)
        self.browse("ADMIN_LOGIN", **OWNER)
        self.assertEqual(self.browse("SHADOW_AI", token="wrong-explicit-token").status_code, 401)
        self.assertEqual(self.browser.post(ROUTES["SHADOW_AI"], json={}).status_code, 403)
        for route, fields in (("SHADOW_AI", {}), ("SHADOW_AI_IMPORT", {"sample": True})):
            self.assertEqual(self.browser.post(ROUTES[route], json=dict(Parent_id=self.pid, **fields),
                headers=dict(HEADERS, Origin="https://outside.example")).status_code, 403)
        self.assertEqual(self.browse("SHADOW_AI_IMPORT", Parent_id=self.pid, sample=True).status_code, 200)
        other, token = self.make_owner(dict(OWNER, username="demo_workspace_other"), token=self.admin)
        self.assertEqual(self.post("SHADOW_AI_IMPORT", Parent_id=self.pid, token=token, clear=True).status_code, 401)
        self.assertEqual(self.post("SHADOW_AI", Parent_id=self.pid, token=token).status_code, 401)
        self.assertEqual(self.post("SHADOW_AI", Parent_id=other, token=token).json["summary"]["total_events"], 0)
        once = self.approve()
        with ThreadPoolExecutor(2) as pool:
            statuses = list(pool.map(lambda _: self.post("SHADOW_AI_POLICY", Parent_id=self.pid, admin_token=once,
                tool_key="openai", status="restricted", note="Synthetic workspace policy").status_code, range(2)))
        self.assertEqual(sorted(statuses), [200, 401])
        updated = next(t for t in self.read_shadow()["inventory"] if t["tool_key"] == "openai")
        self.assertEqual((updated["status"], updated["note"], updated["updated_by"]), ("restricted", "Synthetic workspace policy", OWNER["username"]))
        self.assertNotIn(updated["note"], repr(self.workspace_rows("ACTIVITY_LOG")))

    def test_custom_domain_policy_lifecycle_and_cascade(self):
        for host in ("https://assistant.example", "*", "*.example", "example", "api.example/path", "api.example:", "name@api.example", "api.example:65536"):
            self.assertEqual(self.post("SHADOW_AI_POLICY", Parent_id=self.pid, token=self.admin, method="add", domain=host).status_code, 400, host)
        custom = self.write_shadow("SHADOW_AI_POLICY", method="add", name="Fixture AI", domain="Assistant.EXAMPLE.:8443", status="restricted")["tool"]
        self.assertEqual(custom["tool_key"], "custom:assistant.example:8443")
        for host in ("assistant.example:8443", "node.assistant.example", "intranet.chatgpt.com"):
            self.assertEqual(self.post("SHADOW_AI_POLICY", Parent_id=self.pid, token=self.admin, method="add", domain=host).status_code, 409)
        result = self.write_shadow("SHADOW_AI_IMPORT", content=f"{stamp()} 10.20.1.5 CONNECT node.assistant.example:8443 64")
        self.assertEqual(result["ai_events_added"], 1)
        self.assertEqual(self.read_shadow()["events"][0]["status"], "restricted")
        self.assertIsNone(self.write_shadow("SHADOW_AI_POLICY", method="remove", tool_key=custom["tool_key"])["tool"])
        self.assertEqual(self.read_shadow()["events"][0]["status"], "unapproved")
        self.assertEqual(self.post("SHADOW_AI_POLICY", Parent_id=self.pid, token=self.admin, method="remove", tool_key="openai").status_code, 400)
        self.assertEqual(self.post("SHADOW_AI_POLICY", Parent_id=self.pid, token=self.admin, tool_key="openai", status="approved", note="x" * 241).status_code, 400)
        self.write_shadow("SHADOW_AI_POLICY", method="add", domain="second-assistant.example")
        self.assertEqual(self.post("ADMIN", method="remove", **OWNER).status_code, 200)
        self.assertEqual(self.workspace_rows("DISCOVERY_EVENTS"), [])
        self.assertEqual(self.workspace_rows("AI_TOOL_POLICY"), [])
        self.assertTrue(self.workspace_rows("ACTIVITY_LOG"))

    def test_offline_csv_proxy_and_dns_parse_only_structured_metadata(self):
        traffic = ('time,department,src_ip,destination,method,request_bytes,classification,prompt\n'
                   f'{stamp()},Sales,192.0.2.24,https://demo-user:fake-credential@FoO.ChatGPT.com.:8443/secret-path?api_key=secret#private,POST,4500,client_data,"private fixture\nsecond line"\n'
                   f'{stamp()},Engineering,10.20.4.1,chatgpt.com.benign.example,GET,1,general,ignored\n'
                   f'{stamp()},Engineering,10.20.4.2,127.0.0.1:11435,GET,1,general,ignored\n'
                   f'{stamp()},Engineering,10.20.4.3,127.0.0.1:11434,GET,1,general,ignored\n')
        plain = (f'{EVENT_TIME} 192.0.2.31 POST api.deepseek.com/u?redirect=https://privacy.example 4900\n'
                 '1794988800.0 100 192.0.2.32 TCP_MISS/200 9800 POST https://api.groq.com/path - HIER_DIRECT/- x/test\n'
                 '1794988801.0 101 192.0.2.33 TCP_TUNNEL/200 9800 CONNECT api.x.ai:443 demo_actor HIER_DIRECT/- - request_bytes=4999\n'
                 '192.0.2.34 - - [18/Nov/2026:09:00:00 +0200] "GET https://claude.ai/p?q=secret HTTP/1.1" 200 8010\n'
                 'Nov 18 08:00:00 dnsmasq[11]: query[A] api.perplexity.ai from 192.0.2.35\n'
                 f'{EVENT_TIME} named client @fixture 192.0.2.36#601 address: query: gemini.google.com IN AAAA +\n'
                 f'{EVENT_TIME} 192.0.2.37 query chatgpt.com.benign.example\n')
        with patch.object(socket, "getaddrinfo", side_effect=AssertionError("offline parser reached DNS")), \
             patch.object(urllib.request, "urlopen", side_effect=AssertionError("offline parser reached HTTP")):
            one = self.write_shadow("SHADOW_AI_IMPORT", content=traffic)
            two = self.write_shadow("SHADOW_AI_IMPORT", content=plain)
        self.assertEqual(tuple(one[key] for key in ("lines_scanned", "ai_events_added", "non_ai_ignored")), (4, 2, 2))
        self.assertEqual(tuple(two[key] for key in ("lines_scanned", "ai_events_added", "non_ai_ignored")), (7, 6, 1))
        events = self.read_shadow(days=0)["events"]
        by_host = {r["host"]: r for r in events}
        self.assertEqual(by_host["foo.chatgpt.com:8443"]["data_signal"], "client_data")
        self.assertEqual(by_host["api.deepseek.com"]["bytes_sent"], 4900)
        self.assertEqual(by_host["api.deepseek.com"]["data_signal"], "large_upload")
        self.assertEqual(by_host["api.groq.com"]["bytes_sent"], 0)
        self.assertEqual(by_host["api.x.ai:443"]["actor"], "demo_actor")
        self.assertEqual(by_host["api.x.ai:443"]["bytes_sent"], 4999)
        self.assertTrue(by_host["claude.ai"]["observed_at"].startswith("2026-11-18T07:00:00"))
        self.assertEqual(by_host["gemini.google.com"]["method"], "DNS")
        for table in ("ACTIVITY_LOG", "DISCOVERY_EVENTS"):
            rows = repr(self.workspace_rows(table))
            for unsafe in ("fake-credential", "?api_key=secret", "secret-path", "private fixture", "second line", "privacy.example", "q=secret"):
                self.assertNotIn(unsafe, rows)
        for malformed in ("\x00bin", "bad row without supported fields", 'host,user\n"no-end', "host,bytes\nchatgpt.com,-12", "\n" * 2001 + "actor DNS chatgpt.com"):
            self.assertEqual(self.post("SHADOW_AI_IMPORT", Parent_id=self.pid, token=self.admin, content=malformed).status_code, 400)
        self.assertEqual(len(self.workspace_rows("DISCOVERY_EVENTS")), 8)

    def test_sample_team_time_signal_and_live_policy_filters_and_clear(self):
        first = self.write_shadow("SHADOW_AI_IMPORT", sample=True, admin_token=self.approve())
        self.assertEqual((first["lines_scanned"], first["non_ai_ignored"], first["summary"]["total_events"]), (25, 3, 22))
        self.write_shadow("SHADOW_AI_IMPORT", content=f"date,group,host,data_signal\n{stamp(8)},Sales,api.deepseek.com,client_data")
        filters = {"team": "Sales", "data_signal": "client_data", "status": "unapproved"}
        week = self.read_shadow(days=7, **filters)
        self.assertEqual(week["summary"]["total_events"], 3)
        self.assertEqual(week["by_team"][0]["unapproved_tools"], ["DeepSeek", "Perplexity"])
        self.assertEqual(week["by_team"][0]["client_data_to_unapproved"], 3)
        self.assertEqual(self.read_shadow(days=30, **filters)["summary"]["total_events"], 4)
        ranked = self.read_shadow(days=7)["by_team"]
        self.assertEqual(ranked[0]["team"], "Sales")
        self.write_shadow("SHADOW_AI_POLICY", tool_key="deepseek", status="approved")
        self.assertEqual(self.read_shadow(days=7, **filters)["summary"]["total_events"], 1)
        self.assertEqual(self.write_shadow("SHADOW_AI_IMPORT", clear=True)["events_cleared"], 23)
        self.assertEqual(self.read_shadow(days=0)["events"], [])
        self.assertEqual(self.workspace_rows("AI_TOOL_POLICY")[0]["status"], "approved")

    def test_custom_tool_scope_label_boundaries_and_effective_port(self):
        self.write_shadow("SHADOW_AI_POLICY", method="add", domain="fixture-assistant.example:443")
        other, token = self.make_owner(dict(OWNER, username="demo_other_owner"), token=self.admin)
        self.assertEqual(self.post("SHADOW_AI_POLICY", Parent_id=other, token=token, method="add",
                                   domain="fixture-assistant.example:443", status="approved").status_code, 200)
        self.configure(PROVIDER="custom", API_BASE="https://node.fixture-assistant.example/v1")
        with patch.object(chat_api, "complete", return_value="Fixture answer") as complete:
            self.assertTrue(self.send(prompt="Synthetic prompt").json["blocked"])
            complete.assert_not_called()
            self.configure(API_BASE="https://notfixture-assistant.example/v1")
            self.assertEqual(self.send(prompt="Synthetic prompt").json["action"], "allow")
            self.configure(API_BASE="https://fixture-assistant.example:8443/v1")
            self.assertEqual(self.send(prompt="Synthetic prompt").json["action"], "allow")
        logs = ("host,user,method\nhttps://fixture-assistant.example/fixture?sample=1,user@client.example,POST\n"
                "https://notfixture-assistant.example/v1,user@client.example,POST\n"
                "https://fixture-assistant.example:8443/v1,user@client.example,POST")
        result = self.write_shadow("SHADOW_AI_IMPORT", content=logs)
        self.assertEqual((result["ai_events_added"], result["non_ai_ignored"]), (1, 2))
        event = self.read_shadow()["events"][0]
        self.assertEqual((event["host"], event["actor"], event["team"], event["status"]),
                         ("fixture-assistant.example", "user@client.example", "Unassigned", "unapproved"))
        foreign = self.post("SHADOW_AI_IMPORT", Parent_id=other, token=token, content=logs)
        self.assertEqual(foreign.status_code, 200)
        self.assertEqual(self.post("SHADOW_AI", Parent_id=other, token=token).json["events"][0]["status"], "approved")
        self.write_shadow("SHADOW_AI_IMPORT", clear=True)
        self.assertEqual(self.post("SHADOW_AI", Parent_id=other, token=token).json["summary"]["total_events"], 1)

    def test_discovery_event_details_are_capped_not_the_summary(self):
        lines = [f"{stamp()} 192.0.2.71 POST api.deepseek.com 4800" for _ in range(201)]
        self.write_shadow("SHADOW_AI_IMPORT", content="\n".join(lines))
        data = self.read_shadow()
        self.assertEqual(data["summary"]["total_events"], 201)
        self.assertEqual(len(data["events"]), 200)
        self.assertEqual([row["id"] for row in data["events"]], sorted((row["id"] for row in data["events"]), reverse=True))
        self.assertEqual(data["by_team"][0]["sensitive_data_to_unapproved"], 0)
        for filter_ in ({"days": True}, {"days": 14}, {"status": "other"}, {"data_signal": "test-fixture"}):
            self.assertEqual(self.post("SHADOW_AI", token=self.admin, **filter_).status_code, 400)

    def test_tool_policy_blocks_both_routes_allowing_only_an_authorized_override(self):
        draft = self.history_seed()
        self.configure(PROVIDER="deepseek", MODEL_NAME="deepseek-chat")
        with patch.object(chat_api, "complete", return_value="Synthetic answer") as complete:
            for route, args in (("CHAT", {"prompt": "Synthetic prompt"}), ("CHAT_REGENERATE", draft)):
                block = self.send(route, **args).json
                self.assertEqual((block["action"], block["block_info"]["stage"], block["block_info"]["main_cause"]),
                                 ("block", "policy", "UNAPPROVED_AI_TOOL"))
                self.assertIn("DeepSeek", block["error_message"])
                complete.assert_not_called()
                self.assertEqual(self.send(route, bypass=True, admin_token=self.approve("page"), **args).status_code, 401)
            for route, args in (("CHAT", {"prompt": "Synthetic prompt"}), ("CHAT_REGENERATE", draft)):
                grant = self.approve()
                self.assertEqual(self.send(route, bypass=True, admin_token=grant, **args).json["action"], "allow")
                self.assertEqual(self.send(route, bypass=True, admin_token=grant, **args).status_code, 401)
            self.configure(PROVIDER="auto", MODEL_NAME="xai/grok-demo")
            self.assertTrue(self.send(prompt="Synthetic prompt").json["blocked"])
            self.configure(MODEL_NAME="perplexity/sonar-fixture")
            self.assertTrue(self.send(prompt="Synthetic prompt").json["blocked"])
            self.configure(PROVIDER="custom", API_BASE="https://assistant.example/v1")
            self.assertEqual(self.send(prompt="Synthetic prompt").json["action"], "allow")
            self.write_shadow("SHADOW_AI_POLICY", method="add", domain="assistant.example")
            self.configure(PROVIDER="openai")
            self.assertTrue(self.send(prompt="Synthetic prompt").json["blocked"])
            self.write_shadow("SHADOW_AI_POLICY", tool_key="custom:assistant.example", status="restricted")
            self.assertEqual(self.send(prompt="Synthetic prompt").json["action"], "allow")
        self.assertTrue(any(row["reason"] == "UNAPPROVED_AI_TOOL" for row in self.workspace_rows("BLOCK_LOG")))

    def test_local_ollama_does_not_require_a_key(self):
        self.configure(PROVIDER="ollama", CLEAR_API_KEY=True, MODEL_NAME="fixture-model")
        with patch.object(chat_api, "complete", return_value="Local fixture") as complete:
            self.assertEqual(self.send(prompt="Synthetic prompt").json["reply_message"], "Local fixture")
            self.assertEqual(complete.call_args.args[0], "")
            self.assertEqual(complete.call_args.kwargs["api_base"], "http://localhost:11434")
            self.write_shadow("SHADOW_AI_POLICY", tool_key="ollama", status="unapproved")
            self.assertTrue(self.send(prompt="Synthetic prompt").json["blocked"])
            self.assertEqual(complete.call_count, 1)

    def test_provider_exception_and_diagnostics_keep_the_prompt_out_of_logs(self):
        client = SimpleNamespace()

        def fail_call(**kwargs):
            self.assertTrue(client.turn_off_message_logging)
            self.assertTrue(client.redact_messages_in_exceptions)
            self.assertTrue(client.suppress_debug_info)
            self.assertFalse(client.set_verbose or client.log_raw_request_response)
            logging.getLogger("LiteLLM").warning("Debug diagnostic: %r", kwargs)
            raise RuntimeError("Fixture request: " + repr(kwargs))

        client.completion = fail_call
        package_logs = [logging.getLogger(name) for name in ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy")]
        for logger in package_logs:
            self.addCleanup(setattr, logger, "disabled", logger.disabled)
        with patch.dict(sys.modules, litellm=client), self.assertLogs(level="WARNING") as log:
            answer = self.send(prompt=FIXTURE_SECRET, bypass=True, admin_token=self.approve())
        self.assertEqual(answer.status_code, 502, answer.json)
        self.assertEqual(len(log.output), 1)
        self.assertIn("Provider call failed", log.output[0])
        for text in (FIXTURE_SECRET, "synthetic-fixture-key-not-real"):
            self.assertNotIn(text, str(answer.json))
            self.assertNotIn(text, repr(log.output))
            self.assertNotIn(text, repr(self.workspace_rows("ACTIVITY_LOG")))

    def test_warnings_pause_confirmation_rechecks_and_never_log_evidence(self):
        self.configure(action_check1="warn", action_check3="block")
        warning_marker = ADDRESS
        block_marker = "synthetic-block-trigger"

        def scan(stage, text, *a, **kw):
            if stage == "check1" and warning_marker in text:
                return verdict(finding(text, warning_marker, "EMAIL"))
            if stage == "check3" and block_marker in text:
                return verdict(finding(text, block_marker, "PROMPT_INJECTION"))
            return verdict()

        with patch.object(scanning, "run_check", side_effect=scan), patch.object(config, "LOG_PROMPT_PREVIEW", True), \
             patch.object(chat_api, "complete", return_value="Synthetic answer") as complete:
            for route, args in (("CHAT", {}), ("CHAT_REGENERATE", self.history_seed("Original safe prompt"))):
                with self.subTest(route=route):
                    baseline = len(self.workspace_rows("CHATS"))
                    calls = complete.call_count
                    stopped = self.send(route, prompt=warning_marker, **args)
                    self.assertEqual(stopped.status_code, 200)
                    self.assertEqual([stopped.json[k] for k in ("error", "blocked", "warned", "action", "reply_message")],
                                     [False, False, True, "warn", "NULL"])
                    self.assertEqual(stopped.json["warn_info"]["snippet"], warning_marker)
                    self.assertFalse(stopped.json["warn_info"]["will_redact"])
                    self.assertEqual(len(self.workspace_rows("CHATS")), baseline)
                    self.assertEqual(complete.call_count, calls)
                    self.assertEqual(self.send(route, prompt=warning_marker, confirm_warn="true", **args).status_code, 400)
                    changed = self.send(route, prompt=f"{warning_marker} {block_marker}", confirm_warn=True, **args).json
                    self.assertTrue(changed["blocked"])
                    self.assertEqual(complete.call_count, calls)
                    result = self.send(route, prompt=warning_marker, confirm_warn=True, **args).json
                    self.assertEqual((result["action"], result["reply_message"]), ("allow", "Synthetic answer"))
                    self.assertEqual(complete.call_args.args[2], warning_marker)
            self.send("CHAT_REGENERATE", **dict(chat_id=result["chat_id"], message_id=result["message_id"]), confirm_warn=True)
        for table in ("BLOCK_LOG", "ACTIVITY_LOG"):
            self.assertNotIn(warning_marker, repr(self.workspace_rows(table)))
            self.assertNotIn(block_marker, repr(self.workspace_rows(table)))
        activity = [row["kind"] for row in self.workspace_rows("ACTIVITY_LOG")]
        self.assertIn("warned", activity)
        self.assertIn("warn_proceeded", activity)

    def test_redaction_overlap_repetition_collision_and_local_restoration_in_both_routes(self):
        self.configure(action_check1="redact", action_check2="redact", restore_redactions=True)
        text = f"[EMAIL_1]; {ADDRESS} / {ADDRESS}; confidential:{FIXTURE_SECRET}END"

        def scan(stage, prompt, *a, **kw):
            self.assertTrue(kw["full_detail"])
            if stage == "check1":
                # Catch the first occurrence only (redaction still masks repeats).
                return verdict(finding(prompt, ADDRESS, "EMAIL"))
            return verdict(finding(prompt, f"confidential:{FIXTURE_SECRET}", "internal company financial data"),
                           finding(prompt, FIXTURE_SECRET + "END", "legal contract or NDA"))

        sanitized = "[EMAIL_1]; [EMAIL_2] / [EMAIL_2]; [CONFIDENTIAL_1]"
        with patch.object(scanning, "run_check", side_effect=scan), patch.object(config, "LOG_PROMPT_PREVIEW", True), \
             patch.object(chat_api, "complete", return_value="[EMAIL_1] [EMAIL_2] [CONFIDENTIAL_1]") as complete:
            for route, args in (("CHAT", {}), ("CHAT_REGENERATE", self.history_seed())):
                result = self.send(route, prompt=text, **args).json
                self.assertEqual(result["action"], "redact", result)
                self.assertEqual(complete.call_args.args[2], sanitized)
                self.assertEqual(result["redacted_prompt"], sanitized)
                self.assertEqual(result["reply_message"], f"[EMAIL_1] {ADDRESS} confidential:{FIXTURE_SECRET}END")
                self.assertEqual(result["redaction_info"], dict(count=3, categories=["CONFIDENTIAL", "EMAIL"],
                                                              placeholders=["[EMAIL_2]", "[CONFIDENTIAL_1]"], restored=True))
                if route == "CHAT_REGENERATE":
                    self.assertNotIn(ADDRESS, repr(result["messages"]))
                history = self.send("CHATS_OPEN", chat_id=result["chat_id"]).json["chat"]["messages"][0]
                self.assertTrue(history["redacted"])
                self.assertFalse(history["redaction_info"]["restored"])
                self.assertEqual(history["prompt"], sanitized)
                self.assertEqual(history["answer"], "[EMAIL_1] [EMAIL_2] [CONFIDENTIAL_1]")
        for table in ("CHATS", "ACTIVITY_LOG", "BLOCK_LOG"):
            self.assertNotIn(ADDRESS, repr(self.workspace_rows(table)))
            self.assertNotIn(FIXTURE_SECRET, repr(self.workspace_rows(table)))
        stats = self.post("TEAM", token=self.admin).json
        self.assertEqual(stats["stats"]["blocked"], 0)
        self.assertEqual(stats["members"][0]["checks_on"], 2)

    def test_redaction_stays_enabled_on_override_and_warning_confirmation(self):
        self.configure(action_check1="redact", action_check2="warn")
        text = f"{ADDRESS} and {FIXTURE_SECRET}"

        def scan(stage, prompt, *a, **kw):
            return (verdict(finding(prompt, ADDRESS, "EMAIL")) if stage == "check1" else
                    verdict(finding(prompt, FIXTURE_SECRET, "legal contract or NDA")))

        with patch.object(scanning, "run_check", side_effect=scan), patch.object(chat_api, "complete", return_value=ADDRESS) as complete:
            pause = self.send(prompt=text).json
            self.assertTrue(pause["warn_info"]["will_redact"])
            complete.assert_not_called()
            for options in (dict(confirm_warn=True), dict(bypass=True, admin_token=self.approve())):
                sent = self.send(prompt=text, **options).json
                self.assertEqual(sent["action"], "redact")
                self.assertEqual(sent["reply_message"], "[EMAIL_1]")
                self.assertEqual(complete.call_args.args[2], f"[EMAIL_1] and {FIXTURE_SECRET}")
        self.assertNotIn(ADDRESS, repr(self.workspace_rows("CHATS")))

    def test_source_and_confidential_actions_are_independent_and_scan_full_paste(self):
        scanning.registry.get_scanner("check2")  # import the real local context scanner
        import context
        tail = "synthetic private tail"
        code = 'const fixture = "strictly confidential synthetic fixture";\nreturn demo_value'
        long_prompt = "strictly confidential synthetic header\n" + "\n".join(
            f"Synthetic test line {i} to classify" for i in range(context.DETAIL_LINES + 1)) + f"\n{tail}"

        def classify(items, labels, **kwargs):
            return [{"labels": [context.LABELS[3] if tail in line else context.SAFE_LABEL], "scores": [.96]} for line in items]

        with patch.object(context, "classify_batched", side_effect=classify), patch.object(chat_api, "complete", return_value="ok") as complete:
            self.configure(action_check2="redact", action_code="allow")
            self.assertEqual(self.send(prompt=code).json["action"], "redact")
            self.assertIn("return demo_value", complete.call_args.args[2])
            self.assertNotIn("strictly confidential", complete.call_args.args[2])
            self.assertNotIn(tail, self.send(prompt=long_prompt).json["redacted_prompt"])
            self.configure(action_check2="block", action_code="warn")
            self.assertEqual(self.send(prompt=code).json["block_info"]["main_cause"], "internal company financial data")
            self.assertTrue(self.send(prompt="return demo_value").json["warned"])
            self.configure(action_check2="allow", action_code="redact")
            self.assertEqual(self.send(prompt=code).json["redaction_info"]["categories"], ["CODE"])

    def test_redact_skips_legacy_ner_short_circuit_and_safely_edits_history(self):
        scanning.registry.get_scanner("check1")
        import greek_pii
        self.configure(action_check1="redact")
        name = "Fictional Fixture"
        text = ADDRESS + "\n" + "nonsensitive filler " * 80 + "\n" + name
        self.assertGreater(len(text), greek_pii.DETAIL_CHARS)
        start = len(text) - len(name)
        entity = SimpleNamespace(label_="PERSON", text=name, start_char=start, end_char=len(text))
        chat_id, entry = chat_store.save_exchange(DB_FILE, int(self.pid), int(self.eid), None,
                                                  ADDRESS, f"Original answer for {ADDRESS}")
        draft = dict(chat_id=chat_id, message_id=entry["id"])
        with patch.object(greek_pii, "run_ner", return_value=SimpleNamespace(ents=[entity])) as ner, \
             patch.object(chat_api, "complete", return_value="Synthetic answer") as complete:
            edited = self.send("MESSAGE_EDIT", **draft, text=text)
            self.assertEqual(edited.status_code, 200, edited.json)
            self.assertEqual(ner.call_count, 2)
            saved = edited.json["messages"][0]["prompt"]
            self.assertNotIn(ADDRESS, saved)
            self.assertNotIn(name, saved)
            self.assertNotIn(ADDRESS, edited.json["messages"][0]["answer"])
            self.assertNotIn(ADDRESS, repr(self.workspace_rows("CHATS")))
            with patch.object(greek_pii, "run_ner", return_value=SimpleNamespace(ents=[])):
                regen = self.send("CHAT_REGENERATE", **draft)
                self.assertEqual(regen.json["action"], "redact")
                self.assertEqual(complete.call_args.args[2], saved)

    def test_fail_closed_on_invalid_error_or_timeout_for_both_routes(self):
        draft = self.history_seed()
        failures = [ValueError(FIXTURE_SECRET), {"blocked": "false"}, {"blocked": True, "matches": []},
                    verdict(dict(cause="EMAIL", start_offset=True, end_offset=5, snippet="bad"))]
        with patch.object(chat_api, "complete") as complete:
            for action in ("warn", "redact", "block"):
                self.configure(action_check1=action)
                for route, args in (("CHAT", {}), ("CHAT_REGENERATE", draft)):
                    for failure in failures:
                        mock = {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure}
                        with patch.object(scanning, "run_check", **mock):
                            answer = self.send(route, **args, prompt=FIXTURE_SECRET)
                            self.assertEqual(answer.status_code, 503, (action, route, answer.json))
                            self.assertNotIn(FIXTURE_SECRET, str(answer.json))
                    with patch.object(scanning, "SCREEN_BUDGET", .04), \
                         patch.object(scanning, "run_check", side_effect=lambda *a, **k: time.sleep(.15)):
                        self.assertEqual(self.send(route, **args, prompt=FIXTURE_SECRET).status_code, 503)
            complete.assert_not_called()
        self.assertEqual(self.send("CHATS_OPEN", chat_id=draft["chat_id"]).json["chat"]["messages"][0]["answer"], "Original reply")


class RedactionTests(unittest.TestCase):
    def test_merged_span_uses_highest_severity_then_first_category(self):
        text = "review synthetic-value"
        matches = [finding(text, text, "computer source code"), finding(text, "synthetic-value", "API_KEY"),
                   finding(text, "synthetic-value", "IBAN")]
        result = redact(text, matches)
        self.assertEqual(result.prompt, "[API_KEY_1]")
        self.assertEqual(result.un_restored_reply("safe synthetic-value"), "safe [API_KEY_1]")
        self.assertEqual(restore(result.prompt, result.mapping), text)

    def test_exact_single_pass_restore_and_invalid_offsets(self):
        self.assertEqual(restore("[CODE_1] [EMAIL_2] [CODE_11] [CODE_1]", {"[CODE_1]": "[EMAIL_2]", "[EMAIL_2]": ADDRESS}),
                         f"[EMAIL_2] {ADDRESS} [CODE_11] [EMAIL_2]")
        for start, end in ((-1, 2), (0, 0), (0, 99), (False, 2), (0, 2.5)):
            with self.assertRaises(RedactionError):
                redact("abc", [dict(cause="EMAIL", start_offset=start, end_offset=end)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
