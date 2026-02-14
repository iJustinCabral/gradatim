"""Tests for the web frontend store and server."""

import json
import http.client
import threading
import time
import unittest

from gradatim.web.store import Store
from gradatim.web.server import run_server, _make_handler

import http.server


class TestStore(unittest.TestCase):
    """Test the in-memory data store."""

    def setUp(self):
        self.store = Store()

    def test_seed_data(self):
        jobs = self.store.list_jobs()
        self.assertGreaterEqual(len(jobs), 3)

        invites = self.store.list_invites()
        available = [i for i in invites if not i["redeemed_by"]]
        self.assertGreaterEqual(len(available), 5)

    def test_create_user(self):
        uid = self.store.create_user("alice")
        user = self.store.get_user(uid)
        self.assertEqual(user["handle"], "alice")
        self.assertFalse(user["is_system"])

    def test_user_by_handle(self):
        self.store.create_user("bob")
        user = self.store.get_user_by_handle("bob")
        self.assertIsNotNone(user)
        self.assertEqual(user["handle"], "bob")

    def test_sessions(self):
        uid = self.store.create_user("charlie")
        token = self.store.create_session(uid)
        self.assertEqual(self.store.get_session_user(token), uid)
        self.store.delete_session(token)
        self.assertIsNone(self.store.get_session_user(token))

    def test_invite_redeem(self):
        uid = self.store.create_user("admin")
        code = self.store.create_invite(created_by=uid)
        ok, result = self.store.redeem_invite(code, "newuser")
        self.assertTrue(ok)
        user = self.store.get_user(result)
        self.assertEqual(user["handle"], "newuser")

    def test_invite_double_redeem(self):
        uid = self.store.create_user("admin2")
        code = self.store.create_invite(created_by=uid)
        ok1, _ = self.store.redeem_invite(code, "user1")
        self.assertTrue(ok1)
        ok2, msg = self.store.redeem_invite(code, "user2")
        self.assertFalse(ok2)
        self.assertIn("already been used", msg)

    def test_invite_invalid_code(self):
        ok, msg = self.store.redeem_invite("nonexistent", "someone")
        self.assertFalse(ok)

    def test_invite_duplicate_handle(self):
        uid = self.store.create_user("admin3")
        code1 = self.store.create_invite(created_by=uid)
        code2 = self.store.create_invite(created_by=uid)
        ok1, _ = self.store.redeem_invite(code1, "dupehandle")
        self.assertTrue(ok1)
        ok2, msg = self.store.redeem_invite(code2, "dupehandle")
        self.assertFalse(ok2)
        self.assertIn("already taken", msg)

    def test_create_and_list_jobs(self):
        uid = self.store.create_user("poster")
        job_id = self.store.create_job(
            posted_by=uid, title="Test Job", category="factorization",
            description="test", params={"n": 42},
        )
        job = self.store.get_job(job_id)
        self.assertEqual(job["title"], "Test Job")
        self.assertEqual(job["status"], "open")

        jobs = self.store.list_jobs(category="factorization")
        ids = [j["id"] for j in jobs]
        self.assertIn(job_id, ids)

    def test_claim_job(self):
        uid = self.store.create_user("claimer")
        job_id = self.store.create_job(
            posted_by=uid, title="Claim Me", category="factorization",
            description="", params={"n": 100},
        )
        ok, msg = self.store.claim_job(job_id, uid)
        self.assertTrue(ok)
        job = self.store.get_job(job_id)
        self.assertEqual(job["status"], "claimed")

        # Double-claim should fail
        ok2, msg2 = self.store.claim_job(job_id, uid)
        self.assertFalse(ok2)

    def test_update_job_status(self):
        uid = self.store.create_user("solver")
        job_id = self.store.create_job(
            posted_by=uid, title="Solve Me", category="factorization",
            description="", params={"n": 15},
        )
        self.store.claim_job(job_id, uid)
        self.store.update_job_status(job_id, "solved", {"factors": [3, 5]})
        job = self.store.get_job(job_id)
        self.assertEqual(job["status"], "solved")
        self.assertEqual(job["result"]["factors"], [3, 5])

    def test_compute_config(self):
        uid = self.store.create_user("configuser")
        config = self.store.get_compute_config(uid)
        self.assertEqual(config["backend"], "local")

        self.store.update_compute_config(uid, {
            "backend": "openai",
            "api_key": "sk-test",
            "model_name": "gpt-4",
        })
        config = self.store.get_compute_config(uid)
        self.assertEqual(config["backend"], "openai")
        self.assertEqual(config["api_key"], "sk-test")

    def test_stats(self):
        stats = self.store.get_stats()
        self.assertIn("total_jobs", stats)
        self.assertIn("open_jobs", stats)
        self.assertIn("total_users", stats)


class TestWebServer(unittest.TestCase):
    """Test the HTTP server serves pages and API endpoints."""

    @classmethod
    def setUpClass(cls):
        cls.store = Store()
        handler = _make_handler(cls.store, agent=None)
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path: str) -> http.client.HTTPResponse:
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp

    def _post_form(self, path: str, data: dict,
                   cookie: str = "") -> http.client.HTTPResponse:
        body = "&".join(f"{k}={v}" for k, v in data.items())
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if cookie:
            headers["Cookie"] = cookie
        conn.request("POST", path, body=body, headers=headers)
        return conn.getresponse()

    def test_homepage_loads(self):
        resp = self._get("/")
        self.assertEqual(resp.status, 200)
        body = resp.read().decode()
        self.assertIn("gradatim", body)
        self.assertIn("problem board", body)

    def test_static_css(self):
        resp = self._get("/static/style.css")
        self.assertEqual(resp.status, 200)
        body = resp.read().decode()
        self.assertIn("Craigslist", body)

    def test_join_page(self):
        resp = self._get("/join")
        self.assertEqual(resp.status, 200)
        body = resp.read().decode()
        self.assertIn("invite code", body)

    def test_login_page(self):
        resp = self._get("/login")
        self.assertEqual(resp.status, 200)
        body = resp.read().decode()
        self.assertIn("handle", body)

    def test_status_page(self):
        resp = self._get("/status")
        self.assertEqual(resp.status, 200)
        body = resp.read().decode()
        self.assertIn("network status", body)

    def test_api_jobs(self):
        resp = self._get("/api/jobs")
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode())
        self.assertIn("jobs", data)
        self.assertIsInstance(data["jobs"], list)

    def test_api_stats(self):
        resp = self._get("/api/stats")
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode())
        self.assertIn("total_jobs", data)

    def test_join_flow(self):
        # Get an available invite code from the store
        invites = self.store.list_invites()
        available = [i for i in invites if not i["redeemed_by"]]
        self.assertTrue(len(available) > 0)
        code = available[0]["code"]

        # Redeem it
        resp = self._post_form("/join", {
            "code": code,
            "handle": "webtest_user",
        })
        # Should redirect (303)
        self.assertIn(resp.status, [303, 302])

    def test_404(self):
        resp = self._get("/nonexistent")
        self.assertEqual(resp.status, 404)

    def test_seeded_job_detail(self):
        jobs = self.store.list_jobs()
        self.assertTrue(len(jobs) > 0)
        job_id = jobs[0]["id"]
        resp = self._get(f"/job/{job_id}")
        self.assertEqual(resp.status, 200)
        body = resp.read().decode()
        self.assertIn(jobs[0]["title"], body)


if __name__ == "__main__":
    unittest.main()
