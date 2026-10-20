"""Formatting helpers shared by the source pack, the daily recap and the CLI."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, tzinfo
from typing import Any

from opstrail.episodes import app_display

MAX_COMMANDS_PER_EPISODE = 150


def hhmm(epoch: float, tz: tzinfo, seconds: bool = False) -> str:
    return datetime.fromtimestamp(epoch, tz).strftime("%H:%M:%S" if seconds else "%H:%M")


def fmt_duration(seconds: float | int | None) -> str:
    s = int(round(float(seconds or 0)))
    if s < 60:
        return f"{s}s"
    h, rem = divmod(s, 3600)
    m = rem // 60
    return f"{h}h {m:02d}m" if h else f"{m}m"


def compact_event(ev: dict[str, Any], tz: tzinfo) -> dict[str, Any]:
    d = ev.get("data") or {}
    out: dict[str, Any] = {
        "id": ev["id"],
        "time": hhmm(ev["epoch"], tz, seconds=True),
        "type": ev["type"],
        "text": ev.get("text") or "",
    }
    if ev.get("duration_s"):
        out["dur"] = fmt_duration(ev["duration_s"])
    if ev.get("episode_id"):
        out["episode_id"] = ev["episode_id"]
    if ev["type"] in ("shell", "ai"):
        if d.get("cwd"):
            out["cwd"] = d["cwd"]
        if d.get("success") is not None:
            out["ok"] = bool(d["success"])
    if ev["type"] == "screenshot":
        out["ref"] = f"shot://{ev['id']}"
    return out


def command_lines(events: list[dict[str, Any]], tz: tzinfo, limit: int = MAX_COMMANDS_PER_EPISODE) -> list[str]:
    """Chronological command list with consecutive duplicates collapsed."""
    lines: list[str] = []
    last_key = None
    repeat = 0
    for ev in events:
        if ev["type"] not in ("shell", "ai"):
            continue
        d = ev.get("data") or {}
        cmd = str(d.get("cmd") or d.get("file") or d.get("description") or "").strip()
        if not cmd:
            continue
        key = (cmd, d.get("cwd"))
        if key == last_key:
            repeat += 1
            lines[-1] = lines[-1].split("  (x")[0] + f"  (x{repeat + 1})"
            continue
        last_key, repeat = key, 0
        flag = ""
        if d.get("success") is False:
            code = d.get("exit_code")
            flag = f"[FAILED{' exit ' + str(code) if code not in (None, '') else ''}] "
        origin = "[AI:" + str(d.get("tool")) + "] " if ev["type"] == "ai" else ""
        cwd = f"({d['cwd']}) " if d.get("cwd") else ""
        one_line = cmd.replace("\r", "").replace("\n", " ⏎ ")
        lines.append(f"{hhmm(ev['epoch'], tz)} {flag}{origin}{cwd}{one_line}")
    if len(lines) > limit:
        hidden = len(lines) - limit
        lines = lines[: limit // 2] + [f"… ({hidden} more commands omitted) …"] + lines[-limit // 2 :]
    return lines


def window_summary(events: list[dict[str, Any]], top: int = 12) -> list[tuple[str, float]]:
    totals: Counter[str] = Counter()
    for ev in events:
        if ev["type"] != "window":
            continue
        d = ev.get("data") or {}
        title = str(d.get("title") or "").strip()
        label = f"{app_display(d.get('app'))} — {title}" if title else app_display(d.get("app"))
        totals[label] += float(ev.get("duration_s") or 0)
    return totals.most_common(top)


def episode_header(ep: dict[str, Any], tz: tzinfo) -> str:
    stats = ep.get("stats") or {}
    return (
        f"{ep['local_date']} {hhmm(ep['start_epoch'], tz)}–{hhmm(ep['end_epoch'], tz)}"
        f" (active {fmt_duration(stats.get('active_s'))})"
    )


def episode_pack(ep: dict[str, Any], events: list[dict[str, Any]], tz: tzinfo) -> str:
    """Markdown block with every fact an AI needs to document one episode."""
    stats = ep.get("stats") or {}
    out = [f"### Episode #{ep['id']} — {ep.get('title') or 'Untitled'}"]
    out.append(f"- When: {episode_header(ep, tz)}")
    if ep.get("tags"):
        out.append(f"- Tags: {', '.join(ep['tags'])}")
    if stats.get("targets"):
        out.append(f"- Target hosts: {', '.join(stats['targets'])}")
    if ep.get("origin") == "meeting":
        out.append(f"- Type: MEETING — subject “{stats.get('meeting_subject') or ep.get('title')}”"
                   " (only the window title is captured; the user's notes hold the content)")
    if stats.get("activities"):
        from opstrail.activity import label as act_label

        acts = ", ".join(f"{act_label(a)} {fmt_duration(sec)}" for a, sec in list(stats["activities"].items())[:6] if sec)
        if acts:
            out.append(f"- Activities: {acts}")
    if stats.get("consoles"):
        out.append(f"- Consoles: {', '.join(stats['consoles'])}")
    if stats.get("chats"):
        out.append(f"- Chatted with: {', '.join(stats['chats'])}")
    if stats.get("top_apps"):
        out.append(f"- Apps: {', '.join(stats['top_apps'])}")
    out.append(
        f"- Counts: {stats.get('commands', 0)} commands ({stats.get('failed_commands', 0)} failed), "
        f"{stats.get('notes', 0)} notes, {stats.get('screenshots', 0)} screenshots"
    )

    notes = [e for e in events if e["type"] == "note"]
    tasks = [e for e in events if e["type"] == "task"]
    if notes or tasks:
        out.append("\n**Notes & markers from the user (most important context — the 'why')**")
        for ev in sorted(notes + tasks, key=lambda e: e["epoch"]):
            out.append(f"- {hhmm(ev['epoch'], tz)} {ev.get('text')}")

    cmds = command_lines(events, tz)
    if cmds:
        out.append("\n**Commands (chronological, secrets already redacted)**")
        out.append("```text")
        out.extend(cmds)
        out.append("```")

    windows = window_summary(events)
    if windows:
        out.append("\n**Windows / pages used (by focus time)**")
        for label, secs in windows:
            out.append(f"- {fmt_duration(secs)} — {label}")

    shots = [e for e in events if e["type"] == "screenshot"]
    if shots:
        out.append("\n**Screenshots (embed with `![caption](shot://ID)`)**")
        for ev in shots:
            d = ev.get("data") or {}
            caption = d.get("caption") or ""
            where = f"{app_display(d.get('app'))} — {d.get('title') or ''}".strip(" —")
            out.append(f"- shot://{ev['id']} — {hhmm(ev['epoch'], tz)} {where}{(' — ' + caption) if caption else ''}")
    return "\n".join(out)
