"""Incremental grouping of raw events into episodes (work items). See SPEC §5."""

from __future__ import annotations

import re
import time
from collections import Counter
from typing import Any

from opstrail.config import Config
from opstrail.events import is_focus_window
from opstrail.store import Store

APP_NAMES = {
    "pwsh.exe": "PowerShell",
    "powershell.exe": "PowerShell",
    "powershell_ise.exe": "PowerShell ISE",
    "windowsterminal.exe": "Terminal",
    "cmd.exe": "CMD",
    "code.exe": "VS Code",
    "cursor.exe": "Cursor",
    "msedge.exe": "Edge",
    "chrome.exe": "Chrome",
    "firefox.exe": "Firefox",
    "brave.exe": "Brave",
    "mstsc.exe": "Remote Desktop",
    "putty.exe": "PuTTY",
    "mobaxterm.exe": "MobaXterm",
    "winscp.exe": "WinSCP",
    "filezilla.exe": "FileZilla",
    "explorer.exe": "Explorer",
    "ms-teams.exe": "Teams",
    "teams.exe": "Teams",
    "outlook.exe": "Outlook",
    "olk.exe": "Outlook",
    "winword.exe": "Word",
    "excel.exe": "Excel",
    "powerpnt.exe": "PowerPoint",
    "notepad.exe": "Notepad",
    "notepad++.exe": "Notepad++",
    "mmc.exe": "MMC",
    "ssms.exe": "SSMS",
    "vmconnect.exe": "Hyper-V",
    "vmware.exe": "VMware",
    "vmrc.exe": "VMware Remote Console",
    "claude.exe": "Claude",
    "chatgpt.exe": "ChatGPT",
    "wireshark.exe": "Wireshark",
    "postman.exe": "Postman",
}

STOPWORDS = set(
    """
    the and for with from your you are this that not all any can new tab tabs page pages home untitled
    microsoft edge google chrome firefox mozilla brave windows window powershell pwsh visual studio code
    explorer file files folder open save edit view help tools terminal command prompt cmd bash zsh shell
    https http www com net org html exe get set select object where string null true false sudo cd ls dir
    cat echo clear exit history man vim nano grep awk sed head tail less more type write output item
    content path location list show new-item remove-item copy-item move-item out-file format-table
    teams outlook mail inbox search claude chatgpt copilot settings profile login sign signin user users
    work personal and properties document documents desktop downloads notepad word excel powerpoint
    python python3 pip git node npm main preview loading microsoft365 office meeting chat chats activity
    redacted password todo opstrail ot-note ot-task ot-shot
    """.split()
)

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,}")
TARGET_PATTERNS = [
    re.compile(r"(?i)\b(?:ssh|sftp|mosh)\s+(?:-\S+\s+(?:\S+\s+)?)*(?:[\w.-]+@)?([\w.-]+)"),
    re.compile(r"(?i)\bscp\b.*?\s(?:[\w.-]+@)?([\w.-]+):"),
    re.compile(r"(?i)-ComputerName\s+['\"]?([\w.-]+)"),
    re.compile(r"(?i)\bmstsc\b.*?/v:([\w.-]+)"),
    re.compile(r"(?i)\bwinrs\b.*?-r(?:emote)?:([\w.-]+)"),
    re.compile(r"(?i)\b(?:telnet|nc|ncat)\s+([\w.-]+)"),
]


def app_display(app: str | None) -> str:
    if not app:
        return "Unknown"
    key = app.lower()
    if key in APP_NAMES:
        return APP_NAMES[key]
    return re.sub(r"\.exe$", "", app, flags=re.I)


def extract_targets(cmd: str) -> list[str]:
    found = []
    for pattern in TARGET_PATTERNS:
        for match in pattern.finditer(cmd or ""):
            host = match.group(1).strip(".-")
            if host and not host.startswith("-") and host.lower() not in {"localhost", "-p", "-i"}:
                found.append(host)
    return found


def _event_haystack(ev: dict[str, Any]) -> str:
    d = ev.get("data") or {}
    parts = [ev.get("text") or "", str(d.get("cwd") or ""), str(d.get("title") or "")]
    return " ".join(parts).lower()


def project_label(ev: dict[str, Any], projects: dict[str, list[str]]) -> str | None:
    if not projects:
        return None
    hay = _event_haystack(ev)
    for name, keywords in projects.items():
        for kw in keywords or []:
            if kw and str(kw).lower() in hay:
                return name
    return None


