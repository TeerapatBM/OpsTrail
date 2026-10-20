"""`opstrail` command line."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from opstrail import __version__
from opstrail.config import REPO_ROOT, load_config


def _out(obj: Any) -> None:
    if isinstance(obj, str):
        print(obj)
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _svc():
    from opstrail.service import OpsTrail

    return OpsTrail(load_config())


# ----------------------------------------------------------------- commands
def cmd_init(args: argparse.Namespace) -> int:
    cfg = load_config()
    print(f"OpsTrail home : {cfg.home}")
    print(f"config        : {cfg.config_path}")
    print(f"database      : {cfg.db_path}")
    print(f"exports       : {cfg.export_dir}")
    print(f"templates     : {cfg.templates_dir}")
    _svc()  # creates the database
    return 0


def cmd_agent(args: argparse.Namespace) -> int:
    from opstrail.agent.daemon import run_agent

    return run_agent(load_config(), with_hotkeys=not args.no_hotkeys)


def _agent_pid(cfg) -> int:
    from opstrail.agent import osapi

    pid_file = cfg.home / "agent.pid"
    try:
        pid = int(pid_file.read_text().strip() or 0)
    except (OSError, ValueError):
        return 0
    return pid if pid and osapi.agent_alive(pid) else 0


def cmd_stop(args: argparse.Namespace) -> int:
    import signal

    cfg = load_config()
    pid = _agent_pid(cfg)
    if not pid:
        print("agent is not running")
        return 0
    try:
        os.kill(pid, signal.SIGTERM)  # Windows: TerminateProcess
    except OSError as exc:
        print(f"could not stop agent (pid {pid}): {exc}")
        return 1
    for _ in range(50):
        if not _agent_pid(cfg):
            break
        time.sleep(0.1)
    try:
        (cfg.home / "agent.pid").unlink()
    except OSError:
        pass
    print(f"agent stopped (pid {pid})")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    """Stop the agent and start it again in the background (use after updating OpsTrail)."""
    import subprocess

    from opstrail.agent import osapi

    cmd_stop(args)
    kwargs: dict[str, Any] = {"cwd": str(REPO_ROOT), "stdin": subprocess.DEVNULL,
                              "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0x8)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen([osapi.pythonw(), "-m", "opstrail", "agent"], **kwargs)
    cfg = load_config()
    for _ in range(40):
        time.sleep(0.25)
        if _agent_pid(cfg) and _web_alive(cfg):
            break
    print(f"agent started (pid {proc.pid}) — web: http://127.0.0.1:{cfg.web.get('port', 8765)}/")
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from opstrail.mcp_server import run

    run(http=args.http, host=args.host, port=args.port)
    return 0


def _web_alive(cfg) -> bool:
    import urllib.request

    from opstrail.web.app import url

    try:
        with urllib.request.urlopen(url(cfg, "api/health"), timeout=2) as resp:
            return b"opstrail" in resp.read()
    except Exception:
        return False


def cmd_web(args: argparse.Namespace) -> int:
    """Open the web UI; start a server in this process if the agent isn't serving it."""
    import webbrowser

    from opstrail.web.app import serve, url

    cfg = load_config()
    if _web_alive(cfg):
        print(f"OpsTrail web is running: {url(cfg)}")
        if not args.no_browser:
            webbrowser.open(url(cfg))
        return 0
    print(f"Starting OpsTrail web on {url(cfg)} (Ctrl+C to stop)")
    if not args.no_browser:
        import threading

        threading.Timer(1.5, lambda: webbrowser.open(url(cfg))).start()
    serve(_svc())
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    text = " ".join(args.text).strip()
    if not text:
        from opstrail.agent.popup import note

        note(load_config())
        return 0
    svc = _svc()
    _out(svc.add_note(text, args.episode or None, source="cli"))
    return 0


def cmd_task(args: argparse.Namespace) -> int:
    svc = _svc()
    title = " ".join(args.title).strip()
    if args.action == "start" and not title:
        print("usage: opstrail task start <title>")
        return 2
    svc.record("task", {"action": args.action, "title": title}, source="cli")
    svc.refresh()
    print(f"task {args.action}: {title}".rstrip(": "))
    return 0


