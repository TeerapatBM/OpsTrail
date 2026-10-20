"""OpsTrail web UI: JSON API + static single-page app, served on 127.0.0.1 only."""

from __future__ import annotations

import logging
import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from opstrail import __version__, llm
from opstrail.service import OpsTrail, OpsTrailError

log = logging.getLogger("opstrail.web")
STATIC = Path(__file__).parent / "static"
LOOPBACK = ("127.0.0.1", "localhost", "[::1]")


# ---------------------------------------------------------------- security
class LocalOnly:
    """Defence for a localhost app against DNS rebinding and CSRF from other websites.

    * Host header must be a loopback name (blocks DNS-rebinding attacks).
    * State-changing requests need `X-OpsTrail: 1` (custom header → cross-site forms/fetch can't send it
      without a CORS preflight, which we never approve) and, when present, a same-origin Origin header.
      Only browser ingest permits an extension origin, authenticated with its per-install token.
    * Hardened response headers (CSP, no framing, no cross-origin embedding of screenshots).
    """

    def __init__(self, app: Any, port: int, extra_hosts: tuple[str, ...] = (), cfg: Any = None):
        self.app = app
        self.cfg = cfg
        self.port = port
        self.hosts = {h for h in LOOPBACK} | {f"{h}:{port}" for h in LOOPBACK} | set(extra_hosts)
        self.origins = {f"http://{h}:{port}" for h in LOOPBACK} | {f"http://{h}" for h in extra_hosts}

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        method = scope.get("method", "GET")
        if headers.get("host", "") not in self.hosts:
            await JSONResponse({"error": "forbidden host"}, status_code=403)(scope, receive, send)
            return
        if method not in ("GET", "HEAD"):
            origin = headers.get("origin")
            browser_post = scope.get("path") == "/api/ingest/browser" and method == "POST"
            extension = bool(origin and re.fullmatch(r"chrome-extension://[a-p]{32}", origin))
            from opstrail.browser import valid_token

            paired = browser_post and self.cfg is not None and valid_token(
                self.cfg, headers.get("x-opstrail-browser-token", ""))
            if (headers.get("x-opstrail") != "1" or
                    (browser_post and not paired) or
                    (origin and origin not in self.origins and not (extension and paired))):
                await JSONResponse({"error": "cross-site request blocked"}, status_code=403)(scope, receive, send)
                return

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cross-origin-resource-policy", b"same-origin"),
                    (
                        b"content-security-policy",
                        b"default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                        b"script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
                    ),
                ]
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + extra
            await send(message)

        await self.app(scope, receive, send_with_headers)


# ------------------------------------------------------------------ helpers
def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ids(value: Any) -> list[int]:
    if not value:
        return []
    if isinstance(value, str):
        value = value.split(",")
    return [int(v) for v in value if str(v).strip()]


Handler = Callable[[Request, dict[str, Any]], Any]


def api(fn: Handler, *, body: bool = False) -> Callable[[Request], Awaitable[Response]]:
    """Run a sync handler in a thread; map errors to JSON."""

    async def endpoint(request: Request) -> Response:
        payload: dict[str, Any] = {}
        if body:
            try:
                payload = await request.json()
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
        try:
            result = await run_in_threadpool(fn, request, payload)
        except OpsTrailError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except llm.LLMError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        except Exception as exc:  # pragma: no cover - unexpected
            log.exception("api error")
            return JSONResponse({"error": f"internal error: {exc}"}, status_code=500)
        if isinstance(result, Response):
            return result
        return JSONResponse(result)

    return endpoint


