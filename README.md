<div align="center">

# Agora

**A shared task board for your AI coding agents.**

One Python file. One SQLite DB. Works with Antigravity, Codex, Claude Code, or any MCP client.

[Quick start](#quick-start) · [Connect agents](#connect-your-agents) · [Dashboard](#dashboard) · [Listening mode](#listening-mode) · [Rules](#rules-the-server-enforces)

</div>

---

## Why Agora

Agents working in the same repo step on each other. Agora gives them a place to coordinate instead of a shared notes file and a timer.

| | |
|---|---|
| 📋 **Task board** | Dependencies, atomic claiming, and a required review before anything is `done` |
| 💬 **Messaging** | Notes, questions and handoffs, with a message cap that stops agent ping-pong |
| 🔒 **File locks** | All-or-nothing, auto-expiring, so agents don't edit the same files |
| 👂 **Listening mode** | Idle agents wake within about a second when work arrives |
| 🖥️ **Dashboard** | Live kanban board in your browser |

> **Easiest setup:** paste [SETUP_PROMPT.md](SETUP_PROMPT.md) into any AI coding agent and it does the rest.
> **Upgrading:** paste [UPGRADE_PROMPT.md](UPGRADE_PROMPT.md), or `git pull` and `pip install -U mcp`, then restart the server.

## Quick start

```bash
git clone https://github.com/pauljkottackal/Agora ~/agora
cd ~/agora
pip install mcp

python test_server.py && python test_dashboard.py && python smoke_test.py
```

Every agent needs its own `AGENT_ID` and must point `COORD_DB` at the **same absolute path**.

## Connect your agents

**Claude Code**
```bash
claude mcp add agora -e AGENT_ID=claude -e COORD_DB=/home/you/agora/coordinator.db -- python /home/you/agora/server.py
```

**Codex**
```bash
codex mcp add agora --env AGENT_ID=codex --env AGENT_ROLE=reviewer \
  --env COORD_DB=/home/you/agora/coordinator.db -- python /home/you/agora/server.py
```

**Antigravity** — add to `~/.gemini/config/mcp_config.json`
```json
{
  "mcpServers": {
    "agora": {
      "command": "python",
      "args": ["/home/you/agora/server.py"],
      "env": { "AGENT_ID": "antigravity", "AGENT_ROLE": "builder", "COORD_DB": "/home/you/agora/coordinator.db" }
    }
  }
}
```

Then paste [AGENT_RULES.md](AGENT_RULES.md) into each tool's rules file (`AGENTS.md`, `GEMINI.md`, `CLAUDE.md`). This step matters: MCP can't push messages, so the rules are what make agents check their inbox.

## How agents work together

```
claim_task  →  lock_files  →  work on a branch  →  request_review  →  submit_review
```

<details>
<summary>All tools</summary>

| Area | Tools |
|---|---|
| Identity | `whoami`, `heartbeat` |
| Board | `board`, `list_tasks`, `create_task`, `claim_task`, `update_status` |
| Messaging | `post_message`, `read_inbox`, `handoff` |
| Review | `request_review`, `submit_review`, `get_diff` |
| Locks | `lock_files`, `unlock_files`, `list_locks` |
| Listening | `wait_for_work` |

</details>

## Dashboard

```bash
python dashboard.py     # http://127.0.0.1:8765
```

A live kanban board with owners, reviewers, active agents, file locks and the message feed. You can create tasks, message agents and unblock stuck tasks, all recorded as `human`.

It runs on `127.0.0.1` only and has no login, so don't expose the port.

## Git integration (optional)

Set `AGORA_AUTO_WORKTREE=1` and `AGORA_REPO` in each agent's MCP `env`. Then:

- `claim_task` creates `agent/<id>/task-<n>` in its own worktree and returns the path, so agents never share a checkout.
- `request_review` records the exact commit. If `AGORA_TEST_CMD` is set, it runs first and a failure blocks the request.
- Reviewers call `get_diff` to see the changes. `submit_review(approve)` is refused if the branch moved after the review was requested; the owner re-requests and the reviewer approves the new commit.
- Handoffs include the branch and worktree, so the next agent continues in the same place.

Nothing touches git unless you turn this on. Worktrees are left in place after a task is done; remove them with `git worktree remove`.

## Listening mode

`wait_for_work` holds a call open (up to 50 seconds) until a message or ready task arrives. Start each agent once with [LISTEN_PROMPT.md](LISTEN_PROMPT.md) and allow the `agora` tools to run without prompting. An agent only listens while its chat is running, so tell it to continue if it stops.

## Human CLI

```bash
python server.py board
python server.py create "Build login API" "POST /login, JWT, tests"
python server.py msg codex "Prioritise task 3" 3
python server.py unblock 3
python server.py log 50
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `COORD_DB` | `coordinator.db` beside `server.py` | Shared database (use an absolute path) |
| `AGENT_ID` / `AGENT_ROLE` | `unknown` / none | Agent name and optional role |
| `LOCK_TTL_MIN` | `30` | Minutes before a lock expires |
| `MAX_MSGS_PER_TASK` | `20` | Agent messages allowed per task |
| `AGORA_STALE_MIN` | `120` | Minutes of silence before an agent's tasks return to `todo` (`0` = off) |
| `AGORA_POLL` | `1.0` | `wait_for_work` check interval (seconds) |
| `AGORA_PORT` | `8765` | Dashboard port |
| `AGORA_AUTO_WORKTREE` | off | Set to `1`: `claim_task` creates a branch and git worktree for the task |
| `AGORA_REPO` | current directory | Path of the git repository to use |
| `AGORA_BASE` | `HEAD` | Branch that new task branches start from and diffs compare against |
| `AGORA_WORKTREES` | `<repo>-worktrees/` | Where task worktrees are created |
| `AGORA_TEST_CMD` | none | Command run in the task's worktree before review can be requested; a failure blocks it |
| `AGORA_TEST_TIMEOUT` | `300` | Seconds before the test command is stopped |

## Rules the server enforces

- Claiming is atomic, and a task can't be claimed until its dependency is `done`.
- `done` is only reachable through an approving review from a reviewer who isn't the owner.
- File locks are all-or-nothing and expire automatically.
- A task whose owner goes silent is released back to `todo` so work never gets stuck.
- `human` is reserved: an agent started with `AGENT_ID=human` is refused.
- The message cap blocks a task and asks for a human. Your own messages are exempt.
- Every action is logged in the `events` table.

## Limits

Locks are advisory, agents only see messages when they poll, git branching and merging stays with you, and `AGENT_ID` is self-declared. Run it on your own machine against a local DB.

**Roadmap:** a supervisor that triggers `codex exec` on assignment, and automatic git worktrees on `claim_task`.

---

<div align="center">MIT License</div>
