"""Move events from the inbox (written by hooks/CLI) into the SQLite store."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from opstrail.activity import classify_row
from opstrail.config import Config
from opstrail.events import normalize, parse_tsv_line
from opstrail.redact import compile_extra, redact_obj
from opstrail.store import Store

log = logging.getLogger("opstrail.ingest")

STALE_PROCESSING_S = 600


def _claim(path: Path) -> Path | None:
    """Atomically rename an inbox file so only one process ingests it."""
    target = path.with_name(f"{path.name}.processing-{os.getpid()}-{int(time.time() * 1000)}")
    try:
        os.replace(path, target)
        return target
    except (PermissionError, FileNotFoundError, OSError):
        return None  # still being written (Windows) or claimed by someone else


def _candidates(cfg: Config) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    if not cfg.inbox_dir.exists():
        return out
    now = time.time()
    for path in sorted(cfg.inbox_dir.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        if name.endswith(".jsonl") or name.endswith(".tsv"):
            out.append((path, "jsonl" if name.endswith(".jsonl") else "tsv"))
        elif ".processing-" in name:
            # crash recovery: a claimed file that was never finished
            try:
                if now - path.stat().st_mtime > STALE_PROCESSING_S:
                    kind = "tsv" if ".tsv.processing-" in name else "jsonl"
                    out.append((path, kind))
            except FileNotFoundError:
                continue
    return out


def ingest_inbox(cfg: Config, store: Store) -> int:
    """Ingest all pending inbox files. Returns the number of new events stored."""
    if not cfg.inbox_dir.exists():
        return 0
    extra = compile_extra(cfg.redaction.get("extra_patterns"))
    inserted = 0
    for path, kind in _candidates(cfg):
        claimed = path if ".processing-" in path.name else _claim(path)
        if claimed is None:
            continue
        try:
            raw = claimed.read_bytes().decode("utf-8-sig", errors="replace")
        except FileNotFoundError:
            continue
        rejected: list[str] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = parse_tsv_line(line, cfg) if kind == "tsv" else json.loads(line)
                event = redact_obj(event, extra)
                row = classify_row(cfg.home, normalize(event, cfg))
                if store.insert_event(row) is not None:
                    inserted += 1
            except Exception as exc:  # keep going – one bad line must not block the rest
                rejected.append(f"{exc}: {line[:300]}")
        if rejected:
            with (cfg.inbox_dir / "rejected.log").open("a", encoding="utf-8") as fh:
                for item in rejected:
                    fh.write(item + "\n")
            log.warning("rejected %d line(s) from %s", len(rejected), path.name)
        try:
            claimed.unlink()
        except FileNotFoundError:
            pass
    return inserted


def store_event(cfg: Config, store: Store, event: dict) -> int | None:
    """Redact + normalise + insert a single event directly (used by the agent/MCP)."""
    extra = compile_extra(cfg.redaction.get("extra_patterns"))
    row = classify_row(cfg.home, normalize(redact_obj(event, extra), cfg))
    return store.insert_event(row)
