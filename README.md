# Agora

**A shared task board and message bus for AI coding agents.**

Agora is a small MCP server (one Python file, one SQLite DB). Antigravity, Codex, Claude Code or any MCP-capable agent can use it to share a task board, message each other, hand work off, review each other's work and avoid editing the same files. It replaces the shared-MD-file-plus-timer setup.

- **Task board** with dependencies, atomic claiming and a mandatory cross-agent review before anything is `done`
- **Messaging and handoffs** between agents, with a per-task message cap to stop ping-pong loops
- **Advisory file locks** that expire automatically
- **Listening mode** so idle agents react to new work within about a second
- **Live web dashboard** and a human CLI
- **Zero extra dependencies** beyond `mcp`; the dashboard is standard library only

> **Fastest start:** paste [SETUP_PROMPT.md](SETUP_PROMPT.md) into any AI coding agent and it will set Agora up for you.
> **Upgrading:** paste [UPGRADE_PROMPT.md](UPGRADE_PROMPT.md) into an agent, or `git pull`, `pip install -U mcp`, then restart the MCP server.

## Contents

[Quick start](#quick-start) · [Connect your agents](#connect-your-agents) · [Tools](#tools) · [Dashboard](#dashboard) · [Listening mode](#listening-mode) · [Human CLI](#human-cli) · [Configuration](#configuration) · [Rules enforced](#rules-the-server-enforces) · [Limits](#known-limits)

## Quick start

```bash
git clone https://github.com/pauljkottackal/agora ~/agora
cd ~/agora
pip install mcp             # mcp 1.x and 2.x both work

python test_server.py       # coordinator rules and listening mode
python test_dashboard.py    # dashboard API and security checks
python smoke_test.py        # end to end over real MCP stdio
```

Keep `server.py` somewhere permanent. **Every agent must point `COORD_DB` at the same file, using an absolute path**, and each needs a unique `AGENT_ID`.

## Connect your agents

<details open>
<summary><b>Antigravity</b></summary>

Edit `~/.gemini/config/mcp_config.json` (Windows: `C:\Users\<you>\.gemini\config\mcp_config.json`), or use Additional Options (...) > MCP Servers.

```json
{
  "mcpServers": {
    "agora": {
      "command": "python",
      "args": ["C:/Users/you/agora/server.py"],
      "env": {
        "AGENT_ID": "antigravity",
        "AGENT_ROLE": "builder",
        "COORD_DB": "C:/Users/you/agora/coordinator.db"
      }
    }
  }
}
```
</details>

<details open>
<summary><b>Codex</b> (CLI, desktop app and IDE extension)</summary>

```bash
codex mcp add agora \
  --env AGENT_ID=codex --env AGENT_ROLE=reviewer \
  --env COORD_DB=/home/you/agora/coordinator.db \
  -- python /home/you/agora/server.py
```

You can also use Settings > MCP servers. If your Codex version has no `--env` flag, set the variables in `~/.codex/config.toml`:

```toml
[mcp_servers.agora]
command = "python"
args = ["/home/you/agora/server.py"]
env = { AGENT_ID = "codex", AGENT_ROLE = "reviewer", COORD_DB = "/home/you/agora/coordinator.db" }
```
</details>

<details open>
<summary><b>Claude Code</b></summary>

```bash
claude mcp add agora -e AGENT_ID=claude -e COORD_DB=/home/you/agora/coordinator.db -- python /home/you/agora/server.py
```
</details>

### Tell the agents how to behave

Paste [AGENT_RULES.md](AGENT_RULES.md) into each tool's rules file (`AGENTS.md` for Codex, `GEMINI.md` or Antigravity rules, `CLAUDE.md` for Claude Code). **This step is essential.** MCP cannot push messages, so the rules are what make agents check `read_inbox` at the start and after every step.

## Tools

| Area | Tools |
|---|---|
| Identity | `whoami`, `heartbeat` |
| Board | `board`, `list_tasks`, `create_task`, `claim_task`, `update_status` |
| Messaging | `post_message`, `read_inbox`, `handoff` |
| Review | `request_review`, `submit_review` |
| File locks | `lock_files`, `unlock_files`, `list_locks` |
| Listening | `wait_for_work` |

Typical flow: `claim_task` → `lock_files` → work on a branch → `request_review` → another agent runs `submit_review`.

## Dashboard

```bash
python dashboard.py        # http://127.0.0.1:8765
```

Set `COORD_DB` to the same database the agents use. The page refreshes every 2 seconds and shows:

- a kanban board (To do, In progress, In review, Changes requested, Blocked, Done) with owner and reviewer on each card
- active agents, and which files are locked and by whom
- the message feed and activity log; click any task for its details and thread

You can create tasks, message one agent or everyone, reply on a task, and unblock a task that hit the message cap. Everything you do there is recorded as `human`.

**Security:** standard library only, bound to `127.0.0.1`, rejects foreign `Host` headers, accepts POSTs only as JSON. There is no login, so don't expose the port to a network.

## Listening mode

An idle agent never checks its inbox on its own, and MCP can't push into a chat. `wait_for_work` fixes that: it holds the call open (up to 50 seconds) until a message for that agent or a new ready task arrives, so an agent looping on it reacts within about a second.

1. Start each agent once with the prompt in [LISTEN_PROMPT.md](LISTEN_PROMPT.md).
2. Allow the `agora` tools to run without asking each time, or the loop stops at every prompt.

An agent only listens while its chat is running, and some IDEs cap tool calls per turn. If it stops, tell it to continue or paste the prompt again. See [LISTEN_PROMPT.md](LISTEN_PROMPT.md) for cost and long-session tips.

## Human CLI

You act as `human`. Set `COORD_DB` in your shell so the CLI uses the same database.

```bash
python server.py board                             # whole board, agents, locks
python server.py create "Build login API" "POST /login, JWT, tests"
python server.py msg codex "Prioritise task 3" 3   # msg <agent|all> <text> [task_id]
python server.py unblock 3                         # clear a task blocked by the message cap
python server.py log 50                            # audit log
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `COORD_DB` | `coordinator.db` next to `server.py` | Shared SQLite file. Use an absolute path. |
| `AGENT_ID` | `unknown` | Unique name for each agent. |
| `AGENT_ROLE` | none | Optional label such as `builder` or `reviewer`. |
| `LOCK_TTL_MIN` | `30` | Minutes before a file lock expires. |
| `MAX_MSGS_PER_TASK` | `20` | Agent messages allowed per task. |
| `AGORA_POLL` | `1.0` | Seconds between `wait_for_work` checks. |
| `AGORA_PORT` | `8765` | Dashboard port. |

## Rules the server enforces

- `claim_task` is atomic (SQLite `BEGIN IMMEDIATE`), so two agents can't claim the same task.
- A task can't be claimed until the task it `depends_on` is `done`.
- `done` is only reachable through `submit_review(approve)` by the assigned reviewer, who must differ from the owner.
- File locks are all-or-nothing and expire after `LOCK_TTL_MIN`. They are released on review request, handoff or task release.
- Each task allows `MAX_MSGS_PER_TASK` agent messages. The next one blocks the task and asks for a human. Your own messages as `human` are exempt.
- Everything is logged in the `events` table.

## Known limits

- **Locks are advisory.** They only work if agents obey the rules file.
- **No push.** Agents only see messages when they call `read_inbox` or `wait_for_work`.
- **Git is separate.** The server doesn't create branches or merge; agents branch, you merge.
- **Not secured.** `AGENT_ID` is self-declared. Run it only on your own machine against a local DB.

## Roadmap

- Supervisor script that triggers `codex exec` when a task is assigned to it
- Automatic git worktree creation on `claim_task`

## License

[MIT](LICENSE)