def _span(ev: dict[str, Any]) -> tuple[float, float]:
    start = float(ev["epoch"])
    return start, start + float(ev.get("duration_s") or 0.0)


def compute_stats(events: list[dict[str, Any]], projects: dict[str, list[str]] | None = None) -> dict[str, Any]:
    apps: Counter[str] = Counter()
    keywords: Counter[str] = Counter()
    targets: Counter[str] = Counter()
    project_hits: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    failed = 0
    window_s = 0.0
    activities: Counter[str] = Counter()
    meeting_subjects: Counter[str] = Counter()
    chats: Counter[str] = Counter()
    consoles: Counter[str] = Counter()
    # notes/tasks annotate work; they don't stretch its time span (unless they are all there is)
    timed = [e for e in events if e["type"] not in ("note", "task")] or events
    start = min((_span(e)[0] for e in timed), default=0.0)
    end = max((_span(e)[1] for e in timed), default=0.0)
    for ev in events:
        d = ev.get("data") or {}
        t = ev["type"]
        counts[t] += 1
        weight = 1.0
        if t == "window":
            dur = float(ev.get("duration_s") or 0.0)
            if is_focus_window(ev):  # background meeting presence overlaps focus time: count it once
                window_s += dur
                apps[app_display(d.get("app"))] += dur
            weight = max(1.0, dur / 30.0)
            text = str(d.get("title") or "")
        elif t in ("shell", "ai"):
            text = str(d.get("cmd") or d.get("file") or d.get("description") or "")
            weight = 2.0
            if d.get("success") is False:
                failed += 1
            for host in extract_targets(text):
                targets[host] += 1
        elif t == "note":
            text = str(d.get("text") or "")
            weight = 3.0
        else:
            text = ev.get("text") or ""
        for token in TOKEN_RE.findall(text):
            low = token.lower().strip(".:-")
            if len(low) < 3 or low in STOPWORDS or low.isdigit():
                continue
            keywords[low] += weight
        if projects:
            label = project_label(ev, projects)
            if label:
                project_hits[label] += weight
        act = ev.get("activity") or ""
        subj = (ev.get("subject") or "").strip()
        if act and t in ("window", "shell", "ai"):
            activities[act] += float(ev.get("duration_s") or 0.0) if t == "window" else 30.0
        if act == "meeting":
            meeting_subjects[subj or "ประชุม"] += float(ev.get("duration_s") or 1.0)
        elif act == "chat" and subj and subj != "Microsoft Teams":
            chats[subj] += float(ev.get("duration_s") or 1.0)
        elif act == "console" and subj:
            consoles[subj] += float(ev.get("duration_s") or 1.0)
    active_s = window_s if window_s > 0 else max(0.0, end - start)
    return {
        "start_epoch": start,
        "end_epoch": end,
        "active_s": round(active_s),
        "event_counts": dict(counts),
        "commands": counts.get("shell", 0) + counts.get("ai", 0),
        "failed_commands": failed,
        "notes": counts.get("note", 0),
        "screenshots": counts.get("screenshot", 0),
        "top_apps": [a for a, _ in apps.most_common(4)],
        "keywords": [k for k, _ in keywords.most_common(6)],
        "targets": [h for h, _ in targets.most_common(5)],
        "project": project_hits.most_common(1)[0][0] if project_hits else None,
        "activities": {k: round(v) for k, v in activities.most_common()},
        "meeting_subject": meeting_subjects.most_common(1)[0][0] if meeting_subjects else None,
        "chats": [c for c, _ in chats.most_common(5)],
        "consoles": [c for c, _ in consoles.most_common(3)],
    }


def auto_title(stats: dict[str, Any], origin: str = "auto") -> str:
    if origin == "meeting":
        return f"ประชุม: {stats.get('meeting_subject') or 'ไม่ระบุหัวข้อ'}"
    acts = stats.get("activities") or {}
    total = sum(acts.values()) or 1
    console = (stats.get("consoles") or [None])[0]
    if stats.get("project"):
        head = stats["project"]
    elif console and acts.get("console", 0) / total >= 0.3:
        head = console
    elif acts and max(acts, key=acts.get) == "chat" and stats.get("chats"):
        return f"แชท: {', '.join(stats['chats'][:2])}"
    else:
        head = (stats.get("top_apps") or ["Work"])[0]
    keywords = [k for k in stats.get("keywords", []) if k.lower() != str(head).lower()][:3]
    targets = stats.get("targets") or []
    detail = ", ".join(keywords)
    if targets:
        detail = f"{detail} @ {targets[0]}" if detail else f"@ {targets[0]}"
    return f"{head}: {detail}" if detail else str(head)


