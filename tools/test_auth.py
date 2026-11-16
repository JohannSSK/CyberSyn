#!/usr/bin/env python3
"""Regression tests for who is allowed to call CyberSyn's member routes.

These lock in the fix for the finding that every employee-facing route trusted
two guessable integers (Parent_id / Employee_id) with nothing proving who the
caller was. Without this file, that hole can silently come back.

Run it from anywhere:

    python3 tools/test_auth.py

It needs no network and no ML models: the scanners and the AI call are stubbed,
because what is under test is authorisation, not detection quality.
"""

import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"

# Point the app at a throwaway database before it is imported, so the tests
# never touch the development database.
_TMP = tempfile.mkdtemp(prefix="cybersyn-test-")
os.environ["CYBERSYN_DB_FILE"] = str(Path(_TMP) / "test.db")

sys.path.insert(0, str(SRC))
import app as cybersyn  # noqa: E402  (import after the path/env setup)
import auth  # noqa: E402

DB = cybersyn.DB_FILE


def seed():
    """Create one administrator and one team member."""
    import sqlite3
    con = sqlite3.connect(DB)
    con.execute(
        "INSERT INTO ADMINS (username, password) VALUES (?, ?)",
        ("boss", cybersyn.generate_password_hash("admin-pw")),
    )
    con.execute(
        "INSERT INTO EMPLOYEES (Parent_id, username, password) VALUES (?, ?, ?)",
        (1, "member", cybersyn.generate_password_hash("member-pw")),
    )
    con.commit()
    con.close()


class AuthModuleTests(unittest.TestCase):
    """The token primitives in src/auth.py."""

    def setUp(self):
        auth.init_tables(DB)
        import sqlite3
        con = sqlite3.connect(DB)
        con.execute("DELETE FROM EMPLOYEE_SESSIONS")
        con.commit()
        con.close()

    def test_issued_token_resolves_to_its_member(self):
        token = auth.create_employee_session(DB, 1, 7)
        self.assertEqual(auth.member_from_token(DB, token),
                         {"Parent_id": 1, "Employee_id": 7})

    def test_unknown_and_empty_tokens_resolve_to_nothing(self):
        auth.create_employee_session(DB, 1, 7)
        for token in ("", "   ", "forged", None, 12345, object()):
            self.assertIsNone(auth.member_from_token(DB, token))

    def test_revoked_member_loses_access(self):
        token = auth.create_employee_session(DB, 1, 7)
        auth.revoke_employee_sessions(DB, 1, 7)
        self.assertIsNone(auth.member_from_token(DB, token))

    def test_expired_token_is_refused_and_cleaned_up(self):
        token = auth.create_employee_session(DB, 1, 7)
        import sqlite3
        con = sqlite3.connect(DB)
        con.execute(
            "UPDATE EMPLOYEE_SESSIONS SET expires_at = ?",
            ((auth.datetime.now(auth.timezone.utc) - timedelta(days=1)).isoformat(),),
        )
        con.commit()
        con.close()
        self.assertIsNone(auth.member_from_token(DB, token))
        con = sqlite3.connect(DB)
        gone = con.execute("SELECT COUNT(*) FROM EMPLOYEE_SESSIONS").fetchone()[0]
        con.close()
        self.assertEqual(gone, 0, "the expired row should be deleted on use")

    def test_require_member_rejects_missing_parts(self):
        token = auth.create_employee_session(DB, 1, 7)
        good = {"Parent_id": 1, "Employee_id": 7, "session_token": token}
        self.assertEqual(auth.require_member(DB, good)[:2], (1, 7))
        for bad in [
            {}, None, "nope",
            dict(good, session_token=None),
            dict(good, session_token="forged"),
            dict(good, Parent_id=None),
            dict(good, Employee_id="abc"),
            dict(good, Parent_id=0),
        ]:
            self.assertEqual(auth.require_member(DB, bad), (None, None, False), bad)

    def test_a_member_cannot_act_as_another_member(self):
        mine = auth.create_employee_session(DB, 1, 7)
        self.assertEqual(auth.require_member(
            DB, {"Parent_id": 1, "Employee_id": 8, "session_token": mine}),
            (None, None, False))
        self.assertEqual(auth.require_member(
            DB, {"Parent_id": 2, "Employee_id": 7, "session_token": mine}),
            (None, None, False))


