"""OpsTrail MCP server (stdio or streamable HTTP). Works with mcp SDK v1 (FastMCP) and v2 (MCPServer)."""

from __future__ import annotations

import functools
import json
import logging
import os
from typing import Any, Callable

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError

    MCP_V2 = True
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]
    from mcp.server.fastmcp.exceptions import ToolError  # type: ignore[no-redef]

    MCP_V2 = False

from opstrail import __version__
from opstrail.service import OpsTrail, OpsTrailError

log = logging.getLogger("opstrail.mcp")

INSTRUCTIONS = """\
OpsTrail records the user's daily ops work (shell commands, focused windows, notes, screenshots)
and groups it into episodes (work items). Use it to write documentation from real activity.

Typical flows:
- "สรุปงานวันนี้" / daily worklog: daily_recap(date) -> polish the draft with the user -> save_draft(session_id, markdown).
- New document: list_episodes(date) -> pick episode ids with the user -> list_templates -> start_doc_session(template, title,
  episode_ids) -> write the document by following the returned source pack -> save_draft -> export_doc(format="docx").
- Continue a document: list_doc_sessions -> get_doc_session(id) -> add_doc_sources(...) if more work was done ->
  save_draft (new version) -> export_doc.
Rules: only use facts from OpsTrail sources or the user; unknowns become [TODO: ...]; never reveal or reconstruct
[REDACTED] values; reference screenshots as ![caption](shot://ID). Dates are YYYY-MM-DD, 'today' or 'yesterday'.
Record the user's intent/decisions with add_note when they explain *why* they did something.
"""


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)


