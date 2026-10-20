"""MCP server tests: in-memory and real stdio subprocess (works with mcp v1 and v2)."""

from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager

import anyio
from conftest import DAY

from opstrail.mcp_server import MCP_V2, build_server

EXPECTED_TOOLS = {
    "status", "get_timeline", "search_activity", "list_episodes", "get_episode", "update_episode",
    "merge_episodes", "add_note", "list_templates", "start_doc_session", "list_doc_sessions",
    "get_doc_session", "add_doc_sources", "save_draft", "set_doc_status", "export_doc",
    "daily_recap", "search_docs",
}


def _text(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


@asynccontextmanager
async def stdio_session(env: dict):
    if MCP_V2:
        from mcp.client.client import Client, StdioServerParameters

        params = StdioServerParameters(command=sys.executable, args=["-m", "opstrail", "mcp"], env=env)
        async with Client(params) as client:
            yield client
    else:  # pragma: no cover - mcp 1.x
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(command=sys.executable, args=["-m", "opstrail", "mcp"], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


@asynccontextmanager
async def memory_session(server):
    if MCP_V2:
        from mcp.client.client import Client

        async with Client(server) as client:
            yield client
    else:  # pragma: no cover - mcp 1.x
        from mcp.shared.memory import create_connected_server_and_client_session

        async with create_connected_server_and_client_session(server._mcp_server) as session:
            yield session


def test_in_memory_full_flow(svc, sample_day):
    server = build_server(svc)

    async def main():
        async with memory_session(server) as c:
            tools = {t.name for t in (await c.list_tools()).tools}
            assert EXPECTED_TOOLS <= tools, EXPECTED_TOOLS - tools
            prompts = {p.name for p in (await c.list_prompts()).prompts}
            assert {"daily_worklog", "write_document", "continue_document"} <= prompts

            eps = json.loads(_text(await c.call_tool("list_episodes", {"date": DAY})))
            assert len(eps) == 2
            res = await c.call_tool(
                "start_doc_session", {"template": "sop", "title": "UF install", "episode_ids": [eps[0]["id"]]}
            )
            text = _text(res)
            head = json.loads(text.split("\n\n", 1)[0])
            sid = head["session_id"]
            assert "OpsTrail source pack" in text
            saved = json.loads(_text(await c.call_tool("save_draft", {"session_id": sid, "markdown": "# SOP\n\nok"})))
            assert saved["version"] == 1
            out = json.loads(_text(await c.call_tool("export_doc", {"session_id": sid, "format": "docx"})))
            assert out["files"][0].endswith(".docx") and os.path.exists(out["files"][0])
            cont = _text(await c.call_tool("get_doc_session", {"session_id": sid, "include_sources": False}))
            assert "## Latest draft" in cont and "# SOP" in cont
            recap = _text(await c.call_tool("daily_recap", {"date": DAY}))
            assert "Daily Worklog" in recap
            bad = await c.call_tool("get_episode", {"episode_id": 99999})
            is_error = getattr(bad, "is_error", None)
            if is_error is None:
                is_error = getattr(bad, "isError")
            assert is_error and "not found" in _text(bad), _text(bad)
            res = await c.read_resource("opstrail://templates/sop")
            assert "Skeleton" in res.contents[0].text

    anyio.run(main)


def test_stdio_subprocess(home, sample_day):
    env = {**os.environ, "OPSTRAIL_HOME": str(home)}

    async def main():
        with anyio.fail_after(60):
            await inner()

    async def inner():
        async with stdio_session(env) as c:
            status = json.loads(_text(await c.call_tool("status", {})))
            assert status["events_today"] is not None and "sop" in status["templates"]
            eps = json.loads(_text(await c.call_tool("list_episodes", {"date": DAY})))
            assert len(eps) == 2  # inbox was ingested by the server itself
            note = json.loads(_text(await c.call_tool("add_note", {"text": "จาก MCP", "episode_id": eps[1]["id"]})))
            assert note["episode_id"] == eps[1]["id"]

    anyio.run(main)
