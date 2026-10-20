"""OpsTrail facade used by the MCP server, the CLI and the agent."""

from __future__ import annotations

import re
import time
from difflib import SequenceMatcher
from collections.abc import Iterator
from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path
from typing import Any

from opstrail import __version__
from opstrail.config import Config, load_config
from opstrail.episodes import assign_episodes, merge_episodes, rebuild_episodes, refresh_episode
from opstrail.events import is_focus_window, make_event
from opstrail.export import export_markdown, markdown_to_docx, shot_resolver, slugify
from opstrail.ingest import ingest_inbox, store_event
from opstrail.locks import file_lock
from opstrail.recap import build_recap
from opstrail.render import compact_event, episode_header, episode_pack, fmt_duration, hhmm, window_summary
from opstrail.store import DOC_STATUSES, Store
from opstrail.templates import Template, load_templates

RECAP_TEMPLATE = "daily-worklog"
MAX_RANGE_DAYS = 31


class OpsTrailError(ValueError):
    """User-facing error (bad id, unknown template, …)."""


def _validate_date(value: str | None, cfg: Config) -> str:
    if not value or value.strip().lower() in ("today", ""):
        return cfg.today()
    text = value.strip().lower()
    if text == "yesterday":
        return (date_cls.fromisoformat(cfg.today()) - timedelta(days=1)).isoformat()
    try:
        return date_cls.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise OpsTrailError(f"invalid date {value!r}, use YYYY-MM-DD, 'today' or 'yesterday'") from exc


def _date_range(start: str, end: str) -> list[str]:
    d0, d1 = date_cls.fromisoformat(start), date_cls.fromisoformat(end)
    if d1 < d0:
        d0, d1 = d1, d0
    days = (d1 - d0).days
    if days > MAX_RANGE_DAYS:
        raise OpsTrailError(f"date range too large (max {MAX_RANGE_DAYS} days)")
    return [(d0 + timedelta(days=i)).isoformat() for i in range(days + 1)]


