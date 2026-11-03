#!/usr/bin/env python3
"""
Agora dashboard: a local web UI for the Agora coordinator database.

    python dashboard.py            # http://127.0.0.1:8765
    AGORA_PORT=9000 python dashboard.py

Uses only the standard library. Binds to 127.0.0.1 and rejects requests whose Host
header isn't localhost (DNS-rebinding guard) and POSTs that aren't JSON (cross-site guard).
Everything you do here is recorded as the agent "human".
"""
import json
import os
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["AGENT_ID"] = "human"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server as s  # noqa: E402

PORT = int(os.environ.get("AGORA_PORT", "8765"))
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
MAX_BODY = 64 * 1024


def read_state():
    """Read-only snapshot. Uses a plain connection so polling doesn't count as agent activity."""
    conn = sqlite3.connect(s._db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        q = lambda sql, *a: [dict(r) for r in conn.execute(sql, a)]
        return {
            "now": s._now(),
            "db": s._db_path(),
            "max_msgs": s.MAX_MSGS_PER_TASK,
            "tasks": q("SELECT * FROM tasks ORDER BY id"),
            "agents": q("SELECT * FROM agents ORDER BY id"),
            "locks": q("SELECT * FROM file_locks WHERE expires_at >= ? ORDER BY path", s._now()),
            "messages": q(
                "SELECT m.*, t.title AS task_title FROM messages m "
                "LEFT JOIN tasks t ON t.id = m.task_id ORDER BY m.id DESC LIMIT 150"
            )[::-1],
            "events": q("SELECT * FROM events ORDER BY id DESC LIMIT 60"),
        }
    finally:
        conn.close()


def as_int(v, default=0):
    try:
        return int(v or default)
    except (TypeError, ValueError):
        return default


class Handler(BaseHTTPRequestHandler):
    server_version = "Agora"

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _host_ok(self):
        if self.headers.get("Host") in ALLOWED_HOSTS:
            return True
        self._send(403, {"ok": False, "error": "bad host"})
        return False

    def do_GET(self):
        if not self._host_ok():
            return
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "dashboard.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif self.path.startswith("/api/state"):
            self._send(200, read_state())
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if not self._host_ok():
            return
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._send(415, {"ok": False, "error": "JSON only"})
        n = as_int(self.headers.get("Content-Length"))
        if n > MAX_BODY:
            return self._send(413, {"ok": False, "error": "too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._send(400, {"ok": False, "error": "bad json"})

        if self.path == "/api/task":
            title = (body.get("title") or "").strip()
            if not title:
                return self._send(400, {"ok": False, "error": "title is required"})
            r = s.create_task(
                title, (body.get("description") or "").strip(), as_int(body.get("depends_on"))
            )
        elif self.path == "/api/message":
            text = (body.get("body") or "").strip()
            if not text:
                return self._send(400, {"ok": False, "error": "message is empty"})
            r = s.post_message(
                text, to=(body.get("to") or "").strip(), task_id=as_int(body.get("task_id"))
            )
        elif self.path == "/api/unblock":
            r = s.unblock_task(as_int(body.get("task_id")))
        else:
            return self._send(404, {"ok": False, "error": "not found"})
        self._send(200 if r.get("ok") else 400, r)


def main():
    with s.db():  # make sure the schema exists
        pass
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Agora dashboard: http://127.0.0.1:{PORT}   (db: {s._db_path()})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
