## Multi-agent coordination (Agora MCP)

You share this repo with other AI agents. Coordinate ONLY through the `agora` MCP tools, never by editing shared notes files.

1. **Start of every session:** call `whoami`, then `read_inbox`, then `board`.
2. **Before starting work:** `claim_task(task_id)`. If it fails, pick another task. Never work on a task you have not claimed.
3. **Before editing files:** `lock_files([...paths], task_id)`. If a file is locked by someone else, do NOT edit it. Work on something else or message the owner.
4. **Work in your own git branch or worktree** (`agent/<your-id>/task-<id>`). Never commit directly to main.
5. **After each meaningful step:** `read_inbox`. Answer questions with `post_message`. Keep messages short and specific.
6. **Stopping partway or passing work on:** `handoff(task_id, to, summary, files_touched, remaining, verify)`. Be explicit; the next agent has none of your context.
7. **Finished:** run the tests, then `request_review(task_id, reviewer)` with another agent. Never mark your own task done; only an approving `submit_review` does that.
8. **When asked to review:** read the diff on the task branch, run the tests, then `submit_review(task_id, 'approve' | 'changes_requested', comments)`. Be concrete about what to change.
9. **If a task becomes `blocked`** (message cap reached), stop messaging about it and tell the human. Do not retry.
10. Do not run destructive git commands (force push, reset --hard) or merge to main. A human merges.
11. **Listening mode:** when the human tells you to "enter Agora listening mode", loop on `wait_for_work`. If `woke` is false, call it again at once with no commentary. If true, handle what arrived using the rules above, then wait again. Stop only when told to, when a task is `blocked`, or on an unfixable error.
