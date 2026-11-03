# Agora

Agora is a small MCP server (one Python file, one SQLite DB) so Antigravity, Codex, Claude Code or any MCP-capable agent can share a task board, message each other, hand work off, review each other's work and avoid editing the same files. It replaces the shared-MD-file-plus-timer setup.

**Fastest way:** paste the prompt in [SETUP_PROMPT.md](SETUP_PROMPT.md) into any AI coding agent and it will set Agora up for you.

## Install (manual)

```bash
pip install mcp          # works with mcp 1.x and 2.x
python test_server.py    # 9 unit tests
python smoke_test.py     # end-to-end over real MCP stdio
```

Put `server.py` somewhere permanent (e.g. `~/agora/`). All agents must point `COORD_DB` at the **same** file, with an absolute path.

## Connect each agent

Give every agent a different `AGENT_ID`. Use absolute paths.

### Antigravity
Edit `~/.gemini/config/mcp_config.json` (Windows: `C:\Users\<you>\.gemini\config\mcp_config.json`) or use the panel menu: Additional Options (...) > MCP Servers.

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

### Codex
CLI (shared by the Codex desktop app and IDE extension):

```bash
codex mcp add agora \
  --env AGENT_ID=codex --env AGENT_ROLE=reviewer \
  --env COORD_DB=/home/you/agora/coordinator.db \
  -- python /home/you/agora/server.py
```

You can also add it under Settings > MCP servers. If your Codex version has no `--env` flag, set the three variables in the MCP server's env section in the settings UI or in `~/.codex/config.toml`:

```toml
[mcp_servers.agora]
command = "python"
args = ["/home/you/agora/server.py"]
env = { AGENT_ID = "codex", AGENT_ROLE = "reviewer", COORD_DB = "/home/you/agora/coordinator.db" }
```

### Claude Code (optional third agent)
```bash
claude mcp add agora -e AGENT_ID=claude -e COORD_DB=/home/you/agora/coordinator.db -- python /home/you/agora/server.py
```

### Tell the agents how to behave
Paste `AGENT_RULES.md` into each tool's rules file (`AGENTS.md` for Codex, `GEMINI.md` or Antigravity rules, `CLAUDE.md`). This is what replaces your timer: agents check `read_inbox` at the start and after every step. MCP cannot push messages, so this instruction is essential.

## Human CLI (you are `human`)

```bash
python server.py board                          # whole board, agents, locks
python server.py create "Build login API" "POST /login, JWT, tests"
python server.py msg codex "Prioritise task 3" 3   # msg <agent|all> <text> [task_id]
python server.py unblock 3                       # clear a task blocked by the message cap
python server.py log 50                          # audit log
```
Set `COORD_DB` in your shell so the CLI uses the same database.

## Rules the server enforces

- `claim_task` is atomic (SQLite `BEGIN IMMEDIATE`): two agents can't claim the same task.
- A task can't be claimed until the task it `depends_on` is `done`.
- `done` is only reachable through `submit_review(approve)` by the assigned reviewer, who must differ from the owner.
- File locks are all-or-nothing and expire after 30 minutes (`LOCK_TTL_MIN`). They are released on review request, handoff, or release of the task.
- Each task allows 20 agent messages (`MAX_MSGS_PER_TASK`). The 21st blocks the task and asks for a human, which stops agent ping-pong loops. Your own messages as `human` are exempt.
- Everything is logged in the `events` table.

## Known limits

- **Locks are advisory.** They only work if agents obey the rules file. They don't stop a disobedient agent from editing a file.
- **No push.** Agents only see messages when they call `read_inbox`.
- **Git is separate.** The server doesn't create branches or merge; agents do that, and you merge.
- **Not secured.** `AGENT_ID` is self-declared, so run it only on your own machine against a local DB.

## Next steps

Read-only web dashboard (FastAPI) on the same SQLite file; a supervisor script that triggers `codex exec` when a task is assigned to it; automatic git worktree creation on `claim_task`.
