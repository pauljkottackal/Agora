import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# pick a free port before importing dashboard (it builds its Host allow-list from AGORA_PORT)
with socket.socket() as _s:
    _s.bind(("127.0.0.1", 0))
    PORT = _s.getsockname()[1]
os.environ["AGORA_PORT"] = str(PORT)
os.environ["COORD_DB"] = os.path.join(tempfile.mkdtemp(), "dash.db")

import dashboard as d  # noqa: E402
import server as s  # noqa: E402


class DashboardAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with s.db():
            pass
        cls.httpd = d.ThreadingHTTPServer(("127.0.0.1", PORT), d.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        h = {"Host": f"127.0.0.1:{PORT}", **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body)
            h.setdefault("Content-Type", "application/json")
        c.request(method, path, data, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, raw

    def test_page_and_state(self):
        st, html = self.req("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(b"Agora", html)
        st, state = self.req("GET", "/api/state")
        self.assertEqual(st, 200)
        for k in ("tasks", "agents", "locks", "messages", "events"):
            self.assertIn(k, state)

    def test_rejects_foreign_host(self):
        st, _ = self.req("GET", "/api/state", headers={"Host": "evil.example"})
        self.assertEqual(st, 403)

    def test_post_requires_json_content_type(self):
        st, _ = self.req("POST", "/api/task", body={"title": "x"}, headers={"Content-Type": "text/plain"})
        self.assertEqual(st, 415)

    def test_create_task_message_and_unblock(self):
        st, r = self.req("POST", "/api/task", {"title": "  "})
        self.assertEqual(st, 400)
        st, r = self.req("POST", "/api/task", {"title": "From UI", "description": "d"})
        self.assertEqual((st, r["ok"]), (200, True))
        tid = r["task_id"]
        st, r = self.req("POST", "/api/message", {"body": "hello", "to": "codex", "task_id": tid})
        self.assertEqual((st, r["ok"]), (200, True))
        st, state = self.req("GET", "/api/state")
        self.assertTrue(any(m["body"] == "hello" and m["from_agent"] == "human" for m in state["messages"]))
        st, r = self.req("POST", "/api/unblock", {"task_id": tid})
        self.assertEqual(st, 400)  # not blocked

    def test_unblock_resets_counter(self):
        os.environ["AGENT_ID"] = "codex"
        old = s.MAX_MSGS_PER_TASK
        s.MAX_MSGS_PER_TASK = 2
        try:
            tid = s.create_task("loop")["task_id"]
            s.claim_task(tid)
            s.post_message("a", task_id=tid)
            s.post_message("b", task_id=tid)
            self.assertFalse(s.post_message("c", task_id=tid)["ok"])  # blocked now
            os.environ["AGENT_ID"] = "human"
            st, r = self.req("POST", "/api/unblock", {"task_id": tid})
            self.assertEqual((st, r["status"]), (200, "in_progress"))
            os.environ["AGENT_ID"] = "codex"
            self.assertTrue(s.post_message("d", task_id=tid)["ok"])
        finally:
            s.MAX_MSGS_PER_TASK = old
            os.environ["AGENT_ID"] = "human"


if __name__ == "__main__":
    unittest.main(verbosity=2)