def refresh_episode(store: Store, episode_id: int, cfg: Config) -> None:
    ep = store.get_episode(episode_id)
    if not ep:
        return
    events = store.events_for_episode(episode_id)
    if not events:
        return
    stats = compute_stats(events, cfg.projects)
    fields: dict[str, Any] = {
        "stats": stats,
        "start_epoch": stats["start_epoch"] or ep["start_epoch"],
        "end_epoch": stats["end_epoch"] or ep["end_epoch"],
    }
    if not ep["title_locked"]:
        fields["title"] = auto_title(stats, ep.get("origin", "auto"))
    tags = list(ep["tags"])
    if stats.get("project") and stats["project"] not in tags:
        tags.insert(0, stats["project"])
        fields["tags"] = tags
    store.update_episode(episode_id, **fields)


def _smooth_labels(
    events: list[dict[str, Any]], labels: list[str | None], start_label: str | None, min_run: float
) -> list[str | None]:
    """Forward-fill missing labels and absorb short interior runs into the previous label."""
    filled: list[str | None] = []
    prev = start_label
    for label in labels:
        prev = label if label is not None else prev
        filled.append(prev)
    # build runs
    runs: list[list[int]] = []
    for i, label in enumerate(filled):
        if runs and filled[runs[-1][0]] == label:
            runs[-1].append(i)
        else:
            runs.append([i])
    for r_index in range(1, len(runs) - 1):  # interior runs only; the tail is handled by deferral
        run = runs[r_index]
        first, last = events[run[0]], events[run[-1]]
        span = _span(last)[1] - _span(first)[0]
        if span < min_run:
            previous_label = filled[runs[r_index - 1][-1]]
            for i in run:
                filled[i] = previous_label
    return filled


def assign_episodes(store: Store, cfg: Config, date: str | None = None, now: float | None = None) -> set[int]:
    """Assign unassigned events to episodes. Returns ids of touched episodes."""
    dates = [date] if date else store.dates_with_unassigned()
    touched: set[int] = set()
    for d in dates:
        touched |= _assign_for_date(store, cfg, d, now if now is not None else time.time())
    return touched