def cmd_shot(args: argparse.Namespace) -> int:
    from opstrail.agent import osapi
    from opstrail.agent.screenshot import capture

    cfg = load_config()
    if args.delay:
        print(f"capturing in {args.delay}s – switch to the window you want …")
        time.sleep(args.delay)
    osapi.set_dpi_aware()
    fg = osapi.foreground() or {}
    path = capture(cfg, fg, mode="screen" if args.screen else None)
    svc = _svc()
    data = {"path": str(path), "app": fg.get("app", ""), "title": fg.get("title", "")}
    if args.caption:
        data["caption"] = args.caption
    eid = svc.record("screenshot", data, source="cli")
    print(f"saved {path} (shot://{eid})")
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    cfg = load_config()
    cfg.set_paused(True)
    print("OpsTrail capture paused (run `opstrail resume` to continue)")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    cfg = load_config()
    cfg.set_paused(False)
    print("OpsTrail capture resumed")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    svc = _svc()
    svc.refresh()
    _out(svc.status())
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    _out(_svc().refresh())
    return 0


def cmd_timeline(args: argparse.Namespace) -> int:
    svc = _svc()
    svc.refresh()
    res = svc.timeline(args.date, args.types or "", args.limit)
    if args.json:
        _out(res)
        return 0
    print(f"{res['date']} — {res['shown']}/{res['total_events']} events")
    for ev in res["events"]:
        extra = f" [{ev['dur']}]" if ev.get("dur") else ""
        ok = "" if ev.get("ok", True) else " [FAILED]"
        print(f"{ev['time']} {ev['type']:<10} #{ev.get('episode_id') or '-':<4} {ev['text'][:140]}{extra}{ok}")
    return 0


def cmd_episodes(args: argparse.Namespace) -> int:
    svc = _svc()
    svc.refresh()
    eps = svc.rebuild_episodes(args.date) if args.rebuild else svc.list_episodes(args.date, args.to)
    if args.json:
        _out(eps)
        return 0
    if not eps:
        print("no episodes")
    for ep in eps:
        print(f"#{ep['id']:<4} {ep['date']} {ep['time']}  {ep['active']:>7}  {ep['title']}  "
              f"(cmd {ep['commands']}, notes {ep['notes']}, shots {ep['screenshots']})")
    return 0


def cmd_recap(args: argparse.Namespace) -> int:
    svc = _svc()
    res = svc.daily_recap(args.date, save=not args.no_save)
    if args.print:
        print(res["markdown"])
    if not args.no_save:
        print(f"saved as doc session #{res['session_id']} v{res['version']}")
        if args.export:
            _out(svc.export_doc(res["session_id"], args.export))
    return 0


def cmd_docs(args: argparse.Namespace) -> int:
    svc = _svc()
    if args.docs_cmd == "list":
        for s in svc.list_doc_sessions(args.status or "", args.template or "", 100):
            print(f"#{s['session_id']:<4} [{s['status']:<6}] {s['template']:<14} v{s['latest_version']}  {s['title']}")
    elif args.docs_cmd == "show":
        res = svc.get_doc_session(args.id, include_sources=args.sources)
        print(res.pop("latest_markdown") or "(no draft yet)")
        if args.sources:
            print("\n---\n" + res.pop("source_pack"))
    elif args.docs_cmd == "export":
        _out(svc.export_doc(args.id, args.format, args.version or None))
    elif args.docs_cmd == "new":
        ids = [int(x) for x in args.episodes.split(",")] if args.episodes else []
        res = svc.start_doc_session(args.template, args.title, ids, args.date, args.to)
        print(f"created doc session #{res['session_id']} – ask Claude/GPT: “continue_document {res['session_id']}”")
    elif args.docs_cmd == "search":
        _out(svc.search_docs(" ".join(args.query)))
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from opstrail import evals

    if args.eval_cmd == "export":
        svc = _svc()
        svc.refresh()
        out = evals.EVALS_DIR / "days" / f"{args.name}.jsonl"
        n = evals.export_day(svc, args.date, out, anonymize=not args.raw)
        print(f"exported {n} events to {out}")
        print("REVIEW the file before committing (window titles can contain customer names).")
        print(f'Then add a [[case]] with day = "days/{args.name}.jsonl" and date = "{args.date}" to evals/cases.toml')
        return 0
    results = evals.run(use_llm=args.llm, only=args.case or "")
    text = evals.report(results, args.llm)
    out_dir = Path(args.out) if args.out else load_config().home / "evals"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"eval-{time.strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text(text, encoding="utf-8")
    print(text.split("<details>")[0] if not args.verbose else text)
    print(f"report: {path}")
    return 0 if all(r.ok for r in results) else 1