# --------------------------------------------------------------------- app
def create_app(svc: OpsTrail | None = None, *, port: int | None = None, extra_hosts: tuple[str, ...] = ()) -> Any:
    ot = svc or OpsTrail()
    web_port = port or int(ot.cfg.data.get("web", {}).get("port", 8765))

    def fresh() -> OpsTrail:
        try:
            ot.refresh()
        except Exception:
            log.exception("refresh failed")
        return ot

    q = lambda r, k, d="": r.query_params.get(k, d)  # noqa: E731

    # --- status / capture
    def status(r: Request, b: dict) -> Any:
        st = fresh().status()
        st["llm"] = llm.public_settings(ot.cfg)
        st["hotkeys"] = ot.cfg.hotkeys
        return st

    def capture(r: Request, b: dict) -> Any:
        return ot.set_paused(bool(b.get("paused")))

    def browser_token(r: Request, b: dict) -> Any:
        from opstrail.browser import pairing_token

        try:
            return JSONResponse({"token": pairing_token(ot.cfg)}, headers={"Cache-Control": "no-store"})
        except (OSError, ValueError):
            raise OpsTrailError("ไม่สามารถเปิด browser token ได้ กรุณาลองใหม่") from None

    def browser_ingest(r: Request, b: dict) -> Any:
        return ot.record_browser(b)

    # --- activity
    def day(r: Request, b: dict) -> Any:
        return fresh().day(r.path_params["date"])

    def make_recap(r: Request, b: dict) -> Any:
        res = ot.daily_recap(r.path_params["date"], save=True)
        res.pop("markdown", None)
        return res

    def timeline(r: Request, b: dict) -> Any:
        return fresh().timeline(q(r, "date", "today"), q(r, "types"), _int(q(r, "limit"), 500))

    def episode(r: Request, b: dict) -> Any:
        return fresh().get_episode(_int(r.path_params["id"]), _int(q(r, "max_events"), 300))

    def episode_update(r: Request, b: dict) -> Any:
        return ot.update_episode(_int(r.path_params["id"]), str(b.get("title", "")), b.get("tags", ""), str(b.get("note", "")))

    def merge(r: Request, b: dict) -> Any:
        return ot.merge_episodes(_ids(b.get("ids")), str(b.get("title", "")))

    def note(r: Request, b: dict) -> Any:
        return ot.add_note(str(b.get("text", "")), _int(b.get("episode_id")) or None, source="web")

    def shot(r: Request, b: dict) -> Any:
        return FileResponse(str(ot.shot_file(_int(r.path_params["id"]))), headers={"cache-control": "max-age=86400"})

    # --- documents
    def templates(r: Request, b: dict) -> Any:
        return ot.list_templates()

    def docs(r: Request, b: dict) -> Any:
        return ot.list_doc_sessions(q(r, "status"), q(r, "template"), _int(q(r, "limit"), 200))

    def doc_create(r: Request, b: dict) -> Any:
        res = fresh().start_doc_session(
            str(b.get("template", "")),
            str(b.get("title", "")),
            _ids(b.get("episode_ids")),
            b.get("date") or None,
            b.get("date_to") or None,
        )
        return {"session_id": res["session_id"], "sources_added": res["sources_added"]}

    def doc(r: Request, b: dict) -> Any:
        return ot.doc_detail(_int(r.path_params["id"]), _int(q(r, "version")) or None)

    def doc_meta(r: Request, b: dict) -> Any:
        return ot.update_doc_meta(_int(r.path_params["id"]), str(b.get("title", "")), str(b.get("status", "")))

    def doc_save(r: Request, b: dict) -> Any:
        return ot.save_draft(_int(r.path_params["id"]), str(b.get("markdown", "")), str(b.get("change_note", "")), "web")

    def doc_generate(r: Request, b: dict) -> Any:
        svc = fresh()
        sid, instruction = _int(r.path_params["id"]), str(b.get("instruction", ""))
        if q(r, "stream") != "1":
            return svc.generate_draft(sid, instruction)
        stream = svc.stream_draft(sid, instruction)

        def events():
            try:
                yield from stream
            except (llm.LLMError, OpsTrailError) as exc:
                yield {"event": "error", "error": str(exc)}
            except Exception:
                yield {"event": "error", "error": "สร้างเอกสารไม่สำเร็จ — ลองใหม่อีกครั้ง"}
            finally:
                stream.close()

        def encode():
            for event in events():
                yield f"event: {event['event']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(encode(), media_type="text/event-stream",
                                 headers={"cache-control": "no-cache", "x-accel-buffering": "no"})

    def doc_diff(r: Request, b: dict) -> Any:
        try:
            before, after = int(q(r, "from")), int(q(r, "to"))
        except (ValueError, TypeError) as exc:
            raise OpsTrailError("ระบุ from และ to เป็นเลขเวอร์ชันที่บันทึกแล้ว") from exc
        return ot.doc_diff(_int(r.path_params["id"]), before, after)

    def doc_prompt(r: Request, b: dict) -> Any:
        return {"prompt": fresh().copy_prompt(_int(r.path_params["id"]), q(r, "instruction"))}

    def doc_sources(r: Request, b: dict) -> Any:
        res = fresh().add_doc_sources(
            _int(r.path_params["id"]), _ids(b.get("episode_ids")), b.get("date") or None, b.get("date_to") or None
        )
        res.pop("new_material", None)
        return res

    def doc_download(r: Request, b: dict) -> Any:
        fmt = q(r, "format", "docx")
        if fmt not in ("docx", "md"):
            raise OpsTrailError("format must be docx or md")
        res = ot.export_doc(_int(r.path_params["id"]), fmt, _int(q(r, "version")) or None)
        path = Path(res["files"][0])
        media = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if fmt == "docx"
            else "text/markdown; charset=utf-8"
        )
        return FileResponse(str(path), media_type=media, filename=path.name)

    def search(r: Request, b: dict) -> Any:
        return fresh().search_all(q(r, "q"))

    def recaps(r: Request, b: dict) -> Any:
        return ot.list_recaps(_int(q(r, "limit"), 90))

    # --- AI settings
    def recap_settings(r: Request, b: dict) -> Any:
        return ot.recap_settings()

    def recap_settings_save(r: Request, b: dict) -> Any:
        return ot.save_recap_settings(b.get("teams_webhook_url"), clear=b.get("clear_webhook") is True)

    def llm_get(r: Request, b: dict) -> Any:
        return llm.public_settings(ot.cfg)

    def llm_save(r: Request, b: dict) -> Any:
        key = b.get("api_key")
        if b.get("clear_key"):
            key = ""
        elif key is not None and not str(key).strip():
            key = None  # empty input = keep the stored key
        return llm.save_settings(ot.cfg, {k: v for k, v in b.items() if k not in ("api_key", "clear_key")}, key)

    def llm_test(r: Request, b: dict) -> Any:
        models = llm.list_models(ot.cfg)
        return {"ok": True, "models": models[:200]}

    # --- quality loop
    def profile_get(r: Request, b: dict) -> Any:
        return ot.profile()

    def profile_save(r: Request, b: dict) -> Any:
        return ot.save_profile(str(b.get("author", "")), str(b.get("team", "")))

    def doc_factcheck(r: Request, b: dict) -> Any:
        return ot.fact_check(_int(r.path_params["id"]), _int(q(r, "version")) or None)

    def ai_titles(r: Request, b: dict) -> Any:
        return ot.ai_title_episodes(r.path_params["date"])

    def style_get(r: Request, b: dict) -> Any:
        return ot.style(r.path_params["template"])

    def style_save(r: Request, b: dict) -> Any:
        return ot.save_style(r.path_params["template"], str(b.get("style", "")))

    def style_learn(r: Request, b: dict) -> Any:
        return ot.learn_style(r.path_params["template"])

    async def index(request: Request) -> Response:
        return FileResponse(str(STATIC / "index.html"), headers={"cache-control": "no-cache"})

    async def health(request: Request) -> Response:
        return JSONResponse({"ok": True, "app": "opstrail", "version": __version__})

    routes = [
        Route("/", index),
        Route("/api/health", health),
        Route("/api/status", api(status)),
        Route("/api/capture", api(capture, body=True), methods=["POST"]),
        Route("/api/browser/token", api(browser_token, body=True), methods=["POST"]),
        Route("/api/ingest/browser", api(browser_ingest, body=True), methods=["POST"]),
        Route("/api/day/{date}", api(day)),
        Route("/api/day/{date}/recap", api(make_recap, body=True), methods=["POST"]),
        Route("/api/timeline", api(timeline)),
        Route("/api/episodes/merge", api(merge, body=True), methods=["POST"]),
        Route("/api/episodes/{id:int}", api(episode)),
        Route("/api/episodes/{id:int}", api(episode_update, body=True), methods=["POST"]),
        Route("/api/notes", api(note, body=True), methods=["POST"]),
        Route("/api/shots/{id:int}", api(shot)),
        Route("/api/templates", api(templates)),
        Route("/api/docs", api(docs)),
        Route("/api/docs", api(doc_create, body=True), methods=["POST"]),
        Route("/api/docs/{id:int}", api(doc)),
        Route("/api/docs/{id:int}/meta", api(doc_meta, body=True), methods=["POST"]),
        Route("/api/docs/{id:int}/save", api(doc_save, body=True), methods=["POST"]),
        Route("/api/docs/{id:int}/generate", api(doc_generate, body=True), methods=["POST"]),
        Route("/api/docs/{id:int}/diff", api(doc_diff)),
        Route("/api/docs/{id:int}/prompt", api(doc_prompt)),
        Route("/api/docs/{id:int}/sources", api(doc_sources, body=True), methods=["POST"]),
        Route("/api/docs/{id:int}/download", api(doc_download)),
        Route("/api/recaps", api(recaps)),
        Route("/api/recap/settings", api(recap_settings)),
        Route("/api/recap/settings", api(recap_settings_save, body=True), methods=["POST"]),
        Route("/api/search", api(search)),
        Route("/api/llm", api(llm_get)),
        Route("/api/llm", api(llm_save, body=True), methods=["POST"]),
        Route("/api/llm/test", api(llm_test, body=True), methods=["POST"]),
        Route("/api/profile", api(profile_get)),
        Route("/api/profile", api(profile_save, body=True), methods=["POST"]),
        Route("/api/docs/{id:int}/factcheck", api(doc_factcheck)),
        Route("/api/day/{date}/ai-titles", api(ai_titles, body=True), methods=["POST"]),
        Route("/api/style/{template}", api(style_get)),
        Route("/api/style/{template}", api(style_save, body=True), methods=["POST"]),
        Route("/api/style/{template}/learn", api(style_learn, body=True), methods=["POST"]),
        Mount("/static", app=StaticFiles(directory=str(STATIC)), name="static"),
    ]
    return Starlette(routes=routes, middleware=[Middleware(LocalOnly, port=web_port, extra_hosts=extra_hosts, cfg=ot.cfg)])


def serve(svc: OpsTrail | None = None, port: int | None = None, *, in_thread: bool = False) -> Any:
    """Run uvicorn on 127.0.0.1. With in_thread=True returns the started thread (used by the agent)."""
    import threading

    import uvicorn

    ot = svc or OpsTrail()
    web_port = port or int(ot.cfg.data.get("web", {}).get("port", 8765))
    # log_config=None: don't let uvicorn install console handlers (pythonw has no stdout/stderr);
    # its warnings go to our root logger (~/.opstrail/logs/agent.log when run by the agent).
    config = uvicorn.Config(
        create_app(ot, port=web_port), host="127.0.0.1", port=web_port, log_level="warning", log_config=None
    )
    server = uvicorn.Server(config)
    if not in_thread:
        server.run()
        return server
    thread = threading.Thread(target=server.run, name="opstrail-web", daemon=True)
    thread.start()
    return thread


def url(cfg: Any, path: str = "") -> str:
    port = int(cfg.data.get("web", {}).get("port", 8765))
    return f"http://127.0.0.1:{port}/{path.lstrip('/')}"
