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
from unittest.mock import patch
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"

# Point the app at a throwaway database before it is imported, so the tests
# never touch the development database.
_TMP = tempfile.mkdtemp(prefix="cybersyn-test-")
os.environ["CYBERSYN_DB_FILE"] = str(Path(_TMP) / "test.db")

os.environ["CYBERSYN_KEY_FILE"] = str(Path(_TMP) / "secret.key")
sys.path.insert(0, str(SRC))
import app as cybersyn  # noqa: E402  (import after the path/env setup)
import auth  # noqa: E402
import ai_client  # noqa: E402
import scanning  # noqa: E402

from config import ROUTES  # noqa: E402
DB = cybersyn.DB_FILE


def seed():
    """Create one administrator and one team member.

    The administrator keeps id 1 no matter which other fixtures have run —
    the tests below refer to its workspace by that id.
    """
    import sqlite3

    from passwords import hash_password

    con = sqlite3.connect(DB)
    con.execute(
        "INSERT INTO ADMINS (id, username, password) VALUES (1, ?, ?)",
        ("boss", hash_password("admin-pw")),
    )
    con.execute(
        "INSERT INTO EMPLOYEES (Parent_id, username, password) VALUES (?, ?, ?)",
        (1, "member", hash_password("member-pw")),
    )
    con.commit()
    con.close()