class RouteTests(unittest.TestCase):
    """The HTTP boundary: what an unauthenticated caller can and cannot reach."""

    @classmethod
    def setUpClass(cls):
        seed()
        cls.client = cybersyn.app.test_client()

        cls.admin = cls.client.post(
            "/api/admin/login",
            json={"username": "boss", "password": "admin-pw"},
        ).get_json()["session_token"]

        login = cls.client.post(
            "/api/admin/employee/login",
            json={"Parent_id": 1, "username": "member", "password": "member-pw"},
        ).get_json()
        cls.member_id = int(login["Employee_id"])
        cls.member = login["session_token"]

        # The chat route needs a stored key before it will forward anything.
        cls.client.post("/api/admin/employee/settings",
                        json={"Parent_id": 1, "Employee_id": cls.member_id,
                              "session_token": cls.member,
                              "API_KEY": "sk-test-key-1234567890"})

        # Stub the two things that would need the network or a model, so the
        # tests measure authorisation only.
        cybersyn.call_openai = lambda key, model, prompt: "stub reply"
        cybersyn.run_check = lambda stage, prompt: {
            "blocked": True, "stage": stage, "reason": "stub",
            "line": 1, "start": 0, "end": 1, "snippet": "", "matches": [],
        }

    def ids(self, **extra):
        body = {"Parent_id": 1, "Employee_id": self.member_id,
                "session_token": self.member}
        body.update(extra)
        return body

    # -- the attacks that used to succeed with no credentials at all ---------

    def test_prompt_without_a_session_is_refused(self):
        r = self.client.post("/api/admin/employee/chat",
                             json={"Parent_id": 1, "Employee_id": 1, "prompt": "hi"})
        self.assertEqual(r.status_code, 401)

    def test_chat_history_without_a_session_is_refused(self):
        for path in ("chats", "chats/open", "chats/delete", "chats/rename"):
            with self.subTest(path=path):
                r = self.client.post(f"/api/admin/employee/{path}",
                                     json={"Parent_id": 1, "Employee_id": 1,
                                           "chat_id": 1, "title": "x"})
                self.assertEqual(r.status_code, 401)

    def test_turning_the_checks_off_without_a_session_is_refused(self):
        r = self.client.post("/api/admin/employee/settings",
                             json={"Parent_id": 1, "Employee_id": 1,
                                   "check1": False, "check2": False, "check3": False})
        self.assertEqual(r.status_code, 401)

    def test_model_discovery_without_a_session_is_refused(self):
        r = self.client.post("/api/admin/employee/models", json={"API_KEY": "sk-x"})
        self.assertEqual(r.status_code, 401)

    def test_override_without_an_administrator_session_is_refused(self):
        for extra in ({}, {"admin_token": None}, {"admin_token": "forged"},
                      {"admin_token": self.member}):
            with self.subTest(**extra):
                r = self.client.post(
                    "/api/admin/employee/chat",
                    json=self.ids(prompt="send this anyway", bypass=True, **extra))
                self.assertEqual(r.status_code, 401)

    def test_a_forged_or_borrowed_token_is_refused(self):
        r = self.client.post("/api/admin/employee/chat",
                             json=self.ids(prompt="hi", session_token="forged"))
        self.assertEqual(r.status_code, 401)

    def test_a_member_cannot_reach_another_members_history(self):
        r = self.client.post("/api/admin/employee/chats",
                             json=self.ids(Employee_id=self.member_id + 1))
        self.assertEqual(r.status_code, 401)

    # -- the calls that must still work -------------------------------------

    def test_a_signed_in_member_can_chat(self):
        r = self.client.post("/api/admin/employee/chat",
                             json=self.ids(prompt="hello", check1=False,
                                           check2=False, check3=False))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["reply_message"], "stub reply")

    def test_a_signed_in_member_can_change_their_own_settings(self):
        r = self.client.post("/api/admin/employee/settings",
                             json=self.ids(MODEL_NAME="gpt-4o-mini"))
        self.assertEqual(r.status_code, 200)

    def test_a_signed_in_member_can_read_their_own_history(self):
        r = self.client.post("/api/admin/employee/chats", json=self.ids())
        self.assertEqual(r.status_code, 200)
        self.assertIn("chats", r.get_json())

    def test_an_administrator_can_set_a_members_policy(self):
        r = self.client.post("/api/admin/employee/settings",
                             json=self.ids(session_token=self.admin,
                                           MODEL_NAME="gpt-4o-mini"))
        self.assertEqual(r.status_code, 200)

    def test_an_administrator_cannot_read_a_members_history(self):
        """Deliberate: policy is the administrator's job, the content is not."""
        r = self.client.post("/api/admin/employee/chats",
                             json=self.ids(session_token=self.admin))
        self.assertEqual(r.status_code, 401)

    def test_an_approved_override_goes_through_and_is_logged(self):
        r = self.client.post("/api/admin/employee/chat",
                             json=self.ids(prompt="send this anyway", bypass=True,
                                           admin_token=self.admin,
                                           check1=True, check2=True, check3=True))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["reply_message"], "stub reply")

        import sqlite3
        con = sqlite3.connect(DB)
        rows = con.execute(
            "SELECT COUNT(*) FROM BLOCK_LOG WHERE stage = 'override'").fetchone()[0]
        con.close()
        self.assertGreaterEqual(rows, 1, "an override must leave an audit trail")

    def test_a_blocked_prompt_is_logged_and_not_forwarded(self):
        r = self.client.post("/api/admin/employee/chat",
                             json=self.ids(prompt="my AFM is 123456789",
                                           check1=True, check2=True, check3=True))
        body = r.get_json()
        self.assertTrue(body["blocked"], "the stub scanner blocks everything")
        self.assertEqual(body.get("reply_message"), "NULL", "nothing is forwarded when blocked")

    def test_the_administrator_dashboard_still_works(self):
        r = self.client.post("/api/admin/team", json={"token": self.admin})
        self.assertEqual(r.status_code, 200)
        member = [m for m in r.get_json()["members"] if m["username"] == "member"][0]
        # A blocked prompt counts as a block; an approved override does not.
        self.assertEqual(member["blocked"], 1)
        self.assertEqual(member["overrides"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