def _guard(fn: Callable[..., str]) -> Callable[..., str]:
    """Turn user-facing errors into MCP tool errors whose message reaches the model."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return fn(*args, **kwargs)
        except (OpsTrailError, KeyError, ValueError) as exc:
            raise ToolError(str(exc).strip("'\"")) from exc

    return wrapper


class _GuardedServer:
    """Proxy so every @server.tool(...) function is wrapped by _guard."""

    def __init__(self, server: Any):
        self._server = server

    def tool(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., str]], Callable[..., str]]:
        register = self._server.tool(*args, **kwargs)
        return lambda fn: register(_guard(fn))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._server, name)


def build_server(svc: OpsTrail | None = None) -> Any:
    ot = svc or OpsTrail()
    kwargs: dict[str, Any] = {"instructions": INSTRUCTIONS}
    if MCP_V2:
        kwargs["version"] = __version__
    real_server = _Server("opstrail", **kwargs)
    server = _GuardedServer(real_server)

    def fresh() -> OpsTrail:
        try:
            ot.refresh()
        except Exception:  # never fail a read because of a bad inbox file
            log.exception("refresh failed")
        return ot

    # ------------------------------------------------------------- activity
    @server.tool(description="OpsTrail status: capture on/paused, agent heartbeat, today's counts, paths, templates.")
    def status() -> str:
        return _j(fresh().status())

    @server.tool(
        description="Raw activity timeline for one date (YYYY-MM-DD/today/yesterday). "
        "types: optional comma list of shell,window,note,screenshot,task,ai,idle. Returns the latest `limit` events."
    )
    def get_timeline(date: str = "today", types: str = "", limit: int = 300) -> str:
        return _j(fresh().timeline(date, types, limit))

    @server.tool(description="Search past activity (commands, window titles, notes) by substring.")
    def search_activity(query: str, date_from: str = "", date_to: str = "", limit: int = 50) -> str:
        return _j(fresh().search_activity(query, date_from or None, date_to or None, limit))

    # ------------------------------------------------------------- episodes
    @server.tool(
        description="List episodes (work items) for a date or a date range. Each has id, time, active duration, "
        "auto title, apps, target hosts, command/note/screenshot counts."
    )
    def list_episodes(date: str = "today", date_to: str = "") -> str:
        return _j(fresh().list_episodes(date, date_to or None))

    @server.tool(description="Episode detail: summary, top windows by focus time and its events (commands, notes, shots).")
    def get_episode(episode_id: int, max_events: int = 150) -> str:
        return _j(fresh().get_episode(episode_id, max_events))

    @server.tool(
        description="Rename/tag/annotate an episode. title locks the name; tags is a comma list; note adds a user note."
    )
    def update_episode(episode_id: int, title: str = "", tags: str = "", note: str = "") -> str:
        return _j(fresh().update_episode(episode_id, title, tags, note))

    @server.tool(description="Merge two or more episodes into one (e.g. the same task split by a break).")
    def merge_episodes(episode_ids: list[int], title: str = "") -> str:
        return _j(fresh().merge_episodes(episode_ids, title))

    @server.tool(
        description="Record a note (the user's intent, decision, result or context). Optionally attach to an episode."
    )
    def add_note(text: str, episode_id: int = 0) -> str:
        return _j(fresh().add_note(text, episode_id or None, source="mcp"))

    # ------------------------------------------------------------ documents
    @server.tool(description="List document templates (sop, delivery, guide, daily-worklog, …) with descriptions.")
    def list_templates() -> str:
        return _j(fresh().list_templates())

    @server.tool(
        description="Start a new document (doc session) from episodes and/or dates. Returns the session id and a SOURCE "
        "PACK: writing rules, template guide + skeleton, examples and all captured facts. Write the document from it, "
        "then call save_draft."
    )
    def start_doc_session(
        template: str,
        title: str,
        episode_ids: list[int] | None = None,
        date: str = "",
        date_to: str = "",
    ) -> str:
        res = fresh().start_doc_session(template, title, episode_ids or [], date or None, date_to or None)
        head = {k: v for k, v in res.items() if k != "source_pack"}
        return _j(head) + "\n\n" + res["source_pack"]

    @server.tool(description="List existing documents (doc sessions). Filter by status (draft/review/final) or template.")
    def list_doc_sessions(status: str = "", template: str = "", limit: int = 30) -> str:
        return _j(fresh().list_doc_sessions(status, template, limit))

    @server.tool(
        description="Open a document to continue it: metadata, sources, version history, latest markdown and (optionally) "
        "the full source pack."
    )
    def get_doc_session(session_id: int, include_sources: bool = True) -> str:
        res = fresh().get_doc_session(session_id, include_sources)
        pack = res.pop("source_pack", None)
        latest = res.pop("latest_markdown", None)
        out = _j(res)
        out += "\n\n## Latest draft\n\n" + (latest if latest else "_no draft yet_")
        if pack:
            out += "\n\n---\n\n" + pack
        return out

    @server.tool(
        description="Add more episodes and/or dates to an existing document. Returns only the NEW material to merge."
    )
    def add_doc_sources(session_id: int, episode_ids: list[int] | None = None, date: str = "", date_to: str = "") -> str:
        res = fresh().add_doc_sources(session_id, episode_ids or [], date or None, date_to or None)
        material = res.pop("new_material")
        return _j(res) + "\n\n" + material

    @server.tool(description="Save a new version of a document's markdown (append-only history).")
    def save_draft(session_id: int, markdown: str, change_note: str = "") -> str:
        return _j(ot.save_draft(session_id, markdown, change_note, author="ai"))

    @server.tool(description="Set a document's status: draft, review, final or archived.")
    def set_doc_status(session_id: int, status: str) -> str:
        return _j(ot.set_doc_status(session_id, status))

    @server.tool(
        description="Export the latest (or a given) version to md, docx or both. Screenshots are embedded. "
        "Returns the file paths on the user's computer."
    )
    def export_doc(session_id: int, format: str = "docx", version: int = 0) -> str:
        return _j(ot.export_doc(session_id, format, version or None))

    @server.tool(
        description="Build the deterministic daily worklog for a date. save=true stores it as a version of that day's "
        "'daily-worklog' document and returns its session_id so you can polish it and save_draft again."
    )
    def daily_recap(date: str = "today", save: bool = True) -> str:
        res = ot.daily_recap(date, save)
        md = res.pop("markdown")
        return _j(res) + "\n\n" + md

    @server.tool(
        description="Fact-check a document version: IPs, versions, hostnames and ports in the draft that do not "
        "appear in the captured sources (possible hallucinations). Run it after writing a draft."
    )
    def fact_check(session_id: int, version: int = 0) -> str:
        return _j(ot.fact_check(session_id, version or None))

    @server.tool(description="Full-text search across all documents (Thai-friendly).")
    def search_docs(query: str, limit: int = 10) -> str:
        return _j(ot.search_docs(query, limit))

    # ------------------------------------------------------------ resources
    @server.resource(
        "opstrail://templates/{name}",
        description="Template guide + skeleton for a document type",
        mime_type="text/markdown",
    )
    def template_resource(name: str) -> str:
        tpl = ot.template(name)
        return f"# {tpl.title}\n\n{tpl.description}\n\n## Guide\n\n{tpl.guide}\n\n## Skeleton\n\n{tpl.skeleton}"

    # -------------------------------------------------------------- prompts
    @server.prompt(description="Write/polish today's (or a given date's) daily worklog with OpsTrail")
    def daily_worklog(date: str = "today") -> str:
        return (
            f"ช่วยทำ Daily Worklog ของวันที่ {date} จาก OpsTrail:\n"
            f"1. เรียก daily_recap(date=\"{date}\") เพื่อได้ draft อัตโนมัติและ session_id\n"
            "2. เรียก list_episodes เพื่อดูรายละเอียดงาน ถ้าชื่องานยังเป็นชื่ออัตโนมัติ ให้เสนอชื่อที่อ่านเข้าใจ "
            "และถามฉันสั้นๆ เรื่องผลลัพธ์/สถานะของงานที่ไม่ชัด\n"
            "3. ขัดเกลาตาม template daily-worklog แล้ว save_draft\n"
            "4. แนะนำว่างานไหนควรทำเป็น SOP/Delivery doc/Guide"
        )

    @server.prompt(description="Create a new document (SOP / delivery / guide) from captured work")
    def write_document(template: str = "sop", topic: str = "", date: str = "today", date_to: str = "") -> str:
        rng = f"{date} ถึง {date_to}" if date_to else date
        return (
            f"ช่วยทำเอกสารประเภท `{template}` เรื่อง \"{topic or '[ให้เสนอชื่อเรื่อง]'}\" จากงานช่วง {rng}:\n"
            "1. list_episodes เพื่อหา episode ที่เกี่ยวข้อง แล้วยืนยันกับฉันก่อนว่าจะใช้ episode ไหน\n"
            "2. start_doc_session(template, title, episode_ids) แล้วเขียนเอกสารตาม source pack ที่ได้\n"
            "3. save_draft แล้วสรุปสิ่งที่ยังเป็น [TODO] ให้ฉันเติม\n"
            "4. เมื่อฉันโอเค export_doc(format=\"docx\")"
        )

    @server.prompt(description="Continue an existing document session")
    def continue_document(session_id: str) -> str:
        return (
            f"ทำเอกสาร doc session #{session_id} ต่อ: เรียก get_doc_session({session_id}) อ่าน draft ล่าสุดและ sources, "
            "ถามฉันว่าวันนี้ทำอะไรเพิ่ม (หรือใช้ add_doc_sources กับ episode/วันที่ใหม่), อัปเดตเอกสาร แล้ว save_draft "
            "พร้อม change_note"
        )

    return real_server


class _BearerAuth:
    """Minimal ASGI middleware: require `Authorization: Bearer <token>` for HTTP requests."""

    def __init__(self, app: Any, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            if headers.get("authorization", "") != f"Bearer {self.token}":
                await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await self.app(scope, receive, send)


def run(http: bool = False, host: str | None = None, port: int | None = None) -> None:
    svc = OpsTrail()
    server = build_server(svc)
    if not http:
        server.run("stdio")
        return
    import uvicorn

    host = host or svc.cfg.mcp.get("http_host", "127.0.0.1")
    port = int(port or svc.cfg.mcp.get("http_port", 8765))
    if MCP_V2:
        app = server.streamable_http_app(host=host)
    else:  # pragma: no cover - v1
        server.settings.host = host
        server.settings.port = port
        app = server.streamable_http_app()
    token = os.environ.get("OPSTRAIL_MCP_TOKEN", "").strip()
    if token:
        app = _BearerAuth(app, token)
    elif host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("HTTP MCP bound to %s without OPSTRAIL_MCP_TOKEN – anyone on the network can read your activity", host)
    print(f"OpsTrail MCP (streamable HTTP) on http://{host}:{port}/mcp", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")