class AuthModuleTests(unittest.TestCase):
    """The token primitives in src/auth.py."""

    def setUp(self):
        auth.init_tables(DB)
        import sqlite3
        con = sqlite3.connect(DB)
        con.execute("INSERT OR IGNORE INTO EMPLOYEES (id, Parent_id, username, password) VALUES (7, 1, 'fixture', 'legacy')")
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
        cls.client = cybersyn.app.test_client(use_cookies=False)

        cls.admin = cls.client.post(
            ROUTES["ADMIN_LOGIN"],
            json={"username": "boss", "password": "admin-pw"},
        ).get_json()["session_token"]

        login = cls.client.post(
            ROUTES["EMPLOYEE_LOGIN"],
            json={"Parent_id": 1, "username": "member", "password": "member-pw"},
        ).get_json()
        cls.member_id = int(login["Employee_id"])
        cls.member = login["session_token"]

        # The chat route needs a stored key before it will forward anything.
        # Setting one is an administrator action, so it carries the
        # administrator's approval as well as the member's session.
        cls.client.post(ROUTES["SETTINGS"],
                        json={"Parent_id": 1, "Employee_id": cls.member_id,
                              "session_token": cls.member,
                              "admin_token": cls.admin,
                              "API_KEY": "sk-test-key-1234567890"})

        # Stub the two things that would need the network or a model, so the
        # tests measure authorisation only.
        # Patched where each is *used*: chat_api binds complete() at import.
        from routes import chat_api

        chat_api.complete = lambda key, model, prompt, **kwargs: "stub reply"
        # Screening passes each check the time left in its shared budget,
        # plus a stop flag the checks use to abandon a settled verdict.
        def scan(stage, prompt, *args, **kwargs):
            matches = [] if prompt == "hello" else [{
                "line": 1, "cause": "GREEK_AFM", "score": .95,
                "start_offset": 0, "end_offset": len(prompt), "snippet": prompt,
            }]
            return {"blocked": bool(matches), "matches": matches}

        scanning.run_check = scan

    def ids(self, **extra):
        body = {"Parent_id": 1, "Employee_id": self.member_id,
                "session_token": self.member}
        body.update(extra)
        return body

    # -- the attacks that used to succeed with no credentials at all ---------

    def test_prompt_without_a_session_is_refused(self):
        r = self.client.post(ROUTES["CHAT"],
                             json={"Parent_id": 1, "Employee_id": 1, "prompt": "hi"})
        self.assertEqual(r.status_code, 401)

    def test_chat_history_without_a_session_is_refused(self):
        for path in ("CHATS", "CHATS_OPEN", "CHATS_DELETE", "CHATS_RENAME"):
            with self.subTest(path=path):
                r = self.client.post(ROUTES[path],
                                     json={"Parent_id": 1, "Employee_id": 1,
                                           "chat_id": 1, "title": "x"})
                self.assertEqual(r.status_code, 401)

    def test_turning_the_checks_off_without_a_session_is_refused(self):
        r = self.client.post(ROUTES["SETTINGS"],
                             json={"Parent_id": 1, "Employee_id": 1,
                                   "check1": False, "check2": False, "check3": False})
        self.assertEqual(r.status_code, 401)

    def test_model_discovery_without_a_session_is_refused(self):
        r = self.client.post(ROUTES["MODELS"], json={"API_KEY": "sk-x"})
        self.assertEqual(r.status_code, 401)

    def test_override_without_an_administrator_session_is_refused(self):
        for extra in ({}, {"admin_token": None}, {"admin_token": "forged"},
                      {"admin_token": self.member}):
            with self.subTest(**extra):
                r = self.client.post(
                    ROUTES["CHAT"],
                    json=self.ids(prompt="send this anyway", bypass=True, **extra))
                self.assertEqual(r.status_code, 401)

    def test_a_forged_or_borrowed_token_is_refused(self):
        r = self.client.post(ROUTES["CHAT"],
                             json=self.ids(prompt="hi", session_token="forged"))
        self.assertEqual(r.status_code, 401)

    def test_a_member_cannot_reach_another_members_history(self):
        r = self.client.post(ROUTES["CHATS"],
                             json=self.ids(Employee_id=self.member_id + 1))
        self.assertEqual(r.status_code, 401)

    # -- the calls that must still work -------------------------------------

    def test_a_signed_in_member_can_chat(self):
        r = self.client.post(ROUTES["CHAT"],
                             json=self.ids(prompt="hello"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["reply_message"], "stub reply")

    def test_a_member_cannot_disable_checks_or_change_model_per_request(self):
        from routes import chat_api
        with patch.object(chat_api, "screen", return_value=None) as screen, \
             patch.object(chat_api, "complete", return_value="ok") as complete:
            r = self.client.post(ROUTES["CHAT"], json=self.ids(
                prompt="hello", check1=False, check2=False, check3=False, block_code=True,
                action_check1="allow", action_check2="allow", MODEL_NAME="other/model"))
            self.assertEqual(r.status_code, 200)
            screen.assert_called_once_with("hello", {"action_check1": "block", "action_check2": "block",
                                                     "action_check3": "block", "action_code": "allow"})
            self.assertEqual(complete.call_args.args[1], "gpt-4o-mini")

    def test_a_signed_in_member_can_read_their_own_settings(self):
        r = self.client.post(ROUTES["SETTINGS"], json=self.ids())
        self.assertEqual(r.status_code, 200)
        self.assertIn("MODEL_NAME", r.get_json())

    def test_a_member_cannot_change_policy_without_approval(self):
        """Weakening the gate is not the member's own decision to make."""
        for change in ({"check1": False}, {"MODEL_NAME": "gpt-4o"},
                       {"API_KEY": "sk-another"}, {"PROVIDER": "groq"}):
            with self.subTest(**change):
                r = self.client.post(ROUTES["SETTINGS"],
                                     json=self.ids(**change))
                self.assertEqual(r.status_code, 401)

    def test_policy_changes_work_once_approved(self):
        r = self.client.post(ROUTES["SETTINGS"],
                             json=self.ids(admin_token=self.admin,
                                           MODEL_NAME="gpt-4o-mini"))
        self.assertEqual(r.status_code, 200)

    def test_approval_from_another_workspace_is_refused(self):
        """An administrator may only approve inside their own workspace."""
        other = self.client.post(
            ROUTES["ADMIN_LOGIN"],
            json={"username": "boss", "password": "admin-pw"}).get_json()
        r = self.client.post(ROUTES["SETTINGS"],
                             json=self.ids(Parent_id=99,
                                           admin_token=other["session_token"],
                                           check1=False))
        self.assertNotEqual(r.status_code, 200)

    def test_signing_out_revokes_the_token_on_the_server(self):
        """Clearing localStorage alone would leave it replayable for a week."""
        login = self.client.post(
            ROUTES["EMPLOYEE_LOGIN"],
            json={"Parent_id": 1, "username": "member", "password": "member-pw"}
        ).get_json()
        token = login["session_token"]

        r = self.client.post(ROUTES["CHATS"], json=self.ids(
            Employee_id=int(login["Employee_id"]), session_token=token))
        self.assertEqual(r.status_code, 200, "the token works before sign-out")

        self.client.post(ROUTES["EMPLOYEE_LOGOUT"], json=self.ids(
            Employee_id=int(login["Employee_id"]), session_token=token))

        r = self.client.post(ROUTES["CHATS"], json=self.ids(
            Employee_id=int(login["Employee_id"]), session_token=token))
        self.assertEqual(r.status_code, 401, "the token is dead after sign-out")

    def test_a_single_member_can_be_signed_out(self):
        """Ending one session must not end everyone else's."""
        mine = auth.create_employee_session(DB, 1, 7)
        theirs = auth.create_employee_session(DB, 1, 7)
        self.assertTrue(auth.revoke_employee_session(DB, mine))
        self.assertIsNone(auth.member_from_token(DB, mine))
        self.assertIsNotNone(auth.member_from_token(DB, theirs))

    def test_revoking_a_junk_token_is_harmless(self):
        for token in ("", "   ", "nope", None, 12345, object()):
            with self.subTest(token=token):
                self.assertFalse(auth.revoke_employee_session(DB, token))

    def test_administrator_sessions_are_capped(self):
        """Each approval mints a session; they must not pile up forever."""
        import admin_session

        before = admin_session.MAX_SESSIONS_PER_ADMIN
        try:
            admin_session.MAX_SESSIONS_PER_ADMIN = 3
            tokens = [admin_session.create_session(DB, 4242) for _ in range(8)]
            # The newest survive; older ones are dropped, not accumulated.
            self.assertTrue(all(admin_session.create_session(DB, 4242)
                                for _ in range(2)))
            live = sum(1 for t in tokens
                       if auth.admin_from_token(DB, t) is not None)
            self.assertLessEqual(live, 3, "old sessions should be evicted")
        finally:
            admin_session.MAX_SESSIONS_PER_ADMIN = before

    def test_a_forged_approval_token_is_refused(self):
        r = self.client.post(ROUTES["SETTINGS"],
                             json=self.ids(admin_token="forged", check1=False))
        self.assertEqual(r.status_code, 401)

    def test_a_signed_in_member_can_read_their_own_history(self):
        r = self.client.post(ROUTES["CHATS"], json=self.ids())
        self.assertEqual(r.status_code, 200)
        self.assertIn("chats", r.get_json())

    def test_an_administrator_can_set_a_members_policy(self):
        r = self.client.post(ROUTES["SETTINGS"],
                             json=self.ids(session_token=self.admin,
                                           admin_token=self.admin,
                                           MODEL_NAME="gpt-4o-mini"))
        self.assertEqual(r.status_code, 200)

    def test_a_bad_base_url_is_refused(self):
        """The base URL is fetched by this server, so it gets checked."""
        for url in ("http://169.254.169.254/latest", "ftp://example.com",
                    "https://user:pw@example.com", "file:///etc/passwd"):
            with self.subTest(url=url):
                r = self.client.post(ROUTES["SETTINGS"],
                                     json=self.ids(admin_token=self.admin,
                                                   API_BASE=url))
                self.assertEqual(r.status_code, 400, url)

    def test_an_unknown_provider_is_refused(self):
        r = self.client.post(ROUTES["SETTINGS"],
                             json=self.ids(admin_token=self.admin,
                                           PROVIDER="made-up"))
        self.assertEqual(r.status_code, 400)

    def test_an_administrator_cannot_read_a_members_history(self):
        """Deliberate: policy is the administrator's job, the content is not."""
        r = self.client.post(ROUTES["CHATS"],
                             json=self.ids(session_token=self.admin))
        self.assertEqual(r.status_code, 401)

    def test_an_approved_override_goes_through_and_is_logged(self):
        r = self.client.post(ROUTES["CHAT"],
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
        r = self.client.post(ROUTES["CHAT"],
                             json=self.ids(prompt="Synthetic AFM fixture",
                                           check1=True, check2=True, check3=True))
        body = r.get_json()
        self.assertTrue(body["blocked"], "the stub scanner blocks everything")
        self.assertEqual(body.get("reply_message"), "NULL", "nothing is forwarded when blocked")

    def test_the_administrator_dashboard_still_works(self):
        r = self.client.post(ROUTES["TEAM"], json={"token": self.admin})
        self.assertEqual(r.status_code, 200)
        member = [m for m in r.get_json()["members"] if m["username"] == "member"][0]
        # A blocked prompt counts as a block; an approved override does not.
        self.assertEqual(member["blocked"], 1)
        self.assertEqual(member["overrides"], 1)


class MemberManagementTests(unittest.TestCase):
    """Adding or removing a member decides who may chat on a workspace's
    stored provider key, so POST /api/admin/employee needs that workspace's
    administrator — the two guessable integers on their own were enough."""

    @classmethod
    def setUpClass(cls):
        import sqlite3

        from passwords import hash_password

        con = sqlite3.connect(DB)
        # High, explicit ids: whatever else has run, this fixture neither
        # consumes nor depends on the low ids the other classes assume.
        cur = con.execute("INSERT INTO ADMINS (id, username, password) VALUES (900, ?, ?)",
                          ("mm_boss", hash_password("mm-pw")))
        cls.mm_parent = cur.lastrowid
        cur = con.execute("INSERT INTO ADMINS (id, username, password) VALUES (901, ?, ?)",
                          ("mm_foreign", hash_password("mm-pw")))
        cls.foreign_parent = cur.lastrowid
        con.commit()
        con.close()

        cls.client = cybersyn.app.test_client(use_cookies=False)
        cls.admin = cls.client.post(
            ROUTES["ADMIN_LOGIN"],
            json={"username": "mm_boss", "password": "mm-pw"},
        ).get_json()["session_token"]
        cls.foreign = cls.client.post(
            ROUTES["ADMIN_LOGIN"],
            json={"username": "mm_foreign", "password": "mm-pw"},
        ).get_json()["session_token"]

    def test_adding_a_member_without_an_admin_session_is_refused(self):
        r = self.client.post(ROUTES["EMPLOYEE"],
                             json={"method": "add", "Parent_id": self.mm_parent,
                                   "username": "intruder", "password": "pw-12345a"})
        self.assertEqual(r.status_code, 401)

    def test_adding_a_member_with_the_admin_session_is_allowed(self):
        r = self.client.post(ROUTES["EMPLOYEE"],
                             json={"method": "add", "Parent_id": self.mm_parent,
                                   "username": "legit", "password": "pw-12345a",
                                   "token": self.admin})
        self.assertEqual(r.status_code, 201)

    def test_an_admin_of_another_workspace_is_refused(self):
        r = self.client.post(ROUTES["EMPLOYEE"],
                             json={"method": "add", "Parent_id": self.mm_parent,
                                   "username": "intruder2", "password": "pw-12345a",
                                   "token": self.foreign})
        self.assertEqual(r.status_code, 401)

    def test_removing_a_member_without_an_admin_session_is_refused(self):
        r = self.client.post(ROUTES["EMPLOYEE"],
                             json={"method": "remove", "Parent_id": self.mm_parent,
                                   "username": "legit", "password": "pw-12345a"})
        self.assertEqual(r.status_code, 401)

    def test_removing_a_member_with_the_admin_session_is_allowed(self):
        self.client.post(ROUTES["EMPLOYEE"],
                         json={"method": "add", "Parent_id": self.mm_parent,
                               "username": "throwaway", "password": "pw-12345a",
                               "token": self.admin})
        r = self.client.post(ROUTES["EMPLOYEE"],
                             json={"method": "remove", "Parent_id": self.mm_parent,
                                   "username": "throwaway", "admin_password": "mm-pw",
                                   "token": self.admin})
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
