# Agora upgrade prompt

Paste everything inside the block below into any AI coding agent that has shell access and already has Agora set up. Run it once per agent that uses its own copy of the config or rules file. Your database and task history are never touched.

````text
You are upgrading my existing Agora installation to the latest version from GitHub. Agora is an MCP server that lets AI coding agents share a task board, messages, reviews and file locks. Repo: https://github.com/pauljkottackal/Agora

Follow the steps in order. Do not delete or overwrite anything I did not ask about. Never touch any *.db file. Ask me only where a step says ASK.

1. FIND THE INSTALL
   - Look for it in ~/agora (Windows: %USERPROFILE%\agora). If it is not there, read your own MCP config (Antigravity: ~/.gemini/config/mcp_config.json, Codex: `codex mcp list` or ~/.codex/config.toml, Claude Code: `claude mcp list`), find the "agora" entry, and take the folder of the server.py path in it.
   - If you cannot find it, ASK me where Agora is installed, or tell me to run the setup prompt (SETUP_PROMPT.md in the repo) instead, and stop.

2. RECORD THE CURRENT VERSION
   - In that folder run `git rev-parse --short HEAD` and `git log -1 --format=%cd`. Save the short hash as OLD.
   - Run `git status --short`. If there are local changes to tracked files, ASK me whether to keep them (stash) before continuing. Never discard them.

3. UPDATE
   - Run `git pull --ff-only`. If it fails because the history diverged, show me the error and stop.
   - Save the new short hash as NEW. If OLD equals NEW, say "already up to date" but still do steps 4 to 7 to check the setup.

4. DEPENDENCIES AND TESTS
   - Use the venv Python recorded in the MCP config (or .venv/bin/python, Windows: .venv\Scripts\python.exe). Run `<python> -m pip install -U mcp`.
   - Run `<python> test_server.py` and `<python> test_dashboard.py`. All tests must pass. If any fail, show me the output and stop.

5. CHECK YOUR MCP ENTRY
   - Confirm your "agora" entry still has: command = that venv Python, args = absolute path to server.py, env AGENT_ID (unchanged) and COORD_DB (unchanged absolute path). Fix only broken or relative paths. Do not change AGENT_ID or COORD_DB.

6. REFRESH YOUR RULES
   - Read AGENT_RULES.md from the repo. In this project's rules file (AGENTS.md for Codex, GEMINI.md for Antigravity, CLAUDE.md for Claude Code), replace the existing "Multi-agent coordination" / Agora section with the new text. Keep everything else in that file. If there is no such section, add it.

7. RESTART AND VERIFY
   - New tools only appear after the MCP server restarts. Tell me whether you need me to reload the MCP server, reload the window, or restart the IDE, ask me to do it, and continue after.
   - Call `whoami` and confirm it returns my AGENT_ID. Then list the agora tools you can see and confirm `wait_for_work` is among them.
   - If the dashboard is running (http://127.0.0.1:8765), tell me to stop it with Ctrl+C and start it again with `<python> dashboard.py`. Do not kill processes yourself.

8. REPORT
   Show: OLD -> NEW, the output of `git log --oneline OLD..NEW` (what changed), test results, which config and rules files you checked or changed, and the `whoami` result. If listening mode is new for me, remind me that I can paste the prompt from LISTEN_PROMPT.md to start it.

Safety rules: no force pushes, no resets, no deleting files, no changes outside the Agora folder, your own MCP entry and your own rules file.
````
