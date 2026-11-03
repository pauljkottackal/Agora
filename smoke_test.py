"""Smoke test: talk to server.py over real MCP stdio, as two different agents."""
import asyncio
import os
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(tempfile.mkdtemp(), "smoke.db")


async def call(agent, tool, args=None):
    params = StdioServerParameters(
        command=sys.executable,
        args=[os.path.join(HERE, "server.py")],
        env={**os.environ, "AGENT_ID": agent, "COORD_DB": DB},
    )
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            res = await session.call_tool(tool, args or {})
            sc = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
            return sc or res.content[0].text


async def main():
    async with stdio_client(StdioServerParameters(
        command=sys.executable, args=[os.path.join(HERE, "server.py")],
        env={**os.environ, "AGENT_ID": "x", "COORD_DB": DB})) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tools = [t.name for t in (await session.list_tools()).tools]
            print("tools:", tools)
            assert len(tools) >= 15

    print(await call("codex", "create_task", {"title": "Build login API", "description": "POST /login"}))
    print(await call("codex", "claim_task", {"task_id": 1}))
    print(await call("antigravity", "claim_task", {"task_id": 1}))      # should fail
    print(await call("codex", "post_message", {"body": "API done, review?", "to": "antigravity", "task_id": 1}))
    print(await call("antigravity", "read_inbox"))
    print(await call("codex", "request_review", {"task_id": 1, "reviewer": "antigravity"}))
    print(await call("antigravity", "submit_review", {"task_id": 1, "verdict": "approve", "comments": "LGTM"}))
    print(await call("codex", "board"))


asyncio.run(main())
