# Agora setup prompt

Paste everything inside the block below into any AI coding agent that has shell access (Antigravity, Codex, Claude Code, etc.). Do it once per agent. All agents on the same PC share one database.

````text
You are setting up Agora on this computer. Agora is an MCP server that lets several AI coding agents (Antigravity, Codex, Claude Code, ...) share a task board, send messages, hand off work, review each other and lock files. Repo: https://github.com/pauljkottackal/Agora

Work through the steps in order. Run the commands yourself and fix problems you can fix. Ask me only where a step says ASK. Do not delete or overwrite anything that already exists; when editing a config file, merge into it and keep my other entries. Show me a short summary at the end.

1. DETECT
   - Work out the OS (Windows, macOS or Linux) and which AI tool YOU are (Antigravity, Codex, Claude Code, or other).
   - ASK me for a short, unique AGENT_ID for you (suggest: antigravity, codex or claude, lowercase). Every agent must use a different one.
   - Check Python 3.10+ is installed (`python --version` or `python3 --version`). If it is missing, tell me how to install it and stop.

2. INSTALL
   - If ~/agora (Windows: %USERPROFILE%\agora) already exists, reuse it and run `git pull`. Otherwise run `git clone https://github.com/pauljkottackal/Agora ~/agora`.
   - Create a virtual environment inside it (`python -m venv .venv`) and run `pip install mcp` with that environment's pip.
   - Record the ABSOLUTE path of the venv's Python (Windows: .venv\Scripts\python.exe, macOS/Linux: .venv/bin/python). Call it PYTHON.
   - Run `PYTHON test_server.py` in the repo. All tests must pass. If they fail, show me the error and stop.

3. SHARED DATABASE
   - The database path must be the same for every agent. Check whether ~/.agora/coordinator.db already exists or whether I already set COORD_DB in another agent's config.
   - If one already exists, reuse that exact path. If not, use ~/.agora/coordinator.db (create the folder). Write it as an ABSOLUTE path. Call it DB.

4. REGISTER THE MCP SERVER IN YOUR OWN TOOL
   Server name: agora. Command: PYTHON. Args: [absolute path to server.py]. Env: AGENT_ID=<your id>, COORD_DB=DB.
   - Antigravity: add the entry under "mcpServers" in ~/.gemini/config/mcp_config.json (Windows: C:\Users\<me>\.gemini\config\mcp_config.json). Create the file if it is missing; otherwise merge.
   - Codex: `codex mcp add agora --env AGENT_ID=<id> --env COORD_DB=<DB> -- <PYTHON> <path to server.py>`. If that fails, add an [mcp_servers.agora] block to ~/.codex/config.toml with command, args and env.
   - Claude Code: `claude mcp add agora -e AGENT_ID=<id> -e COORD_DB=<DB> -- <PYTHON> <path to server.py>`
   - Any other tool: use its documented way to add a local stdio MCP server with the same values.

5. TEACH YOURSELF THE RULES
   - Read ~/agora/AGENT_RULES.md.
   - Add its contents to this project's rules file, creating the file if needed: AGENTS.md (Codex), GEMINI.md (Antigravity), CLAUDE.md (Claude Code). If the file already has an "Agora" or "Multi-agent coordination" section, update it instead of duplicating it.

6. VERIFY
   - Tell me whether the tool needs a restart or a reload to pick up the new MCP server. If it does, ask me to do it and continue after.
   - Then call the `whoami` tool from the agora server. It must return my AGENT_ID. If the tool is not visible, re-check the config path, the absolute paths and the JSON/TOML syntax, fix it and try again.
   - Call `board` and show me the result.

7. REPORT
   Give me a short summary: OS, your AGENT_ID, PYTHON, DB, which config file you edited, which rules file you updated, and the result of `whoami`. Finish with this line for me to copy into the NEXT agent's setup: "Reuse COORD_DB=<DB> and pick a different AGENT_ID."

8. DASHBOARD (optional, only for the first agent)
   Tell me how to open the web UI: run `PYTHON dashboard.py` in ~/agora with COORD_DB=DB set, then open http://127.0.0.1:8765. Do not start it yourself unless I ask.

9. LISTENING MODE (optional)
   Tell me that to make you react to messages automatically I can paste the listening prompt from ~/agora/LISTEN_PROMPT.md into your chat, and that your tool permissions should allow the agora tools without asking each time. Do not start the loop unless I ask.

Safety rules: no force pushes, no deleting files, no changing anything outside ~/agora, ~/.agora, your own MCP config and your own rules file. If something is unclear or risky, stop and ask.
````

## Setting up the second agent

Run the same prompt in the other agent. When it asks, give it a different AGENT_ID. It will find and reuse the existing database.