def cmd_purge(args: argparse.Namespace) -> int:
    svc = _svc()
    n = svc.purge(date=args.date, before=args.before)
    print(f"deleted {n} raw events (documents are kept)")
    return 0


def cmd_popup(args: argparse.Namespace) -> int:
    from opstrail.agent import popup

    cfg = load_config()
    if args.kind == "note":
        popup.note(cfg)
    elif args.kind == "task":
        popup.task(cfg)
    elif args.kind == "shot":
        popup.shot(cfg, args.path, args.app or "", args.title or "")
    elif args.kind == "review":
        popup.review(cfg, args.date)
    elif args.kind == "meeting":
        popup.meeting(cfg, args.episode)
    elif args.kind == "toast":
        popup.toast(" ".join(args.message) or "OpsTrail")
    return 0


def cmd_hook(args: argparse.Namespace) -> int:
    """Claude Code PostToolUse hook: reads the hook JSON from stdin and logs an `ai` event."""
    from opstrail.events import make_event, write_inbox

    if os.environ.get("OPSTRAIL_NO_CAPTURE"):  # e.g. AI developers run by scripts/duo.ps1
        return 0
    cfg = load_config()
    if cfg.is_paused():
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    tool = str(payload.get("tool_name") or "")
    tin = payload.get("tool_input") or {}
    data: dict[str, Any] = {"tool": tool or "unknown", "cwd": payload.get("cwd") or ""}
    if tool == "Bash":
        data["cmd"] = tin.get("command", "")
        data["description"] = tin.get("description", "")
        resp = payload.get("tool_response")
        if isinstance(resp, dict) and "interrupted" in resp:
            data["success"] = not resp.get("interrupted")
    elif tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        data["file"] = tin.get("file_path") or tin.get("notebook_path") or ""
    else:
        return 0
    write_inbox(cfg, make_event(cfg, "ai", data, source="claude-code"), "claude-code")
    return 0