def _assign_for_date(store: Store, cfg: Config, date: str, now: float) -> set[int]:
    events = [e for e in store.events_for_date(date, unassigned_only=True) if e["type"] not in ("idle", "system")]
    if not events:
        return set()
    split_gap = float(cfg.episodes.get("idle_split_min", 25)) * 60
    note_attach = float(cfg.episodes.get("note_attach_min", 15)) * 60
    min_run = float(cfg.episodes.get("min_run_min", 5)) * 60
    projects = cfg.projects
    is_today = date == cfg.today()

    episodes = store.episodes_between(date)
    work_eps = [e for e in episodes if e.get("origin") != "meeting"]
    current = max(work_eps, key=lambda e: e["end_epoch"]) if work_eps else None

    def label_of(ep: dict[str, Any] | None) -> str | None:
        if not ep or ep.get("origin") == "meeting":
            return None
        return (ep.get("stats") or {}).get("project") or (ep["tags"][0] if ep.get("tags") else None)

    touched: set[int] = set()
    pending: dict[int, list[int]] = {}

    def assign(ev: dict[str, Any], ep: dict[str, Any], extend: bool = True) -> None:
        pending.setdefault(ep["id"], []).append(ev["id"])
        if extend:
            s, e = _span(ev)
            ep["start_epoch"] = min(ep["start_epoch"], s)
            ep["end_epoch"] = max(ep["end_epoch"], e)
        touched.add(ep["id"])

    def new_episode(ev: dict[str, Any], label: str | None, **kw: Any) -> dict[str, Any]:
        s, e = _span(ev)
        eid = store.create_episode(date, s, e, tags=[label] if label else [], **kw)
        ep = store.get_episode(eid)
        assert ep is not None
        episodes.append(ep)
        return ep

    # --- meetings first: contiguous meeting-window events (same subject) form one meeting episode
    meeting_gap = float(cfg.data.get("meetings", {}).get("merge_gap_min", 10)) * 60
    blocks: list[dict[str, Any]] = []
    for ev in (e for e in events if e.get("activity") == "meeting"):
        subj = (ev.get("subject") or "").strip() or "ไม่ระบุหัวข้อ"
        s0, e0 = _span(ev)
        blk = next((b for b in reversed(blocks) if b["subject"] == subj and s0 - b["end"] <= meeting_gap), None)
        if blk:
            blk["events"].append(ev)
            blk["end"] = max(blk["end"], e0)
        else:
            blocks.append({"subject": subj, "start": s0, "end": e0, "events": [ev]})
    for blk in blocks:
        ep = next(
            (
                x
                for x in episodes
                if x.get("origin") == "meeting"
                and ((x.get("stats") or {}).get("meeting_subject") or x.get("_subject")) == blk["subject"]
                and blk["start"] - x["end_epoch"] <= meeting_gap
                and x["start_epoch"] - blk["end"] <= meeting_gap
            ),
            None,
        )
        if ep is None:
            ep = new_episode(blk["events"][0], "meeting", title=f"ประชุม: {blk['subject']}", origin="meeting")
            ep["_subject"] = blk["subject"]
        for ev in blk["events"]:
            assign(ev, ep)
    if blocks and _reclaim_for_meetings(store, cfg, date, episodes, touched):
        work_eps = [e for e in episodes if e.get("origin") != "meeting"]
        current = max(work_eps, key=lambda e: e["end_epoch"]) if work_eps else None
    events = [e for e in events if e.get("activity") != "meeting"]
    if not events:
        _flush(store, cfg, episodes, pending, touched)
        return touched

    raw_labels = [project_label(e, projects) for e in events]
    labels = _smooth_labels(events, raw_labels, label_of(current), min_run)

    # Defer a fresh tail run of a *different* project label until it proves to last min_run.
    current_label = label_of(current)
    if is_today and labels and current_label is not None and labels[-1] not in (None, current_label):
        tail_label = labels[-1]
        i = len(labels) - 1
        while i > 0 and labels[i - 1] == tail_label:
            i -= 1
        tail_start = _span(events[i])[0]
        if now - tail_start < min_run:
            events, labels = events[:i], labels[:i]

    raw_by_id = {e["id"]: r for e, r in zip(events, raw_labels[: len(events)])}
    for ev, label in zip(events, labels):
        own_label = raw_by_id.get(ev["id"])  # the event's own project (not forward-filled)
        s, _ = _span(ev)
        if ev["type"] == "task":
            action = str(ev["data"].get("action", "")).lower()
            if action == "start":
                for ep in episodes:
                    if ep.get("open_task"):
                        ep["open_task"] = 0
                        store.update_episode(ep["id"], open_task=False)
                title = str(ev["data"].get("title") or "").strip() or "Manual task"
                current = new_episode(ev, own_label, title=title, title_locked=True, origin="manual", open_task=True)
                assign(ev, current)
                continue
            if action == "stop":
                if current is not None:
                    assign(ev, current)
                    if current.get("open_task"):
                        current["open_task"] = 0
                        store.update_episode(current["id"], open_task=False)
                else:
                    store.assign_events([ev["id"]], 0)
                continue

        # 0) anything during a meeting belongs to the meeting (multitasking in the call)
        in_meeting = next(
            (ep for ep in episodes if ep.get("origin") == "meeting" and ep["start_epoch"] <= s < ep["end_epoch"]), None
        )
        if in_meeting is not None:
            assign(ev, in_meeting)
            continue
        # 1) an open manual task swallows everything after its start
        if current is not None and current.get("open_task") and s >= current["start_epoch"]:
            assign(ev, current)
            continue
        # 2) event inside an existing episode's span
        host = next(
            (ep for ep in episodes if ep.get("origin") != "meeting" and ep["start_epoch"] <= s < ep["end_epoch"]), None
        )
        if host is not None:
            assign(ev, host)
            continue
        # 3) continue the current auto episode
        if (
            current is not None
            and current.get("origin") not in ("manual", "meeting")
            and s >= current["start_epoch"]
            and s - current["end_epoch"] <= split_gap
            and (label is None or label_of(current) in (None, label))
        ):
            if own_label and not label_of(current):
                current["tags"] = [own_label, *current.get("tags", [])]
                store.update_episode(current["id"], tags=current["tags"])
            assign(ev, current)
            continue
        # 4) a note written shortly after something ended (e.g. a meeting summary) belongs to it
        if ev["type"] == "note":
            recent = [ep for ep in episodes if ep["end_epoch"] <= s and s - ep["end_epoch"] <= note_attach]
            if recent:
                assign(ev, max(recent, key=lambda ep: ep["end_epoch"]), extend=False)
                continue
        # 5) new episode — tagged only with the event's own project, never a label carried over a gap
        current = new_episode(ev, own_label)
        assign(ev, current)

    _flush(store, cfg, episodes, pending, touched)
    return touched


