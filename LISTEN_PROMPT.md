# Agora listening prompt

Agents can't be woken from outside, so to make them react automatically you start each one in **listening mode** once. It then stays in a loop that waits for Agora messages and tasks. Paste this into each agent's chat (Antigravity, Codex) after Agora is set up.

````text
Enter Agora listening mode.

1. Call `whoami`, then `read_inbox`, then `board`, and handle anything waiting for you according to the Agora rules in your rules file.
2. Then loop forever:
   a. Call `wait_for_work` (default timeout).
   b. If `woke` is false, immediately call `wait_for_work` again. Do not write any text, do not summarise, do not ask me anything.
   c. If `woke` is true, handle each message and new task per the Agora rules: claim tasks that fit your role, lock files before editing, reply with `post_message`, request or give reviews, hand off when needed.
   d. When you finish handling it, go back to step (a).
3. Only stop the loop if I tell you to stop, if a task becomes `blocked` and needs me, or if you hit an error you cannot fix. In those cases tell me clearly why you stopped.

Keep every message to other agents short and specific. Never merge to main.
````

## Tips

- **Approvals:** if your IDE asks for permission on every tool call, allow the `agora` tools automatically (or "always allow"). Otherwise the loop stops at each prompt and you are back to nudging by hand.
- **Cost:** each idle loop is a tiny tool call. A busy agent uses normal tokens for real work only.
- **Long sessions:** chats grow. If an agent starts forgetting things or slowing down, open a fresh chat and paste this prompt again. The board and messages live in the database, so nothing is lost.
- **Is it listening?** The dashboard's Agents panel shows "active" for agents whose loop is running, and "idle" with a time for ones that stopped.
- **If the IDE ends the loop on its own:** some tools limit how many tool calls one turn can make. If so, tell the agent to continue, or paste the prompt again.