def _claude_config_paths() -> list[Path]:
    paths: list[Path] = []
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        paths.append(appdata / "Claude" / "claude_desktop_config.json")
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Packages"
        if local.exists():
            for pkg in local.glob("Claude_*"):
                paths.append(pkg / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json")
    elif sys.platform == "darwin":
        paths.append(Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json")
    else:
        paths.append(Path.home() / ".config" / "Claude" / "claude_desktop_config.json")
    return paths


def cmd_install_claude(args: argparse.Namespace) -> int:
    """Add (or --remove) OpsTrail in Claude Desktop's MCP config (backup first)."""
    entry = {"command": sys.executable, "args": ["-m", "opstrail", "mcp"]}
    if args.remove:
        for path in _claude_config_paths():
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8") or "{}")
            except json.JSONDecodeError:
                continue
            if data.get("mcpServers", {}).pop("opstrail", None) is not None:
                path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"removed 'opstrail' from {path}")
        return 0
    targets = [p for p in _claude_config_paths() if p.parent.exists()] or _claude_config_paths()[:1]
    for path in targets:
        data: dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8") or "{}")
            except json.JSONDecodeError:
                print(f"! {path} is not valid JSON – skipped (fix it manually)")
                continue
            shutil.copy2(path, path.with_suffix(".json.bak"))
        data.setdefault("mcpServers", {})["opstrail"] = entry
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"added 'opstrail' MCP server to {path}")
    print("Restart Claude Desktop (quit from the tray icon) to load it.")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config()
    checks: list[tuple[str, bool, str]] = []
    checks.append(("python >= 3.10", sys.version_info >= (3, 10), sys.version.split()[0]))
    mods = ("mcp", "docx", "mss", "psutil") if sys.platform == "win32" else ("mcp", "docx", "pynput", "mss", "psutil")
    for mod in mods:
        try:
            __import__(mod)
            checks.append((f"import {mod}", True, ""))
        except Exception as exc:  # pragma: no cover - environment specific
            checks.append((f"import {mod}", False, str(exc)))
    try:
        import tkinter  # noqa: F401

        checks.append(("tkinter (popups)", True, ""))
    except Exception as exc:
        checks.append(("tkinter (popups)", False, str(exc)))
    svc = _svc()
    st = svc.status()
    checks.append(("templates found", bool(st["templates"]), ", ".join(st["templates"]) or str(cfg.templates_dir)))
    seen = st["agent_last_seen_s"]
    checks.append(("agent running", st["agent_running"], f"last seen {seen}s ago" if seen is not None else "not running"))
    checks.append(("capturing (not paused)", st["capturing"], ""))
    try:
        from opstrail.agent import osapi

        fg = osapi.foreground()
        checks.append(("foreground window detection", fg is not None, str(fg.get("app")) if fg else "n/a"))
    except Exception as exc:
        checks.append(("foreground window detection", False, str(exc)))
    from opstrail.web.app import url as web_url

    checks.append(("web UI reachable", _web_alive(cfg), web_url(cfg)))
    profile_hook = REPO_ROOT / "hooks" / "powershell" / "OpsTrail.ps1"
    checks.append(("PowerShell hook file", profile_hook.exists(), str(profile_hook)))
    for name, ok, detail in checks:
        print(f"[{'OK' if ok else '!!'}] {name}{(' — ' + detail) if detail else ''}")
    return 0


