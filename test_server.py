import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server as s


def as_agent(name):
    os.environ["AGENT_ID"] = name


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["COORD_DB"] = os.path.join(self.tmp, "t.db")
        as_agent("codex")

    def new_task(self, **kw):
        return s.create_task("t", **kw)["task_id"]

    def test_claim_is_exclusive(self):
        t = self.new_task()
        self.assertTrue(s.claim_task(t)["ok"])
        as_agent("antigravity")
        r = s.claim_task(t)
        self.assertFalse(r["ok"])

    def test_dependency_blocks_claim(self):
        a = self.new_task()
        b = self.new_task(depends_on=a)
        self.assertFalse(s.claim_task(b)["ok"])

    def test_cannot_set_done_directly(self):
        t = self.new_task()
        s.claim_task(t)
        self.assertFalse(s.update_status(t, "done")["ok"])
        self.assertFalse(s.update_status(t, "review")["ok"])

    def test_full_review_flow_and_dependency_unlock(self):
        a = self.new_task()
        b = self.new_task(depends_on=a)
        s.claim_task(a)
        self.assertFalse(s.request_review(a, "codex")["ok"])  # self-review blocked
        self.assertTrue(s.request_review(a, "antigravity")["ok"])
        as_agent("codex")
        self.assertFalse(s.submit_review(a, "approve")["ok"])  # not the reviewer
        as_agent("antigravity")
        self.assertTrue(s.submit_review(a, "changes_requested", "fix x")["ok"])
        as_agent("codex")
        self.assertEqual(s.list_tasks(owner="codex")[0]["status"], "changes_requested")
        self.assertTrue(s.request_review(a, "antigravity")["ok"])
        as_agent("antigravity")
        r = s.submit_review(a, "approve")
        self.assertEqual(r["status"], "done")
        self.assertTrue(s.claim_task(b)["ok"])  # dependency now satisfied

    def test_inbox_direct_and_broadcast(self):
        s.post_message("hi all")
        s.post_message("just you", to="antigravity")
        s.post_message("not yours", to="claude")
        as_agent("antigravity")
        r = s.read_inbox()
        self.assertEqual(r["count"], 2)
        self.assertEqual(s.read_inbox()["count"], 0)  # marked read
        as_agent("claude")
        self.assertEqual(s.read_inbox()["count"], 2)  # broadcast + its own
        as_agent("codex")
        self.assertEqual(s.read_inbox()["count"], 0)  # own broadcast not echoed

    def test_locks(self):
        self.assertTrue(s.lock_files(["src/a.py", "./src/b.py"])["ok"])
        as_agent("antigravity")
        r = s.lock_files(["src/c.py", "src/b.py"])
        self.assertFalse(r["ok"])
        self.assertEqual(len(r["conflicts"]), 1)
        self.assertEqual(len(s.list_locks()), 2)  # all-or-nothing: c.py not locked
        as_agent("codex")
        s.unlock_files(["src/a.py"])
        self.assertEqual(len(s.list_locks()), 1)

    def test_expired_lock_is_ignored(self):
        s.lock_files(["x.py"])
        import sqlite3
        c = sqlite3.connect(os.environ["COORD_DB"])
        c.execute("UPDATE file_locks SET expires_at='2000-01-01T00:00:00+00:00'")
        c.commit()
        c.close()
        as_agent("antigravity")
        self.assertTrue(s.lock_files(["x.py"])["ok"])

    def test_handoff_transfers_ownership_and_releases_locks(self):
        t = self.new_task()
        s.claim_task(t)
        s.lock_files(["a.py"], task_id=t)
        r = s.handoff(t, "antigravity", "did A", ["a.py"], "do B", "run tests")
        self.assertTrue(r["ok"])
        self.assertEqual(s.list_locks(), [])
        as_agent("antigravity")
        msgs = s.read_inbox()["messages"]
        self.assertEqual(msgs[0]["kind"], "handoff")
        self.assertIn("do B", msgs[0]["body"])
        self.assertEqual(s.list_tasks(owner="antigravity")[0]["id"], t)

    def test_message_cap_blocks_task_and_human_unblocks(self):
        os.environ["COORD_DB"] = os.path.join(self.tmp, "cap.db")
        s.MAX_MSGS_PER_TASK = 3
        try:
            t = self.new_task()
            s.claim_task(t)
            for _ in range(3):
                self.assertTrue(s.post_message("ping", task_id=t)["ok"])
            r = s.post_message("one too many", task_id=t)
            self.assertFalse(r["ok"])
            self.assertEqual(s.list_tasks()[0]["status"], "blocked")
            s._cli(["unblock", str(t)])
            as_agent("codex")
            self.assertEqual(s.list_tasks()[0]["status"], "in_progress")
            self.assertTrue(s.post_message("fresh", task_id=t)["ok"])
        finally:
            s.MAX_MSGS_PER_TASK = 20


    # ---- listening mode (wait_for_work)
    def test_wait_returns_immediately_when_message_waiting(self):
        import time
        s.post_message("ping", to="antigravity")
        as_agent("antigravity")
        t0 = time.monotonic()
        r = s.wait_for_work(10)
        self.assertTrue(r["woke"])
        self.assertLess(time.monotonic() - t0, 2)
        self.assertEqual(r["messages"][0]["body"], "ping")
        self.assertFalse(s.wait_for_work(0)["woke"])  # already consumed

    def test_wait_times_out_quietly(self):
        as_agent("antigravity")
        r = s.wait_for_work(0)
        self.assertFalse(r["woke"])
        self.assertEqual(r["messages"], [])
        self.assertIn("again", r["next"])

    def test_wait_wakes_when_message_arrives_later(self):
        import sqlite3, threading, time
        as_agent("antigravity")
        s.heartbeat()  # make sure the schema exists
        s.POLL_SECONDS = 0.05

        def late_sender():
            time.sleep(0.4)
            c = sqlite3.connect(os.environ["COORD_DB"])
            c.execute("INSERT INTO messages(from_agent,to_agent,kind,body,created_at) VALUES('codex','antigravity','note','hello later',?)", (s._now(),))
            c.commit(); c.close()

        threading.Thread(target=late_sender, daemon=True).start()
        t0 = time.monotonic()
        try:
            r = s.wait_for_work(10)
        finally:
            s.POLL_SECONDS = 1.0
        self.assertTrue(r["woke"])
        self.assertEqual(r["messages"][0]["body"], "hello later")
        self.assertLess(time.monotonic() - t0, 3)

    def test_wait_wakes_on_new_ready_task_from_someone_else(self):
        import sqlite3, threading, time
        as_agent("antigravity")
        s.heartbeat()
        s.POLL_SECONDS = 0.05

        def late_creator():
            time.sleep(0.3)
            c = sqlite3.connect(os.environ["COORD_DB"])
            c.execute("INSERT INTO tasks(title,status,created_by,created_at,updated_at) VALUES('new work','todo','human',?,?)", (s._now(), s._now()))
            c.commit(); c.close()

        threading.Thread(target=late_creator, daemon=True).start()
        try:
            r = s.wait_for_work(10)
        finally:
            s.POLL_SECONDS = 1.0
        self.assertTrue(r["woke"])
        self.assertEqual(r["new_tasks"][0]["title"], "new work")

    def test_wait_does_not_wake_on_own_task(self):
        as_agent("antigravity")
        s.create_task("mine")
        self.assertFalse(s.wait_for_work(0)["woke"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
