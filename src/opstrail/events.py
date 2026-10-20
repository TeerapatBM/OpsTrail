"""Event schema v1: creation, validation, normalisation and inbox writing."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import Any

from opstrail.config import Config

SCHEMA_VERSION = 1
EVENT_TYPES = {"shell", "window", "note", "screenshot", "task", "ai", "idle", "system"}
REQUIRED_DATA = {
    "shell": "cmd",
    "window": "app",
    "note": "text",
    "screenshot": "path",
    "task": "action",
    "ai": "tool",
}
MAX_STR = 4000

_FRACTION = re.compile(r"(\.\d{1,6})\d*")


def parse_ts(value: Any, tz: tzinfo) -> datetime:
    """Parse ISO-8601 (any fraction length, 'Z') or epoch seconds into an aware datetime."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing ts")
    text = value.strip()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return datetime.fromtimestamp(float(text), tz)
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    # Python 3.10 only accepts exactly 3 or 6 fractional digits -> normalise to 6.
    text = _FRACTION.sub(lambda m: (m.group(1) + "000000")[:7], text, count=1)
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_STR:
        return value[:MAX_STR] + "…"
    if isinstance(value, dict):
        return {k: _clip(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip(v) for v in value]
    return value


def make_event(
    cfg: Config,
    type_: str,
    data: dict[str, Any],
    *,
    source: str = "cli",
    ts: datetime | None = None,
    duration_s: float | None = None,
) -> dict[str, Any]:
    when = ts or datetime.now(cfg.tz)
    event: dict[str, Any] = {
        "v": SCHEMA_VERSION,
        "ts": when.isoformat(timespec="seconds"),
        "type": type_,
        "source": source,
        "host": cfg.host,
        "user": cfg.user,
        "data": data,
    }
    if duration_s is not None:
        event["duration_s"] = round(float(duration_s), 2)
    return event


def normalize(event: dict[str, Any], cfg: Config) -> dict[str, Any]:
    """Validate an incoming event and convert it to the store row format.

    Raises ValueError for invalid input.
    """
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    type_ = event.get("type")
    if type_ not in EVENT_TYPES:
        raise ValueError(f"unknown type: {type_!r}")
    data = event.get("data") or {}
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    required = REQUIRED_DATA.get(type_)
    if required and not str(data.get(required) or "").strip():
        raise ValueError(f"data.{required} is required for {type_}")
    dt = parse_ts(event.get("ts"), cfg.tz).astimezone(cfg.tz)
    duration = event.get("duration_s")
    try:
        duration = None if duration in (None, "") else max(0.0, float(duration))
    except (TypeError, ValueError):
        duration = None
    data = _clip(data)
    row = {
        "ts": dt.isoformat(timespec="seconds"),
        "epoch": dt.timestamp(),
        "local_date": dt.date().isoformat(),
        "type": type_,
        "source": str(event.get("source") or "unknown")[:40],
        "host": str(event.get("host") or cfg.host)[:120],
        "user": str(event.get("user") or cfg.user)[:120],
        "duration_s": duration,
        "data": data,
    }
    row["text"] = event_text(type_, data)
    row["hash"] = event_hash(row)
    return row


def event_hash(row: dict[str, Any]) -> str:
    payload = json.dumps(
        [row["epoch"], row["type"], row["source"], row["host"], row["data"]],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def event_text(type_: str, data: dict[str, Any]) -> str:
    """One-line human summary used for search and compact timelines."""
    if type_ == "shell":
        return str(data.get("cmd", ""))
    if type_ == "window":
        title = data.get("title") or ""
        text = f"{data.get('app', '')} — {title}".strip(" —")
        return f"{text} [background]" if data.get("presence") else text
    if type_ == "note":
        return str(data.get("text", ""))
    if type_ == "screenshot":
        return str(data.get("caption") or data.get("title") or "screenshot")
    if type_ == "task":
        return f"task {data.get('action', '')}: {data.get('title', '')}".strip(": ")
    if type_ == "ai":
        detail = data.get("cmd") or data.get("file") or data.get("description") or ""
        return f"[{data.get('tool', 'ai')}] {detail}".strip()
    if type_ == "system":
        return str(data.get("message", ""))
    return type_


def is_focus_window(ev: dict[str, Any]) -> bool:
    """A window the user had in focus (not a background meeting-presence segment, see SPEC §4)."""
    return ev.get("type") == "window" and not (ev.get("data") or {}).get("presence")


def parse_tsv_line(line: str, cfg: Config) -> dict[str, Any]:
    """Parse the compact POSIX hook format (see SPEC §4)."""
    parts = line.rstrip("\r\n").split("\t")
    if len(parts) < 5 or parts[0] != "tsv1":
        raise ValueError("bad tsv1 line")

    def b64(s: str) -> str:
        return base64.b64decode(s.encode("ascii")).decode("utf-8", errors="replace") if s else ""

    epoch = float(parts[1])
    exit_code = int(parts[2]) if parts[2].lstrip("-").isdigit() else None
    shell = parts[7] if len(parts) > 7 else "bash"
    return {
        "v": 1,
        "ts": epoch,
        "type": "shell",
        "source": shell or "bash",
        "host": parts[5] if len(parts) > 5 and parts[5] else cfg.host,
        "user": parts[6] if len(parts) > 6 and parts[6] else cfg.user,
        "data": {
            "cmd": b64(parts[4]),
            "cwd": b64(parts[3]),
            "exit_code": exit_code,
            "success": exit_code == 0 if exit_code is not None else None,
            "shell": shell,
            "session": parts[8] if len(parts) > 8 else "",
        },
    }


def write_inbox(cfg: Config, event: dict[str, Any], name: str = "cli") -> Path:
    """Append one event to the inbox (used by CLI, hooks, popups)."""
    cfg.inbox_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{name}-{cfg.host}-{os.getpid()}")
    path = cfg.inbox_dir / f"{safe}.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return path


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
