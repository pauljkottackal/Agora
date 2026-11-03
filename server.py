#!/usr/bin/env python3
"""
Agora: a tiny MCP server that lets several AI coding agents
(Antigravity, Codex, Claude Code, ...) share a task board, message each other,
hand work off, review each other's work and avoid editing the same files.

Run as an MCP server (stdio):     python server.py
Human CLI:                        python server.py board | create | msg | unblock | log

Each agent's MCP config sets AGENT_ID (and optionally AGENT_ROLE) in `env`,
and all of them point COORD_DB at the same SQLite file.
"""
import contextlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coordinator.db")

LOCK_TTL_MIN = int(os.environ.get("LOCK_TTL_MIN", "30"))
POLL_SECONDS = float(os.environ.get("AGORA_POLL", "1.0"))   # wait_for_work check interval
MAX_WAIT_SECONDS = 50                                       # stay under typical tool timeouts
MAX_MSGS_PER_TASK = int(os.environ.get("MAX_MSGS_PER_TASK", "20"))

# Statuses an agent may set directly with update_status.
# 'review' goes through request_review, 'done' only through an approving submit_review.
SETTABLE_STATUSES = {"todo", "in_progress", "blocked"}
ALL_STATUSES = {"todo", "in_progress", "review", "changes_requested", "done", "blocked"}
MESSAGE_KINDS = {"note", "question", "handoff", "review"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  role TEXT,
  last_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  description TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'todo',
  owner TEXT,
  reviewer TEXT,
  approved_by TEXT,
  branch TEXT,
  depends_on INTEGER,
  msg_floor INTEGER NOT NULL DEFAULT 0,
  created_by TEXT,
  created_at TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER,
  from_agent TEXT NOT NULL,
  to_agent TEXT,
  kind TEXT NOT NULL DEFAULT 'note',
  body TEXT NOT NULL,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS message_reads (
  message_id INTEGER NOT NULL,
  agent_id TEXT NOT NULL,
  PRIMARY KEY (message_id, agent_id)
);
CREATE TABLE IF NOT EXISTS file_locks (
  path TEXT PRIMARY KEY,
  task_id INTEGER,
  owner TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent TEXT,
  action TEXT,
  payload TEXT,
  at TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_task ON messages(task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""

_initialised_for = set()


# ---------------------------------------------------------------- helpers
def _db_path():
    return os.environ.get("COORD_DB", DEFAULT_DB)


def _agent():
    # read at call time so tests (and the CLI) can switch identity
    return os.environ.get("AGENT_ID", "unknown")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _in(minutes):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(timespec="seconds")


@contextlib.contextmanager
def db():
    """One transaction per tool call. BEGIN IMMEDIATE serialises writers,
    which is what makes claim_task / lock_files race-free."""
    path = _db_path()
    conn = sqlite3.connect(path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        if path not in _initialised_for:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            _initialised_for.add(path)
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "INSERT INTO agents(id, role, last_seen_at) VALUES(?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET last_seen_at=excluded.last_seen_at, "
                "role=COALESCE(excluded.role, agents.role)",
                (_agent(), os.environ.get("AGENT_ROLE"), _now()),
            )
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def _log(c, action, payload=None):
    c.execute(
        "INSERT INTO events(agent, action, payload, at) VALUES(?,?,?,?)",
        (_agent(), action, json.dumps(payload or {}), _now()),
    )


def _task(c, task_id):
    row = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row) if row else None


def _err(msg, **extra):
    return {"ok": False, "error": msg, **extra}


def _ok(**kw):
    return {"ok": True, **kw}


def _norm_path(p):
    p = p.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p


def _purge_expired_locks(c):
    c.execute("DELETE FROM file_locks WHERE expires_at < ?", (_now(),))


def _insert_message(c, task_id, to_agent, kind, body):
    """Insert a message, enforcing the per-task message cap (loop guard).
    Human messages are exempt. Returns (ok, error_dict_or_None)."""
    me = _agent()
    if task_id is not None and me != "human":
        t = _task(c, task_id)
        if not t:
            return False, _err(f"task {task_id} not found")
        n = c.execute(
            "SELECT COUNT(*) FROM messages WHERE task_id=? AND id>? AND from_agent!='human'",
            (task_id, t["msg_floor"]),
        ).fetchone()[0]
        if n >= MAX_MSGS_PER_TASK:
            if t["status"] != "blocked":
                c.execute(
                    "UPDATE tasks SET status='blocked', updated_at=? WHERE id=?",
                    (_now(), task_id),
                )
                _log(c, "loop_guard_blocked", {"task_id": task_id, "messages": n})
            return False, _err(
                f"Task {task_id} hit the {MAX_MSGS_PER_TASK}-message cap and is now "
                "'blocked'. Stop messaging and ask the human to run: "
                f"python server.py unblock {task_id}"
            )
    c.execute(
        "INSERT INTO messages(task_id, from_agent, to_agent, kind, body, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (task_id, me, to_agent, kind, body, _now()),
    )
    return True, None


def _release_locks(c, owner, task_id=None):
    if task_id is None:
        c.execute("DELETE FROM file_locks WHERE owner=?", (owner,))
    else:
        c.execute("DELETE FROM file_locks WHERE owner=? AND task_id=?", (owner, task_id))


# ---------------------------------------------------------------- MCP tools
try:  # mcp SDK 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    try:  # mcp SDK 1.x
        from mcp.server.fastmcp import FastMCP
    except ImportError:  # allow the CLI to work without the SDK installed
        FastMCP = None


class _NoMCP:
    def tool(self, *a, **k):
        return lambda f: f

    def run(self, *a, **k):
        sys.exit("The 'mcp' package is not installed. Run: pip install mcp")


mcp = FastMCP("agora") if FastMCP else _NoMCP()


@mcp.tool()
def whoami() -> dict:
    """Show who you are to the coordinator, your unread message count, and your open tasks.
    Call this first in every session."""
    me = _agent()
    with db() as c:
        unread = _count_unread(c, me)
        mine = [
            dict(r)
            for r in c.execute(
                "SELECT id, title, status FROM tasks WHERE owner=? AND status!='done'", (me,)
            )
        ]
        awaiting = [
            dict(r)
            for r in c.execute(
                "SELECT id, title FROM tasks WHERE reviewer=? AND status='review'", (me,)
            )
        ]
    return _ok(agent_id=me, unread_messages=unread, my_open_tasks=mine, awaiting_my_review=awaiting)


@mcp.tool()
def heartbeat() -> dict:
    """Mark yourself as active. Every tool call also does this; use it during long work."""
    with db():
        pass
    return _ok(agent_id=_agent(), at=_now())


@mcp.tool()
def board() -> dict:
    """Overview: tasks grouped by status, agents with last-seen time, active file locks."""
    with db() as c:
        _purge_expired_locks(c)
        tasks = [dict(r) for r in c.execute("SELECT * FROM tasks ORDER BY id")]
        agents = [dict(r) for r in c.execute("SELECT * FROM agents ORDER BY id")]
        locks = [dict(r) for r in c.execute("SELECT * FROM file_locks ORDER BY path")]
    grouped = {}
    for t in tasks:
        grouped.setdefault(t["status"], []).append(
            {k: t[k] for k in ("id", "title", "owner", "reviewer", "depends_on")}
        )
    return _ok(tasks_by_status=grouped, agents=agents, locks=locks)


@mcp.tool()
def list_tasks(status: str = "", owner: str = "") -> list:
    """List tasks, optionally filtered by status (todo, in_progress, review,
    changes_requested, done, blocked) and/or owner."""
    q, args = "SELECT * FROM tasks WHERE 1=1", []
    if status:
        q += " AND status=?"
        args.append(status)
    if owner:
        q += " AND owner=?"
        args.append(owner)
    with db() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY id", args)]


@mcp.tool()
def create_task(title: str, description: str = "", depends_on: int = 0, branch: str = "") -> dict:
    """Add a task. Put the goal and acceptance criteria in `description`.
    `depends_on` is a task id that must be 'done' before this one can be claimed (0 = none)."""
    with db() as c:
        if depends_on and not _task(c, depends_on):
            return _err(f"depends_on task {depends_on} not found")
        cur = c.execute(
            "INSERT INTO tasks(title, description, depends_on, branch, created_by, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (title, description, depends_on or None, branch or None, _agent(), _now(), _now()),
        )
        _log(c, "create_task", {"task_id": cur.lastrowid, "title": title})
        return _ok(task_id=cur.lastrowid)


@mcp.tool()
def claim_task(task_id: int) -> dict:
    """Atomically take a 'todo' task. Fails if someone else already has it or if the
    task it depends on is not 'done'."""
    me = _agent()
    with db() as c:
        t = _task(c, task_id)
        if not t:
            return _err(f"task {task_id} not found")
        if t["status"] != "todo":
            return _err(f"task {task_id} is '{t['status']}' (owner: {t['owner']}); only 'todo' tasks can be claimed")
        if t["depends_on"]:
            dep = _task(c, t["depends_on"])
            if not dep or dep["status"] != "done":
                return _err(f"depends on task {t['depends_on']} which is not done yet")
        c.execute(
            "UPDATE tasks SET owner=?, status='in_progress', updated_at=? WHERE id=? AND status='todo'",
            (me, _now(), task_id),
        )
        _log(c, "claim_task", {"task_id": task_id})
        return _ok(task_id=task_id, owner=me, status="in_progress")


@mcp.tool()
def update_status(task_id: int, status: str, note: str = "") -> dict:
    """Owner-only. Set a task to todo (releases it), in_progress, or blocked.
    Use request_review to go to review; 'done' is only reachable via an approving review."""
    me = _agent()
    if status == "done":
        return _err("'done' can only be reached through request_review -> submit_review(approve)")
    if status == "review":
        return _err("use request_review(task_id, reviewer) to move a task to review")
    if status not in SETTABLE_STATUSES:
        return _err(f"status must be one of {sorted(SETTABLE_STATUSES)}")
    with db() as c:
        t = _task(c, task_id)
        if not t:
            return _err(f"task {task_id} not found")
        if t["owner"] != me:
            return _err(f"only the owner ({t['owner']}) can update task {task_id}")
        if t["status"] == "blocked" and me != "human":
            return _err("task is blocked; a human must run: python server.py unblock %d" % task_id)
        owner = None if status == "todo" else me
        c.execute(
            "UPDATE tasks SET status=?, owner=?, updated_at=? WHERE id=?",
            (status, owner, _now(), task_id),
        )
        if status == "todo":
            _release_locks(c, me, task_id)
        if note:
            ok, e = _insert_message(c, task_id, None, "note", note)
            if not ok:
                return e
        _log(c, "update_status", {"task_id": task_id, "status": status})
        return _ok(task_id=task_id, status=status)


@mcp.tool()
def post_message(body: str, to: str = "", task_id: int = 0, kind: str = "note") -> dict:
    """Send a message. `to` = agent id, or empty to broadcast. `task_id` = 0 for the general
    channel. kind: note | question | handoff | review. Each task has a cap on agent
    messages (default 20); hitting it blocks the task and requires a human."""
    if kind not in MESSAGE_KINDS:
        return _err(f"kind must be one of {sorted(MESSAGE_KINDS)}")
    with db() as c:
        ok, e = _insert_message(c, task_id or None, to or None, kind, body)
        if not ok:
            return e
        _log(c, "post_message", {"to": to or "*", "task_id": task_id or None, "kind": kind})
        return _ok(sent=True)


def _count_unread(c, me):
    return c.execute(
        "SELECT COUNT(*) FROM messages m WHERE (m.to_agent=? OR (m.to_agent IS NULL AND m.from_agent!=?)) "
        "AND NOT EXISTS (SELECT 1 FROM message_reads r WHERE r.message_id=m.id AND r.agent_id=?)",
        (me, me, me),
    ).fetchone()[0]


@mcp.tool()
def read_inbox(mark_read: bool = True, limit: int = 50) -> dict:
    """Fetch unread messages addressed to you plus broadcasts from others.
    Call at the start of every task and after finishing each step."""
    me = _agent()
    with db() as c:
        rows = c.execute(
            "SELECT m.* FROM messages m WHERE (m.to_agent=? OR (m.to_agent IS NULL AND m.from_agent!=?)) "
            "AND NOT EXISTS (SELECT 1 FROM message_reads r WHERE r.message_id=m.id AND r.agent_id=?) "
            "ORDER BY m.id LIMIT ?",
            (me, me, me, limit),
        ).fetchall()
        msgs = [dict(r) for r in rows]
        if mark_read:
            c.executemany(
                "INSERT OR IGNORE INTO message_reads(message_id, agent_id) VALUES(?,?)",
                [(m["id"], me) for m in msgs],
            )
        return _ok(count=len(msgs), messages=msgs)


@mcp.tool()
def handoff(task_id: int, to: str, summary: str, files_touched: list[str],
            remaining: str, verify: str) -> dict:
    """Owner-only. Transfer a task to another agent with explicit context so nothing is lost.
    `summary` = what was done, `remaining` = what is left, `verify` = how to check it works."""
    me = _agent()
    if to == me:
        return _err("cannot hand off to yourself")
    with db() as c:
        t = _task(c, task_id)
        if not t:
            return _err(f"task {task_id} not found")
        if t["owner"] != me:
            return _err(f"only the owner ({t['owner']}) can hand off task {task_id}")
        if t["status"] not in ("in_progress", "changes_requested"):
            return _err(f"cannot hand off a task that is '{t['status']}'")
        body = (
            f"HANDOFF task #{task_id} '{t['title']}'\n"
            f"Summary: {summary}\n"
            f"Files touched: {', '.join(files_touched) or '(none)'}\n"
            f"Remaining: {remaining}\n"
            f"Verify: {verify}"
        )
        ok, e = _insert_message(c, task_id, to, "handoff", body)
        if not ok:
            return e
        _release_locks(c, me, task_id)
        c.execute(
            "UPDATE tasks SET owner=?, status='in_progress', updated_at=? WHERE id=?",
            (to, _now(), task_id),
        )
        _log(c, "handoff", {"task_id": task_id, "to": to})
        return _ok(task_id=task_id, new_owner=to)


@mcp.tool()
def request_review(task_id: int, reviewer: str, note: str = "") -> dict:
    """Owner-only. Move a task to 'review' and notify the reviewer (must be a different agent).
    Releases your file locks on this task."""
    me = _agent()
    if reviewer == me:
        return _err("the reviewer must be a different agent than the owner")
    with db() as c:
        t = _task(c, task_id)
        if not t:
            return _err(f"task {task_id} not found")
        if t["owner"] != me:
            return _err(f"only the owner ({t['owner']}) can request review for task {task_id}")
        if t["status"] not in ("in_progress", "changes_requested"):
            return _err(f"cannot request review for a task that is '{t['status']}'")
        ok, e = _insert_message(
            c, task_id, reviewer, "review",
            f"Please review task #{task_id} '{t['title']}'. {note}".strip(),
        )
        if not ok:
            return e
        _release_locks(c, me, task_id)
        c.execute(
            "UPDATE tasks SET status='review', reviewer=?, approved_by=NULL, updated_at=? WHERE id=?",
            (reviewer, _now(), task_id),
        )
        _log(c, "request_review", {"task_id": task_id, "reviewer": reviewer})
        return _ok(task_id=task_id, status="review", reviewer=reviewer)


@mcp.tool()
def submit_review(task_id: int, verdict: str, comments: str = "") -> dict:
    """Reviewer-only. verdict = 'approve' (task becomes done) or 'changes_requested'
    (task returns to the owner with your comments)."""
    me = _agent()
    if verdict not in ("approve", "changes_requested"):
        return _err("verdict must be 'approve' or 'changes_requested'")
    with db() as c:
        t = _task(c, task_id)
        if not t:
            return _err(f"task {task_id} not found")
        if t["status"] != "review":
            return _err(f"task is '{t['status']}', not in review")
        if t["reviewer"] != me:
            return _err(f"only the assigned reviewer ({t['reviewer']}) can review task {task_id}")
        if t["owner"] == me:
            return _err("you cannot review your own task")
        if verdict == "approve":
            c.execute(
                "UPDATE tasks SET status='done', approved_by=?, updated_at=? WHERE id=?",
                (me, _now(), task_id),
            )
            new_status = "done"
        else:
            c.execute(
                "UPDATE tasks SET status='changes_requested', updated_at=? WHERE id=?",
                (_now(), task_id),
            )
            new_status = "changes_requested"
        ok, e = _insert_message(
            c, task_id, t["owner"], "review", f"Review verdict: {verdict}. {comments}".strip()
        )
        if not ok:
            # verdict still applies; just note the cap in the result
            return _ok(task_id=task_id, status=new_status, warning=e["error"])
        _log(c, "submit_review", {"task_id": task_id, "verdict": verdict})
        return _ok(task_id=task_id, status=new_status)


@mcp.tool()
def lock_files(paths: list[str], task_id: int = 0) -> dict:
    """Soft-lock files before editing them. All-or-nothing: if any path is locked by another
    agent, nothing is locked and the conflicts are returned. Locks expire after
    about 30 minutes; re-lock to extend."""
    me = _agent()
    paths = [_norm_path(p) for p in paths]
    with db() as c:
        _purge_expired_locks(c)
        conflicts = []
        for p in paths:
            row = c.execute("SELECT owner, expires_at FROM file_locks WHERE path=?", (p,)).fetchone()
            if row and row["owner"] != me:
                conflicts.append({"path": p, "owner": row["owner"], "expires_at": row["expires_at"]})
        if conflicts:
            return _err("some files are locked by another agent", conflicts=conflicts)
        exp = _in(LOCK_TTL_MIN)
        for p in paths:
            c.execute(
                "INSERT INTO file_locks(path, task_id, owner, expires_at) VALUES(?,?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET task_id=excluded.task_id, "
                "owner=excluded.owner, expires_at=excluded.expires_at",
                (p, task_id or None, me, exp),
            )
        _log(c, "lock_files", {"paths": paths})
        return _ok(locked=paths, expires_at=exp)


@mcp.tool()
def unlock_files(paths: list[str] = []) -> dict:
    """Release your locks on the given paths, or all of your locks if the list is empty."""
    me = _agent()
    with db() as c:
        if paths:
            for p in paths:
                c.execute("DELETE FROM file_locks WHERE path=? AND owner=?", (_norm_path(p), me))
        else:
            _release_locks(c, me)
        _log(c, "unlock_files", {"paths": paths or "all"})
        return _ok(released=paths or "all")


@mcp.tool()
def list_locks() -> list:
    """Show active (unexpired) file locks."""
    with db() as c:
        _purge_expired_locks(c)
        return [dict(r) for r in c.execute("SELECT * FROM file_locks ORDER BY path")]


@mcp.tool()
def wait_for_work(timeout_seconds: int = 25) -> dict:
    """LISTENING MODE. Blocks until a message for you arrives or another agent creates a new
    ready task, for up to timeout_seconds (max 50), then returns what happened.
    If `woke` is false nothing happened: call this tool again straight away.
    If `woke` is true, handle the messages/new_tasks using the Agora rules, then call this
    tool again. Also refreshes your presence on the board."""
    me = _agent()
    timeout = max(0, min(int(timeout_seconds), MAX_WAIT_SECONDS))
    started = _now()
    with db():
        pass  # heartbeat
    deadline = time.monotonic() + timeout
    while True:
        conn = sqlite3.connect(_db_path(), timeout=10)
        try:
            unread = _count_unread(conn, me)
            fresh = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status='todo' AND created_at>=? AND created_by!=? "
                "AND (depends_on IS NULL OR depends_on IN (SELECT id FROM tasks WHERE status='done'))",
                (started, me),
            ).fetchone()[0]
        finally:
            conn.close()
        if unread or fresh or time.monotonic() >= deadline:
            break
        time.sleep(POLL_SECONDS)

    inbox = read_inbox(mark_read=True)
    with db() as c:
        new_tasks = [
            dict(r)
            for r in c.execute(
                "SELECT id, title, description, created_by FROM tasks WHERE status='todo' "
                "AND created_at>=? AND created_by!=? "
                "AND (depends_on IS NULL OR depends_on IN (SELECT id FROM tasks WHERE status='done'))",
                (started, me),
            )
        ]
        pending = {
            "awaiting_my_review": [
                dict(r) for r in c.execute(
                    "SELECT id, title FROM tasks WHERE reviewer=? AND status='review'", (me,))
            ],
            "changes_requested_on_mine": [
                dict(r) for r in c.execute(
                    "SELECT id, title FROM tasks WHERE owner=? AND status='changes_requested'", (me,))
            ],
            "my_in_progress": [
                dict(r) for r in c.execute(
                    "SELECT id, title FROM tasks WHERE owner=? AND status='in_progress'", (me,))
            ],
        }
    woke = bool(inbox["messages"] or new_tasks)
    return _ok(
        woke=woke,
        messages=inbox["messages"],
        new_tasks=new_tasks,
        pending=pending,
        next=("Handle the items above, then call wait_for_work again." if woke
              else "Nothing new. Call wait_for_work again."),
    )


# ---------------------------------------------------------------- human-only actions
# Deliberately NOT MCP tools: agents must not be able to unblock themselves.
def unblock_task(task_id):
    """Clear a task blocked by the message cap and reset its message counter."""
    with db() as c:
        t = _task(c, task_id)
        if not t:
            return _err(f"task {task_id} not found")
        if t["status"] != "blocked":
            return _err(f"task {task_id} is '{t['status']}', not blocked")
        floor = c.execute("SELECT COALESCE(MAX(id),0) FROM messages").fetchone()[0]
        new = "in_progress" if t["owner"] else "todo"
        c.execute(
            "UPDATE tasks SET status=?, msg_floor=?, updated_at=? WHERE id=?",
            (new, floor, _now(), task_id),
        )
        _log(c, "unblock", {"task_id": task_id})
        return _ok(task_id=task_id, status=new)


# ---------------------------------------------------------------- human CLI
def _cli(argv):
    os.environ["AGENT_ID"] = "human"
    cmd, rest = argv[0], argv[1:]
    if cmd == "board":
        with db() as c:
            _purge_expired_locks(c)
            for s in ("todo", "in_progress", "review", "changes_requested", "blocked", "done"):
                rows = c.execute("SELECT * FROM tasks WHERE status=? ORDER BY id", (s,)).fetchall()
                if rows:
                    print(f"\n[{s}]")
                    for r in rows:
                        print(f"  #{r['id']} {r['title']}  owner={r['owner']} reviewer={r['reviewer']}")
            print("\n[agents]")
            for r in c.execute("SELECT * FROM agents ORDER BY id"):
                print(f"  {r['id']:<14} last seen {r['last_seen_at']}")
            locks = c.execute("SELECT * FROM file_locks").fetchall()
            if locks:
                print("\n[locks]")
                for r in locks:
                    print(f"  {r['path']}  by {r['owner']} until {r['expires_at']}")
    elif cmd == "create" and rest:
        print(create_task(rest[0], rest[1] if len(rest) > 1 else ""))
    elif cmd == "msg" and len(rest) >= 2:
        # msg <agent|all> <text> [task_id]
        to = "" if rest[0] == "all" else rest[0]
        print(post_message(rest[1], to=to, task_id=int(rest[2]) if len(rest) > 2 else 0))
    elif cmd == "unblock" and rest:
        r = unblock_task(int(rest[0]))
        if not r["ok"]:
            sys.exit(r["error"])
        print(f"task {r['task_id']} unblocked -> {r['status']} (message counter reset)")
    elif cmd == "log":
        n = int(rest[0]) if rest else 30
        with db() as c:
            for r in reversed(c.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (n,)).fetchall()):
                print(f"{r['at']}  {r['agent']:<12} {r['action']:<18} {r['payload']}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        _cli(sys.argv[1:])
    else:
        mcp.run()  # stdio