# ------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="opstrail", description="OpsTrail – capture ops work, write docs via MCP")
    p.add_argument("--version", action="version", version=f"opstrail {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create ~/.opstrail, config and database").set_defaults(fn=cmd_init)

    w = sub.add_parser("web", help="open the web UI (http://127.0.0.1:8765)")
    w.add_argument("--no-browser", action="store_true")
    w.set_defaults(fn=cmd_web)

    sub.add_parser("stop", help="stop the background agent").set_defaults(fn=cmd_stop)
    sub.add_parser("restart", help="restart the background agent (after an update)").set_defaults(fn=cmd_restart)

    a = sub.add_parser("agent", help="run the capture agent (foreground)")
    a.add_argument("--no-hotkeys", action="store_true")
    a.set_defaults(fn=cmd_agent)

    m = sub.add_parser("mcp", help="run the MCP server (stdio by default)")
    m.add_argument("--http", action="store_true", help="streamable HTTP instead of stdio")
    m.add_argument("--host")
    m.add_argument("--port", type=int)
    m.set_defaults(fn=cmd_mcp)

    n = sub.add_parser("note", help="add a note (no text = popup)")
    n.add_argument("text", nargs="*")
    n.add_argument("--episode", type=int, default=0)
    n.set_defaults(fn=cmd_note)

    t = sub.add_parser("task", help="mark the start/stop of a work item")
    t.add_argument("action", choices=["start", "stop"])
    t.add_argument("title", nargs="*")
    t.set_defaults(fn=cmd_task)

    s = sub.add_parser("shot", help="take a screenshot of the active window")
    s.add_argument("--delay", type=int, default=0)
    s.add_argument("--screen", action="store_true", help="whole monitor instead of the window")
    s.add_argument("--caption", default="")
    s.set_defaults(fn=cmd_shot)

    sub.add_parser("pause", help="pause capture").set_defaults(fn=cmd_pause)
    sub.add_parser("resume", help="resume capture").set_defaults(fn=cmd_resume)
    sub.add_parser("status", help="show status").set_defaults(fn=cmd_status)
    sub.add_parser("ingest", help="process the inbox now").set_defaults(fn=cmd_ingest)
    sub.add_parser("doctor", help="check the installation").set_defaults(fn=cmd_doctor)

    tl = sub.add_parser("timeline", help="show raw events for a date")
    tl.add_argument("--date", default="today")
    tl.add_argument("--types", default="")
    tl.add_argument("--limit", type=int, default=200)
    tl.add_argument("--json", action="store_true")
    tl.set_defaults(fn=cmd_timeline)

    e = sub.add_parser("episodes", help="list work items")
    e.add_argument("--date", default="today")
    e.add_argument("--to", default=None)
    e.add_argument("--rebuild", action="store_true", help="regroup this date from scratch")
    e.add_argument("--json", action="store_true")
    e.set_defaults(fn=cmd_episodes)

    r = sub.add_parser("recap", help="build the daily worklog")
    r.add_argument("--date", default="today")
    r.add_argument("--print", action="store_true")
    r.add_argument("--no-save", action="store_true")
    r.add_argument("--export", choices=["md", "docx", "both"])
    r.set_defaults(fn=cmd_recap)

    d = sub.add_parser("docs", help="document sessions")
    dsub = d.add_subparsers(dest="docs_cmd", required=True)
    dl = dsub.add_parser("list")
    dl.add_argument("--status")
    dl.add_argument("--template")
    ds = dsub.add_parser("show")
    ds.add_argument("id", type=int)
    ds.add_argument("--sources", action="store_true")
    de = dsub.add_parser("export")
    de.add_argument("id", type=int)
    de.add_argument("--format", default="docx", choices=["md", "docx", "both"])
    de.add_argument("--version", type=int, default=0)
    dn = dsub.add_parser("new")
    dn.add_argument("template")
    dn.add_argument("title")
    dn.add_argument("--episodes", default="")
    dn.add_argument("--date", default=None)
    dn.add_argument("--to", default=None)
    dq = dsub.add_parser("search")
    dq.add_argument("query", nargs="+")
    d.set_defaults(fn=cmd_docs)

    ev = sub.add_parser("eval", help="run the golden-day evaluation (referee for Claude/GPT changes)")
    ev.add_argument("eval_cmd", nargs="?", choices=["run", "export"], default="run")
    ev.add_argument("--llm", action="store_true", help="also generate documents with your AI provider")
    ev.add_argument("--case", default="")
    ev.add_argument("--out", default="")
    ev.add_argument("--verbose", action="store_true")
    ev.add_argument("--date", default="today", help="export: the day to export")
    ev.add_argument("--name", default="my-day", help="export: fixture name")
    ev.add_argument("--raw", action="store_true", help="export without anonymising IPs/users")
    ev.set_defaults(fn=cmd_eval)

    pg = sub.add_parser("purge", help="delete raw events (privacy)")
    grp = pg.add_mutually_exclusive_group(required=True)
    grp.add_argument("--date")
    grp.add_argument("--before")
    pg.set_defaults(fn=cmd_purge)

    pu = sub.add_parser("popup", help=argparse.SUPPRESS)
    pu.add_argument("kind", choices=["note", "task", "shot", "review", "toast", "meeting"])
    pu.add_argument("--episode", type=int, default=0)
    pu.add_argument("message", nargs="*")
    pu.add_argument("--path", default="")
    pu.add_argument("--app", default="")
    pu.add_argument("--title", default="")
    pu.add_argument("--date", default=None)
    pu.set_defaults(fn=cmd_popup)

    h = sub.add_parser("hook", help="hook entry points (claude-code)")
    h.add_argument("kind", choices=["claude-code"])
    h.set_defaults(fn=cmd_hook)

    ic = sub.add_parser("install-claude", help="register OpsTrail in Claude Desktop")
    ic.add_argument("--remove", action="store_true", help="unregister instead")
    ic.set_defaults(fn=cmd_install_claude)
    return p


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
            except Exception:
                pass
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except Exception as exc:
        from opstrail.service import OpsTrailError

        if isinstance(exc, OpsTrailError):
            print(f"error: {exc}", file=sys.stderr)
            return 2
        raise