def _reclaim_for_meetings(
    store: Store, cfg: Config, date: str, episodes: list[dict[str, Any]], touched: set[int]
) -> bool:
    """A meeting that grew in this pass (e.g. a background-presence segment flushed every few minutes while
    the user shares the screen) takes back work an earlier refresh put into an auto episode inside its new
    span. User-shaped episodes (manual, merged, renamed, used by a document) are left alone. Returns True
    when work episodes changed."""
    meetings = [ep for ep in episodes if ep.get("origin") == "meeting" and ep["id"] in touched]
    if not meetings:
        return False
    protected = store.episodes_referenced_by_docs()
    movable = {
        ep["id"]
        for ep in episodes
        if ep.get("origin") == "auto" and not ep.get("title_locked") and ep["id"] not in protected
    }
    if not movable:
        return False
    moved: dict[int, list[int]] = {}
    losers: set[int] = set()
    for ev in store.events_for_date(date):
        if ev.get("episode_id") not in movable:
            continue
        s = float(ev["epoch"])
        host = next((m for m in meetings if m["start_epoch"] <= s < m["end_epoch"]), None)
        if host is not None:
            moved.setdefault(host["id"], []).append(ev["id"])
            losers.add(int(ev["episode_id"]))
    for eid, ids in moved.items():
        store.assign_events(ids, eid)
    for eid in losers:
        idx = next(i for i, ep in enumerate(episodes) if ep["id"] == eid)
        if not store.events_for_episode(eid):
            store.delete_episode(eid)
            episodes.pop(idx)
            touched.discard(eid)
            continue
        refresh_episode(store, eid, cfg)
        fresh = store.get_episode(eid)
        if fresh is not None:
            episodes[idx] = fresh
    return bool(losers)


def _flush(
    store: Store, cfg: Config, episodes: list[dict[str, Any]], pending: dict[int, list[int]], touched: set[int]
) -> None:
    for eid, ids in pending.items():
        store.assign_events(ids, eid)
    for eid in touched:
        ep = next((e for e in episodes if e["id"] == eid), None)
        if ep:
            store.update_episode(eid, start_epoch=ep["start_epoch"], end_epoch=ep["end_epoch"])
        refresh_episode(store, eid, cfg)


def rebuild_episodes(store: Store, cfg: Config, date: str) -> set[int]:
    """Drop un-referenced episodes for a date and regroup from scratch."""
    protected = store.episodes_referenced_by_docs()
    for ep in store.episodes_between(date):
        if ep["id"] not in protected:
            store.delete_episode(ep["id"])
    return assign_episodes(store, cfg, date)


def merge_episodes(store: Store, cfg: Config, episode_ids: list[int], title: str = "") -> int:
    eps = [store.get_episode(i) for i in episode_ids]
    eps = [e for e in eps if e]
    if len(eps) < 2:
        raise ValueError("need at least two existing episodes")
    eps.sort(key=lambda e: e["start_epoch"])
    keep = eps[0]
    tags: list[str] = []
    for ep in eps:
        for t in ep["tags"]:
            if t not in tags:
                tags.append(t)
    for ep in eps[1:]:
        ids = [e["id"] for e in store.events_for_episode(ep["id"])]
        store.assign_events(ids, keep["id"])
        store.execute(
            "UPDATE doc_sources SET ref = ? WHERE kind = 'episode' AND ref = ? AND session_id NOT IN "
            "(SELECT session_id FROM doc_sources WHERE kind = 'episode' AND ref = ?)",
            (str(keep["id"]), str(ep["id"]), str(keep["id"])),
        )
        store.execute("DELETE FROM doc_sources WHERE kind = 'episode' AND ref = ?", (str(ep["id"]),))
        store.execute("DELETE FROM episodes WHERE id = ?", (ep["id"],))
    fields: dict[str, Any] = {
        "start_epoch": min(e["start_epoch"] for e in eps),
        "end_epoch": max(e["end_epoch"] for e in eps),
        "tags": tags,
        "origin": "merged" if keep["origin"] != "manual" else "manual",
    }
    if title:
        fields["title"] = title
        fields["title_locked"] = True
    store.update_episode(keep["id"], **fields)
    refresh_episode(store, keep["id"], cfg)
    return int(keep["id"])