class OpsTrail:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or load_config()
        self.store = Store(self.cfg.db_path)

    # ------------------------------------------------------------------ core
    def refresh(self) -> dict[str, int]:
        """Ingest the inbox and group new events into episodes.

        Guarded by a cross-process lock: the agent and every MCP server process call this, and two
        concurrent groupings of the same events would create duplicate episodes.
        """
        with file_lock(self.cfg.home / "refresh.lock") as locked:
            if not locked:  # another process is refreshing right now – its result is good enough
                return {"ingested": 0, "episodes_touched": 0}
            n = ingest_inbox(self.cfg, self.store)
            self._backfill_activity()
            touched = assign_episodes(self.store, self.cfg)
            return {"ingested": n, "episodes_touched": len(touched)}

    def _backfill_activity(self) -> None:
        """Classify events stored before the activity classifier existed (one-time, batched)."""
        from opstrail.activity import classifier_for

        clf = classifier_for(self.cfg.home)
        for _ in range(50):
            rows = self.store.unclassified(2000)
            if not rows:
                return
            items = []
            for r in rows:
                act, subj = clf.classify(r["type"], r.get("data") or {})
                items.append((act, subj, r["id"]))
            self.store.set_activity(items)

    def templates(self) -> dict[str, Template]:
        return load_templates(self.cfg.templates_dir)

    def template(self, name: str) -> Template:
        templates = self.templates()
        if name not in templates:
            raise OpsTrailError(f"unknown template {name!r}; available: {', '.join(templates) or 'none'}")
        return templates[name]

    def record(self, type_: str, data: dict[str, Any], source: str = "cli", **kw: Any) -> int | None:
        return store_event(self.cfg, self.store, make_event(self.cfg, type_, data, source=source, **kw))

    def record_browser(self, payload: dict[str, Any]) -> dict[str, Any]:
        from opstrail.browser import capture_data
        from opstrail.events import parse_ts

        try:
            ts = parse_ts(payload.get("ts"), self.cfg.tz)
            data = capture_data(self.cfg, payload)
        except (ValueError, TypeError, OverflowError, OSError) as exc:
            raise OpsTrailError("ข้อมูล browser ไม่ถูกต้อง (URL, title, tab_id, ts หรือ incognito)") from exc
        eid = self.record("browser", data, source="browser-extension", ts=ts) if data else None
        return {"stored": eid is not None, "event_id": eid}

    # ---------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        today = self.cfg.today()
        heartbeat = float(self.store.kv_get("agent:heartbeat", "0") or 0)
        return {
            "version": __version__,
            "today": today,
            "capturing": not self.cfg.is_paused(),
            "agent_running": time.time() - heartbeat < 60,
            "agent_last_seen_s": round(time.time() - heartbeat) if heartbeat else None,
            "events_today": self.store.count_events(today),
            "episodes_today": len(self.store.episodes_between(today)),
            "doc_sessions": len(self.store.list_sessions(limit=1000)),
            "templates": sorted(self.templates()),
            "paths": {
                "home": str(self.cfg.home),
                "db": str(self.cfg.db_path),
                "exports": str(self.cfg.export_dir),
                "templates": str(self.cfg.templates_dir),
            },
        }

    # -------------------------------------------------------------- activity
    def timeline(self, date: str | None = None, types: str | list[str] = "", limit: int = 300) -> dict[str, Any]:
        d = _validate_date(date, self.cfg)
        type_list = [t.strip() for t in types.split(",")] if isinstance(types, str) else list(types or [])
        events = self.store.events_for_date(d, types=[t for t in type_list if t])
        total = len(events)
        if limit and total > limit:
            events = events[-limit:]
        return {
            "date": d,
            "total_events": total,
            "shown": len(events),
            "events": [compact_event(e, self.cfg.tz) for e in events],
        }

    def search_activity(
        self, query: str, date_from: str | None = None, date_to: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        if not query.strip():
            raise OpsTrailError("query is required")
        df = _validate_date(date_from, self.cfg) if date_from else None
        dt = _validate_date(date_to, self.cfg) if date_to else None
        rows = self.store.search_events(query.strip(), df, dt, limit)
        return [dict(compact_event(e, self.cfg.tz), date=e["local_date"]) for e in rows]

    # -------------------------------------------------------------- episodes
    def _episode_summary(self, ep: dict[str, Any]) -> dict[str, Any]:
        st = ep.get("stats") or {}
        return {
            "id": ep["id"],
            "date": ep["local_date"],
            "time": f"{hhmm(ep['start_epoch'], self.cfg.tz)}–{hhmm(ep['end_epoch'], self.cfg.tz)}",
            "active": fmt_duration(st.get("active_s")),
            "title": ep["title"],
            "title_locked": bool(ep["title_locked"]),
            "origin": ep["origin"],
            "tags": ep["tags"],
            "apps": st.get("top_apps", []),
            "targets": st.get("targets", []),
            "keywords": st.get("keywords", []),
            "commands": st.get("commands", 0),
            "failed_commands": st.get("failed_commands", 0),
            "notes": st.get("notes", 0),
            "screenshots": st.get("screenshots", 0),
            "open_task": bool(ep.get("open_task")),
            "activities": st.get("activities", {}),
            "chats": st.get("chats", []),
            "consoles": st.get("consoles", []),
        }

    def list_episodes(self, date: str | None = None, date_to: str | None = None) -> list[dict[str, Any]]:
        d0 = _validate_date(date, self.cfg)
        d1 = _validate_date(date_to, self.cfg) if date_to else d0
        _date_range(d0, d1)
        return [self._episode_summary(ep) for ep in self.store.episodes_between(min(d0, d1), max(d0, d1))]

    def _require_episode(self, episode_id: int) -> dict[str, Any]:
        ep = self.store.get_episode(int(episode_id))
        if not ep:
            raise OpsTrailError(f"episode {episode_id} not found")
        return ep

    def get_episode(self, episode_id: int, max_events: int = 150) -> dict[str, Any]:
        ep = self._require_episode(episode_id)
        events = self.store.events_for_episode(ep["id"])
        shown = [e for e in events if e["type"] != "window"]
        if max_events and len(shown) > max_events:
            shown = shown[:max_events]
        return {
            **self._episode_summary(ep),
            "windows": [{"focus": fmt_duration(s), "window": w} for w, s in window_summary(events, top=15)],
            "events": [compact_event(e, self.cfg.tz) for e in shown],
            "total_events": len(events),
        }

    def update_episode(self, episode_id: int, title: str = "", tags: str | list[str] = "", note: str = "") -> dict:
        ep = self._require_episode(episode_id)
        fields: dict[str, Any] = {}
        if title.strip():
            fields["title"] = title.strip()
            fields["title_locked"] = True
        if tags:
            tag_list = [t.strip() for t in tags.split(",")] if isinstance(tags, str) else list(tags)
            fields["tags"] = [t for t in tag_list if t]
        if fields:
            self.store.update_episode(ep["id"], **fields)
        if note.strip():
            self.add_note(note.strip(), ep["id"], source="mcp")
        return self._episode_summary(self._require_episode(ep["id"]))

    def merge_episodes(self, episode_ids: list[int], title: str = "") -> dict[str, Any]:
        try:
            eid = merge_episodes(self.store, self.cfg, [int(i) for i in episode_ids], title)
        except ValueError as exc:
            raise OpsTrailError(str(exc)) from exc
        return self._episode_summary(self._require_episode(eid))

    def rebuild_episodes(self, date: str | None = None) -> list[dict[str, Any]]:
        d = _validate_date(date, self.cfg)
        rebuild_episodes(self.store, self.cfg, d)
        return self.list_episodes(d)

    def record_voice(self, episode_id: int | None = None, **kwargs: Any) -> dict[str, Any] | None:
        from opstrail.voice import capture_note

        return capture_note(self, episode_id, **kwargs)

    def add_note(self, text: str, episode_id: int | None = None, source: str = "cli") -> dict[str, Any]:
        if not text.strip():
            raise OpsTrailError("note text is required")
        ep = self._require_episode(episode_id) if episode_id else None
        data: dict[str, Any] = {"text": text.strip()}
        if ep:
            data["episode_id"] = ep["id"]
        event_id = self.record("note", data, source=source)
        if ep and event_id:
            self.store.assign_events([event_id], ep["id"])
            refresh_episode(self.store, ep["id"], self.cfg)
        elif event_id:
            self.refresh()
        ev = self.store.get_event(event_id) if event_id else None
        return {"event_id": event_id, "episode_id": ev.get("episode_id") if ev else None}

    # ------------------------------------------------------------- documents
    def list_templates(self) -> list[dict[str, Any]]:
        return [t.summary() for t in self.templates().values()]

    def _require_session(self, session_id: int) -> dict[str, Any]:
        s = self.store.get_session(int(session_id))
        if not s:
            raise OpsTrailError(f"doc session {session_id} not found")
        return s

    def _add_sources(
        self, session_id: int, episode_ids: list[int] | None, date: str | None, date_to: str | None
    ) -> list[str]:
        added: list[str] = []
        for eid in episode_ids or []:
            ep = self._require_episode(eid)
            if self.store.add_source(session_id, "episode", str(ep["id"])):
                added.append(f"episode #{ep['id']}")
        if date:
            d0 = _validate_date(date, self.cfg)
            d1 = _validate_date(date_to, self.cfg) if date_to else d0
            for d in _date_range(d0, d1):
                if self.store.add_source(session_id, "date", d):
                    added.append(f"date {d}")
        return added

    def _source_episodes(self, session_id: int) -> list[dict[str, Any]]:
        seen: dict[int, dict[str, Any]] = {}
        for src in self.store.sources(session_id):
            if src["kind"] == "episode":
                ep = self.store.get_episode(int(src["ref"]))
                if ep:
                    seen[ep["id"]] = ep
            elif src["kind"] == "date":
                for ep in self.store.episodes_between(src["ref"]):
                    seen[ep["id"]] = ep
        return sorted(seen.values(), key=lambda e: e["start_epoch"])

    def _sources_markdown(self, session_id: int, only: list[int] | None = None) -> str:
        eps = self._source_episodes(session_id)
        if only is not None:
            eps = [e for e in eps if e["id"] in only]
        if not eps:
            return "_No episodes in the sources yet. Use add_doc_sources(session_id, episode_ids=[…] or date=…)._"
        return "\n\n".join(episode_pack(ep, self.store.events_for_episode(ep["id"]), self.cfg.tz) for ep in eps)

    def _writing_rules(self, session_id: int, mode: str = "mcp") -> str:
        lang = (
            "Write in Thai, keep technical terms, product names, commands and UI labels in English."
            if self.cfg.doc_language.startswith("th")
            else "Write in English."
        )
        return "\n".join(
            [
                "## Writing rules",
                f"1. {lang}",
                "2. Use ONLY facts from the sources and the user's messages. Anything unknown → `[TODO: …]`. Never invent IPs, versions, hostnames or results.",
                "3. Follow the skeleton's section order and headings. Fill every section; write `N/A` if a section truly does not apply.",
                "4. Commands go into fenced code blocks (```powershell / ```bash) and must be copy-paste ready. Drop typos, failed attempts and dead ends unless they matter for troubleshooting.",
                "5. Keep `[REDACTED]` exactly as is. Never put secrets into the document — reference where they are stored instead.",
                "6. Screenshots: embed with `![caption](shot://ID)` using only IDs listed in the sources.",
                "7. The user's notes explain intent and decisions — reflect them.",
                (
                    f"8. When the draft is ready call `save_draft(session_id={session_id}, markdown=…, change_note=…)`. "
                    f"To continue later call `get_doc_session({session_id})`."
                )
                if mode == "mcp"
                else "8. Reply with the complete document in Markdown only — no preface, no closing remarks.",
            ]
        )

    def _template_block(self, tpl: Template) -> str:
        from opstrail import quality

        parts = [f"## Template: {tpl.title} (`{tpl.name}`)", tpl.description, ""]
        if tpl.guide.strip():
            parts += ["### Section guide", tpl.guide.strip(), ""]
        style = quality.read_style(self.cfg, tpl.name)
        if style:
            parts += ["### Style lessons learned from this user's past edits (follow them)", style, ""]
        recent = self.store.feedback_for(tpl.name, 2)
        if recent:
            parts += ["### Recent corrections by the user ('-' = AI draft, '+' = what the user kept)"]
            for fb in recent:
                parts += ["```diff", fb["diff"][:1200], "```"]
            parts.append("")
        parts += ["### Skeleton", "````markdown", tpl.skeleton.strip(), "````", ""]
        for name, text in tpl.examples_text():
            parts += [f"### Example of a good document: {name}", "````markdown", text, "````", ""]
        return "\n".join(parts)

    def start_doc_session(
        self,
        template: str,
        title: str,
        episode_ids: list[int] | None = None,
        date: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        tpl = self.template(template)
        if not title.strip():
            raise OpsTrailError("title is required")
        if not episode_ids and not date:
            raise OpsTrailError("give episode_ids and/or date (use list_episodes to find them)")
        for eid in episode_ids or []:
            self._require_episode(eid)
        session_id = self.store.create_session(tpl.name, title.strip(), {"author": self.cfg.author})
        added = self._add_sources(session_id, episode_ids, date, date_to)
        return {
            "session_id": session_id,
            "template": tpl.name,
            "title": title.strip(),
            "sources_added": added,
            "source_pack": self.source_pack(session_id),
        }

    def source_pack(self, session_id: int, only_episodes: list[int] | None = None, mode: str = "mcp") -> str:
        s = self._require_session(session_id)
        tpl = self.template(s["template"])
        header = [
            f"# OpsTrail source pack — doc session #{session_id}",
            f"- Document title: {s['title']}",
            f"- Template: {tpl.title} (`{tpl.name}`)",
            f"- Author: {s['meta'].get('author') or self.cfg.author}",
            f"- Date: {self.cfg.today()}",
            f"- Status: {s['status']}",
            "",
            self._writing_rules(session_id, mode),
            "",
            self._template_block(tpl),
            "## Sources (facts captured by OpsTrail)",
            "",
            self._sources_markdown(session_id, only_episodes),
        ]
        return "\n".join(header)

    def list_doc_sessions(self, status: str = "", template: str = "", limit: int = 30) -> list[dict[str, Any]]:
        return [
            {
                "session_id": s["id"],
                "title": s["title"],
                "template": s["template"],
                "status": s["status"],
                "latest_version": s.get("latest_version") or 0,
                "updated_at": s["updated_at"],
            }
            for s in self.store.list_sessions(status, template, limit)
        ]

    def get_doc_session(self, session_id: int, include_sources: bool = True) -> dict[str, Any]:
        s = self._require_session(session_id)
        latest = self.store.get_version(s["id"])
        out: dict[str, Any] = {
            "session_id": s["id"],
            "title": s["title"],
            "template": s["template"],
            "status": s["status"],
            "sources": self.store.sources(s["id"]),
            "versions": self.store.versions(s["id"]),
            "latest_markdown": latest["markdown"] if latest else None,
        }
        if include_sources:
            out["source_pack"] = self.source_pack(s["id"])
        return out

    def add_doc_sources(
        self,
        session_id: int,
        episode_ids: list[int] | None = None,
        date: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        s = self._require_session(session_id)
        before = {e["id"] for e in self._source_episodes(s["id"])}
        added = self._add_sources(s["id"], episode_ids, date, date_to)
        new_ids = [e["id"] for e in self._source_episodes(s["id"]) if e["id"] not in before]
        return {
            "session_id": s["id"],
            "sources_added": added,
            "new_material": self._sources_markdown(s["id"], only=new_ids) if new_ids else "_nothing new_",
        }

    def save_draft(self, session_id: int, markdown: str, change_note: str = "", author: str = "ai") -> dict:
        from opstrail import quality

        s = self._require_session(session_id)
        if not markdown.strip():
            raise OpsTrailError("markdown is empty")
        previous = self.store.get_version(s["id"])
        version = self.store.add_version(s["id"], markdown, change_note.strip(), author)
        # learn from the user's corrections of an AI draft
        if (
            previous
            and not quality.is_ai_author(author)
            and quality.is_ai_author(previous["author"])
            and previous["markdown"].strip() != markdown.strip()
        ):
            diff = quality.make_diff(previous["markdown"], markdown)
            if diff.strip():
                self.store.add_feedback(s["id"], s["template"], previous["version"], version, diff)
        return {"session_id": s["id"], "version": version, "chars": len(markdown)}

    def set_doc_status(self, session_id: int, status: str) -> dict[str, Any]:
        s = self._require_session(session_id)
        status = status.strip().lower()
        if status not in DOC_STATUSES:
            raise OpsTrailError(f"status must be one of {', '.join(DOC_STATUSES)}")
        self.store.update_session(s["id"], status=status)
        return {"session_id": s["id"], "status": status}

    def rename_doc_session(self, session_id: int, title: str) -> dict[str, Any]:
        s = self._require_session(session_id)
        self.store.update_session(s["id"], title=title.strip())
        return {"session_id": s["id"], "title": title.strip()}

    def export_doc(self, session_id: int, format: str = "docx", version: int | None = None) -> dict[str, Any]:
        s = self._require_session(session_id)
        v = self.store.get_version(s["id"], version)
        if not v:
            raise OpsTrailError("no draft saved yet — call save_draft first")
        fmt = format.strip().lower()
        if fmt not in ("md", "docx", "both"):
            raise OpsTrailError("format must be md, docx or both")
        stamp = s["created_at"][:10]
        base = f"{stamp}_{slugify(s['title'])}_v{v['version']}"
        folder = self.cfg.export_dir / s["template"]
        resolve = shot_resolver(self.store)
        files: list[str] = []
        if fmt in ("md", "both"):
            files.append(str(export_markdown(v["markdown"], folder / f"{base}.md", resolve)))
        if fmt in ("docx", "both"):
            tpl = self.templates().get(s["template"])
            exp = self.cfg.export
            files.append(
                str(
                    markdown_to_docx(
                        v["markdown"],
                        folder / f"{base}.docx",
                        resolve,
                        reference=tpl.reference_docx if tpl else None,
                        font=exp.get("docx_font") or None,
                        font_size=float(exp.get("docx_font_size") or 0) or None,
                        image_width_in=float(exp.get("image_width_in") or 6.0),
                    )
                )
            )
        return {"session_id": s["id"], "version": v["version"], "files": files}

    # ------------------------------------------------------------ daily recap
    def recap_settings(self) -> dict[str, bool]:
        from opstrail import teams

        return teams.public_settings(self.cfg)

    def save_recap_settings(self, teams_webhook_url: str | None = None, clear: bool = False) -> dict[str, bool]:
        from opstrail import teams

        try:
            if teams_webhook_url is not None and not isinstance(teams_webhook_url, str):
                raise ValueError("Webhook URL ต้องเป็นข้อความ")
            return teams.save_settings(self.cfg, teams_webhook_url, clear)
        except ValueError:
            raise OpsTrailError("Webhook URL ไม่ถูกต้อง: ใช้ HTTPS หรือ HTTP loopback สำหรับทดสอบ") from None
        except Exception:
            raise OpsTrailError("บันทึก Teams Webhook ไม่สำเร็จ กรุณาตรวจสิทธิ์ไฟล์และ Windows DPAPI") from None

    def send_teams_digest(self, date: str):
        """Called only by the automatic recap gate, with no DB use in the worker."""
        import logging
        import threading
        from opstrail import teams

        try:
            url = teams.webhook_url(self.cfg)
            if not url:
                return None
            day = _validate_date(date, self.cfg)
            episodes = self.store.episodes_between(day)
            # Explicit titles can also repeat captured commands/window titles.
            # Compare the entire day, including normalized whitespace, before projection.
            captured = []
            for ev in self.store.events_for_date(day):
                data = ev.get("data") or {}
                values = [data.get("cmd")] if ev["type"] in ("shell", "ai") else []
                if ev["type"] in ("window", "screenshot"):
                    values.extend([data.get("title"), ev.get("subject")])
                captured.extend(" ".join(str(v).split()).casefold() for v in values if v and str(v).strip())
            for ep in episodes:
                if ep.get("title_locked"):
                    title = " ".join(str(ep["title"]).split()).casefold()
                    if any(value in title for value in captured):
                        ep["title_locked"] = False
            payload = teams.build_card(self.cfg, day, episodes)
            worker = threading.Thread(target=teams.deliver, args=(url, payload), name="opstrail-teams", daemon=True)
            worker.start()
            return worker
        except Exception:
            logging.getLogger("opstrail.teams").warning("Teams: เตรียม digest ไม่สำเร็จ")
            return None

    def recap_session_id(self, date: str) -> int | None:
        value = self.store.kv_get(f"recap:{date}")
        if value and value.isdigit() and self.store.get_session(int(value)):
            return int(value)
        return None

    def daily_recap(self, date: str | None = None, save: bool = True) -> dict[str, Any]:
        d = _validate_date(date, self.cfg)
        self.refresh()
        markdown = build_recap(self.store, self.cfg, d)
        out: dict[str, Any] = {"date": d, "markdown": markdown}
        if save:
            sid = self.recap_session_id(d)
            if sid is None:
                if RECAP_TEMPLATE not in self.templates():
                    raise OpsTrailError(f"template {RECAP_TEMPLATE!r} is missing")
                sid = self.store.create_session(
                    RECAP_TEMPLATE, f"Daily Worklog {d}", {"author": self.cfg.author, "date": d}
                )
                self.store.add_source(sid, "date", d)
                self.store.kv_set(f"recap:{d}", str(sid))
            version = self.store.add_version(sid, markdown, "auto recap", "opstrail-auto")
            out.update({"session_id": sid, "version": version})
        return out

    def search_docs(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        return self.store.search_docs(query, limit)

    def purge(self, date: str | None = None, before: str | None = None) -> int:
        if date:
            return self.store.purge_events(date=_validate_date(date, self.cfg))
        if before:
            return self.store.purge_events(before=_validate_date(before, self.cfg))
        raise OpsTrailError("date or before is required")

    def episode_header(self, ep: dict[str, Any]) -> str:
        return episode_header(ep, self.cfg.tz)


    # ------------------------------------------------------------ web helpers
    def set_paused(self, paused: bool) -> dict[str, Any]:
        self.cfg.set_paused(paused)
        return {"capturing": not paused}

    def day(self, date: str | None = None) -> dict[str, Any]:
        """Everything the web 'day' page needs in one call."""
        d = _validate_date(date, self.cfg)
        episodes = self.list_episodes(d)
        events = self.store.events_for_date(d)
        active = sum(float(e.get("duration_s") or 0) for e in events if is_focus_window(e))
        if not active:
            active = sum((ep.get("stats") or {}).get("active_s", 0) for ep in self.store.episodes_between(d))
        counts = self.store.count_events(d)
        sid = self.recap_session_id(d)
        recap = None
        if sid:
            v = self.store.get_version(sid)
            recap = {"session_id": sid, "version": v["version"] if v else 0}
        return {
            "date": d,
            "summary": {
                "active": fmt_duration(active),
                "work_items": len(episodes),
                "commands": counts.get("shell", 0) + counts.get("ai", 0),
                "notes": counts.get("note", 0),
                "screenshots": counts.get("screenshot", 0),
            },
            "episodes": episodes,
            "recap": recap,
        }

    def list_recaps(self, limit: int = 60) -> list[dict[str, Any]]:
        out = []
        for s in self.store.list_sessions("", RECAP_TEMPLATE, limit):
            out.append(
                {
                    "session_id": s["id"],
                    "date": s["meta"].get("date") or s["title"].replace("Daily Worklog ", ""),
                    "status": s["status"],
                    "latest_version": s.get("latest_version") or 0,
                    "updated_at": s["updated_at"],
                }
            )
        return sorted(out, key=lambda r: r["date"], reverse=True)

    def doc_detail(self, session_id: int, version: int | None = None) -> dict[str, Any]:
        s = self._require_session(session_id)
        v = self.store.get_version(s["id"], version)
        return {
            "session_id": s["id"],
            "title": s["title"],
            "template": s["template"],
            "status": s["status"],
            "created_at": s["created_at"],
            "updated_at": s["updated_at"],
            "versions": self.store.versions(s["id"]),
            "version": v["version"] if v else 0,
            "markdown": v["markdown"] if v else "",
            "author": v["author"] if v else "",
            "sources": self.store.sources(s["id"]),
            "episodes": [self._episode_summary(ep) for ep in self._source_episodes(s["id"])],
        }

    def doc_diff(self, session_id: int, from_version: int, to_version: int) -> dict[str, Any]:
        """Lossless word/Thai-cluster diff of two explicitly selected saved versions."""
        s = self._require_session(session_id)
        versions = []
        for number in (from_version, to_version):
            if number < 1:
                raise OpsTrailError("ต้องเลือกเวอร์ชันที่บันทึกแล้วทั้งสองเวอร์ชัน")
            v = self.store.get_version(s["id"], number)
            if not v:
                raise OpsTrailError(f"ไม่พบเวอร์ชัน {number} ของเอกสารนี้")
            versions.append(v["markdown"])
        # Thai has no spaces between words. Keep combining marks with their base;
        # the browser expands changed clusters to dictionary words with Intl.Segmenter.
        pattern = r"[\u0e00-\u0e7f][\u0e31\u0e34-\u0e3a\u0e47-\u0e4e]*|[^\W\u0e00-\u0e7f]+|\s+|."
        before, after = [re.findall(pattern, text) for text in versions]
        hunks = [{"op": op, "before": "".join(before[i:j]), "after": "".join(after[k:l])}
                 for op, i, j, k, l in SequenceMatcher(None, before, after, autojunk=False).get_opcodes()]
        return {"hunks": hunks}

    def update_doc_meta(self, session_id: int, title: str = "", status: str = "") -> dict[str, Any]:
        s = self._require_session(session_id)
        if title.strip():
            self.rename_doc_session(s["id"], title)
        if status.strip():
            self.set_doc_status(s["id"], status)
        return self.doc_detail(s["id"])

    def llm_prompt(self, session_id: int, instruction: str = "") -> tuple[str, str]:
        """(system, user) prompt for writing/revising a document with any LLM."""
        s = self._require_session(session_id)
        system = (
            "You are a senior technical writer at a Thai MSSP (cybersecurity and cloud systems integrator). "
            "You turn captured work activity into precise, professional documentation that engineers can follow "
            "and customers can sign off. Output ONLY the final document in GitHub-flavoured Markdown."
        )
        parts = [self.source_pack(s["id"], mode="api")]
        latest = self.store.get_version(s["id"])
        if latest and latest["markdown"].strip():
            parts += [
                "",
                "## Current draft — revise and improve it; keep the user's manual edits unless the sources contradict them",
                "````markdown",
                latest["markdown"].strip(),
                "````",
            ]
        if instruction.strip():
            parts += ["", "## Extra instruction from the user", instruction.strip()]
        parts += ["", "Return the complete document as Markdown only."]
        return system, "\n".join(parts)

    def copy_prompt(self, session_id: int, instruction: str = "") -> str:
        system, user = self.llm_prompt(session_id, instruction)
        return f"{system}\n\n{user}"

    def generate_draft(self, session_id: int, instruction: str = "") -> dict[str, Any]:
        from opstrail import llm

        s = self._require_session(session_id)
        system, user = self.llm_prompt(s["id"], instruction)
        result = llm.complete(self.cfg, system, user)
        return self._save_generated(s["id"], instruction, result)

    def stream_draft(self, session_id: int, instruction: str = "") -> Iterator[dict[str, Any]]:
        from opstrail import llm

        self._require_session(session_id)
        system, user = self.llm_prompt(session_id, instruction)

        def events():
            chunks = llm.stream_complete(self.cfg, system, user)
            try:
                for chunk in chunks:
                    if isinstance(chunk, llm.LLMResult):
                        yield {"event": "done", **self._save_generated(session_id, instruction, chunk)}
                    else:
                        yield {"event": "delta", "text": chunk}
            finally:
                chunks.close()

        return events()

    def _save_generated(self, session_id: int, instruction: str, result: Any) -> dict[str, Any]:
        from opstrail import llm

        s = self._require_session(session_id)
        markdown = llm.strip_fences(result.text)
        if not markdown.strip():
            raise OpsTrailError("AI ส่งเอกสารว่าง — ยังไม่ได้บันทึกเวอร์ชันใหม่")
        note = "AI draft" + (f": {instruction.strip()[:80]}" if instruction.strip() else "")
        if result.truncated:
            note += " (truncated – increase max_tokens)"
        version = self.store.add_version(s["id"], markdown, note, result.label)
        return {
            "session_id": s["id"],
            "version": version,
            "markdown": markdown,
            "model": result.label,
            "truncated": result.truncated,
            "fact_check": self.fact_check(s["id"], version),
        }

    # --------------------------------------------------------- quality loop
    def profile(self) -> dict[str, Any]:
        p = self.cfg.profile
        return {"author": p.get("author") or "", "effective_author": self.cfg.author, "team": p.get("team") or "",
                "windows_user": self.cfg.user}

    def save_profile(self, author: str = "", team: str = "") -> dict[str, Any]:
        self.cfg.save_profile(author=author, team=team)
        return self.profile()

    def fact_check(self, session_id: int, version: int | None = None) -> dict[str, Any]:
        from opstrail import quality

        s = self._require_session(session_id)
        v = self.store.get_version(s["id"], version)
        if not v:
            raise OpsTrailError("no draft saved yet")
        tpl = self.templates().get(s["template"])
        res = quality.fact_check(v["markdown"], self._sources_markdown(s["id"]), tpl.skeleton if tpl else "")
        res["version"] = v["version"]
        return res

    def style(self, template: str) -> dict[str, Any]:
        from opstrail import quality

        self.template(template)
        return {"template": template, "style": quality.read_style(self.cfg, template),
                "edits": len(self.store.feedback_for(template, 1000))}

    def save_style(self, template: str, text: str) -> dict[str, Any]:
        from opstrail import quality

        self.template(template)
        quality.write_style(self.cfg, template, text)
        return self.style(template)

    def learn_style(self, template: str) -> dict[str, Any]:
        """Ask the configured LLM to turn the user's recent edits into durable style rules."""
        from opstrail import llm, quality

        self.template(template)
        diffs = [fb["diff"] for fb in self.store.feedback_for(template, 10)]
        if not diffs:
            raise OpsTrailError("ยังไม่มีการแก้ไข draft ของ AI สำหรับเอกสารประเภทนี้ — แก้ draft แล้วกดบันทึกก่อน")
        result = llm.complete(self.cfg, quality.LEARN_SYSTEM, quality.learn_prompt(quality.read_style(self.cfg, template), diffs))
        text = llm.strip_fences(result.text).strip()
        if not text:
            raise OpsTrailError("AI returned an empty style guide")
        quality.write_style(self.cfg, template, text)
        return self.style(template)

    def ai_title_episodes(self, date: str | None = None) -> dict[str, Any]:
        """One LLM call: human-friendly Thai titles for the day's auto-named episodes."""
        import json as _json

        from opstrail import llm
        from opstrail.render import command_lines

        d = _validate_date(date, self.cfg)
        self.refresh()
        eps = [e for e in self.store.episodes_between(d) if not e["title_locked"]]
        if not eps:
            return {"date": d, "renamed": 0, "titles": []}
        lines = []
        for ep in eps:
            st = ep.get("stats") or {}
            events = self.store.events_for_episode(ep["id"])
            wins = [w for w, _ in window_summary(events, top=4)]
            notes = [e.get("text") for e in events if e["type"] == "note"][:3]
            cmds = command_lines(events, self.cfg.tz, limit=8)
            lines.append(_json.dumps({
                "id": ep["id"], "time": f"{hhmm(ep['start_epoch'], self.cfg.tz)}-{hhmm(ep['end_epoch'], self.cfg.tz)}",
                "auto_title": ep["title"], "activities": st.get("activities"), "consoles": st.get("consoles"),
                "chats": st.get("chats"), "targets": st.get("targets"), "windows": wins, "commands": cmds,
                "notes": notes,
            }, ensure_ascii=False))
        system = (
            "You name work items for an engineer's daily log. For each item give a short, specific Thai title "
            "(max 60 characters, keep product/host names in English) describing WHAT was done, e.g. "
            "\"ติดตั้ง Splunk UF บน splunk-uf01\" or \"ประชุมสัมภาษณ์นักศึกษาฝึกงาน\". Use only the given facts. "
            "Reply with a JSON array only: [{\"id\": <id>, \"title\": \"...\"}]"
        )
        result = llm.complete(self.cfg, system, "\n".join(lines))
        text = llm.strip_fences(result.text).strip()
        m = re.search(r"\[.*\]", text, re.S)
        try:
            items = _json.loads(m.group(0) if m else text)
        except ValueError as exc:
            raise OpsTrailError(f"AI returned invalid JSON: {text[:200]}") from exc
        valid = {e["id"] for e in eps}
        renamed = []
        for it in items if isinstance(items, list) else []:
            try:
                eid, title = int(it.get("id")), str(it.get("title") or "").strip()
            except (TypeError, ValueError, AttributeError):
                continue
            if eid in valid and title:
                self.store.update_episode(eid, title=title[:120], title_locked=True)
                renamed.append({"id": eid, "title": title[:120]})
        return {"date": d, "renamed": len(renamed), "titles": renamed, "model": result.label}

    def shot_file(self, event_id: int) -> Path:
        """Path of a screenshot – only files inside ~/.opstrail/shots are ever served."""
        ev = self.store.get_event(int(event_id))
        if not ev or ev["type"] != "screenshot":
            raise OpsTrailError("screenshot not found")
        path = Path(str(ev["data"].get("path", ""))).expanduser()
        try:
            resolved = path.resolve()
            root = self.cfg.shots_dir.resolve()
        except OSError as exc:
            raise OpsTrailError("screenshot not found") from exc
        if root not in resolved.parents or resolved.suffix.lower() not in (".png", ".jpg", ".jpeg") or not resolved.is_file():
            raise OpsTrailError("screenshot not available")
        return resolved

    def search_all(self, query: str, limit: int = 30) -> dict[str, Any]:
        q = query.strip()
        if not q:
            return {"docs": [], "activity": []}
        return {"docs": self.search_docs(q, 15), "activity": self.search_activity(q, limit=limit)}


def default_shot_path(cfg: Config) -> Path:
    from datetime import datetime

    now = datetime.now(cfg.tz)
    folder = cfg.shots_dir / now.date().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{now.strftime('%H%M%S')}.png"
