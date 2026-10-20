"""SQLite persistence for events, episodes and document sessions."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,
    epoch       REAL NOT NULL,
    local_date  TEXT NOT NULL,
    type        TEXT NOT NULL,
    source      TEXT,
    host        TEXT,
    user        TEXT,
    duration_s  REAL,
    data        TEXT NOT NULL,
    text        TEXT,
    episode_id  INTEGER,
    hash        TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(local_date, epoch);
CREATE INDEX IF NOT EXISTS idx_events_episode ON events(episode_id);

CREATE TABLE IF NOT EXISTS episodes (
    id            INTEGER PRIMARY KEY,
    local_date    TEXT NOT NULL,
    start_epoch   REAL NOT NULL,
    end_epoch     REAL NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    title_locked  INTEGER NOT NULL DEFAULT 0,
    tags          TEXT NOT NULL DEFAULT '[]',
    origin        TEXT NOT NULL DEFAULT 'auto',
    open_task     INTEGER NOT NULL DEFAULT 0,
    stats         TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_episodes_date ON episodes(local_date, start_epoch);

CREATE TABLE IF NOT EXISTS doc_sessions (
    id          INTEGER PRIMARY KEY,
    template    TEXT NOT NULL,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'draft',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    meta        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS doc_sources (
    session_id  INTEGER NOT NULL,
    kind        TEXT NOT NULL,          -- 'episode' | 'date'
    ref         TEXT NOT NULL,
    added_at    TEXT NOT NULL,
    PRIMARY KEY (session_id, kind, ref)
);

CREATE TABLE IF NOT EXISTS doc_versions (
    id           INTEGER PRIMARY KEY,
    session_id   INTEGER NOT NULL,
    version      INTEGER NOT NULL,
    markdown     TEXT NOT NULL,
    change_note  TEXT NOT NULL DEFAULT '',
    author       TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    UNIQUE (session_id, version)
);

CREATE TABLE IF NOT EXISTS kv (
    key    TEXT PRIMARY KEY,
    value  TEXT
);
"""

DOC_STATUSES = ("draft", "review", "final", "archived")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    """Thread-safe (single connection + lock) SQLite wrapper."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), timeout=10, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout = 10000")
        try:
            self.conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError:  # pragma: no cover - e.g. network drives
            pass
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.fts_mode = self._init_fts()
        self.conn.commit()

    # ------------------------------------------------------------------ infra
    def _migrate(self) -> None:
        """Additive schema migrations (never destructive)."""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(events)")}
        if "activity" not in cols:
            self.conn.execute("ALTER TABLE events ADD COLUMN activity TEXT")
        if "subject" not in cols:
            self.conn.execute("ALTER TABLE events ADD COLUMN subject TEXT")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS feedback ("
            " id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, template TEXT NOT NULL,"
            " from_version INTEGER NOT NULL, to_version INTEGER NOT NULL, diff TEXT NOT NULL,"
            " created_at TEXT NOT NULL)"
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_tpl ON feedback(template, id)")

    def _init_fts(self) -> str:
        for tokenizer in ("trigram", "unicode61"):
            try:
                self.conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5("
                    f"title, body, session_id UNINDEXED, tokenize='{tokenizer}')"
                )
                return tokenizer
            except sqlite3.OperationalError:
                continue
        return "like"

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, tuple(params))
            self.conn.commit()
            return cur

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(sql, tuple(params)))

    # --------------------------------------------------------------------- kv
    def kv_get(self, key: str, default: str | None = None) -> str | None:
        rows = self.query("SELECT value FROM kv WHERE key = ?", (key,))
        return rows[0]["value"] if rows else default

    def kv_set(self, key: str, value: str | None) -> None:
        if value is None:
            self.execute("DELETE FROM kv WHERE key = ?", (key,))
        else:
            self.execute(
                "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ----------------------------------------------------------------- events
    def insert_event(self, row: dict[str, Any], episode_id: int | None = None) -> int | None:
        """Insert a normalised event row. Returns the id, or None for a duplicate."""
        if row["type"] in ("idle", "system") and episode_id is None:
            episode_id = 0
        with self._lock:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO events(ts, epoch, local_date, type, source, host, user, duration_s,"
                " data, text, episode_id, hash, activity, subject) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row["ts"],
                    row["epoch"],
                    row["local_date"],
                    row["type"],
                    row.get("source"),
                    row.get("host"),
                    row.get("user"),
                    row.get("duration_s"),
                    json.dumps(row["data"], ensure_ascii=False),
                    row.get("text"),
                    episode_id,
                    row["hash"],
                    row.get("activity"),
                    row.get("subject"),
                ),
            )
            self.conn.commit()
            return cur.lastrowid if cur.rowcount else None

    @staticmethod
    def event_dict(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["data"] = json.loads(d["data"]) if d.get("data") else {}
        return d

    def get_event(self, event_id: int) -> dict[str, Any] | None:
        rows = self.query("SELECT * FROM events WHERE id = ?", (event_id,))
        return self.event_dict(rows[0]) if rows else None

    def events_for_date(
        self,
        date: str,
        *,
        types: Iterable[str] | None = None,
        unassigned_only: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM events WHERE local_date = ?"
        params: list[Any] = [date]
        types = [t for t in (types or []) if t]
        if types:
            sql += f" AND type IN ({','.join('?' * len(types))})"
            params += types
        if unassigned_only:
            sql += " AND episode_id IS NULL"
        sql += " ORDER BY epoch, id"
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [self.event_dict(r) for r in self.query(sql, params)]

    def events_for_episode(self, episode_id: int) -> list[dict[str, Any]]:
        rows = self.query("SELECT * FROM events WHERE episode_id = ? ORDER BY epoch, id", (episode_id,))
        return [self.event_dict(r) for r in rows]

    def dates_with_unassigned(self) -> list[str]:
        rows = self.query("SELECT DISTINCT local_date FROM events WHERE episode_id IS NULL ORDER BY local_date")
        return [r["local_date"] for r in rows]

    def assign_events(self, event_ids: Iterable[int], episode_id: int) -> None:
        ids = list(event_ids)
        if not ids:
            return
        with self._lock:
            for chunk_start in range(0, len(ids), 500):
                chunk = ids[chunk_start : chunk_start + 500]
                self.conn.execute(
                    f"UPDATE events SET episode_id = ? WHERE id IN ({','.join('?' * len(chunk))})",
                    [episode_id, *chunk],
                )
            self.conn.commit()

    def search_events(
        self, query: str, date_from: str | None = None, date_to: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM events WHERE text LIKE ?"
        params: list[Any] = [f"%{query}%"]
        if date_from:
            sql += " AND local_date >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND local_date <= ?"
            params.append(date_to)
        sql += " ORDER BY epoch DESC LIMIT ?"
        params.append(int(limit))
        return [self.event_dict(r) for r in self.query(sql, params)]

    def unclassified(self, limit: int = 2000) -> list[dict[str, Any]]:
        rows = self.query("SELECT * FROM events WHERE activity IS NULL ORDER BY id LIMIT ?", (int(limit),))
        return [self.event_dict(r) for r in rows]

    def set_activity(self, items: list[tuple[str, str, int]]) -> None:
        with self._lock:
            self.conn.executemany("UPDATE events SET activity = ?, subject = ? WHERE id = ?", items)
            self.conn.commit()

    # -------------------------------------------------------------- feedback
    def add_feedback(self, session_id: int, template: str, from_v: int, to_v: int, diff: str) -> None:
        self.execute(
            "INSERT INTO feedback(session_id, template, from_version, to_version, diff, created_at) VALUES(?,?,?,?,?,?)",
            (session_id, template, from_v, to_v, diff, _now()),
        )

    def feedback_for(self, template: str, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.query("SELECT * FROM feedback WHERE template = ? ORDER BY id DESC LIMIT ?", (template, int(limit)))
        return [dict(r) for r in rows]

    def count_events(self, date: str) -> dict[str, int]:
        rows = self.query("SELECT type, COUNT(*) AS n FROM events WHERE local_date = ? GROUP BY type", (date,))
        return {r["type"]: r["n"] for r in rows}

    def purge_events(self, *, date: str | None = None, before: str | None = None) -> int:
        if not date and not before:
            raise ValueError("date or before is required")
        if date:
            cur = self.execute("DELETE FROM events WHERE local_date = ?", (date,))
            self.execute(
                "DELETE FROM episodes WHERE local_date = ? AND id NOT IN "
                "(SELECT CAST(ref AS INTEGER) FROM doc_sources WHERE kind = 'episode')",
                (date,),
            )
        else:
            cur = self.execute("DELETE FROM events WHERE local_date < ?", (before,))
            self.execute(
                "DELETE FROM episodes WHERE local_date < ? AND id NOT IN "
                "(SELECT CAST(ref AS INTEGER) FROM doc_sources WHERE kind = 'episode')",
                (before,),
            )
        return cur.rowcount

    # --------------------------------------------------------------- episodes
    @staticmethod
    def episode_dict(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["tags"] = json.loads(d.get("tags") or "[]")
        d["stats"] = json.loads(d.get("stats") or "{}")
        return d

    def create_episode(
        self,
        local_date: str,
        start_epoch: float,
        end_epoch: float,
        *,
        title: str = "",
        title_locked: bool = False,
        tags: list[str] | None = None,
        origin: str = "auto",
        open_task: bool = False,
    ) -> int:
        now = _now()
        cur = self.execute(
            "INSERT INTO episodes(local_date, start_epoch, end_epoch, title, title_locked, tags, origin,"
            " open_task, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                local_date,
                start_epoch,
                end_epoch,
                title,
                int(title_locked),
                json.dumps(tags or [], ensure_ascii=False),
                origin,
                int(open_task),
                now,
                now,
            ),
        )
        return int(cur.lastrowid)

    def get_episode(self, episode_id: int) -> dict[str, Any] | None:
        rows = self.query("SELECT * FROM episodes WHERE id = ?", (episode_id,))
        return self.episode_dict(rows[0]) if rows else None

    def episodes_between(self, date_from: str, date_to: str | None = None) -> list[dict[str, Any]]:
        rows = self.query(
            "SELECT * FROM episodes WHERE local_date >= ? AND local_date <= ? ORDER BY start_epoch",
            (date_from, date_to or date_from),
        )
        return [self.episode_dict(r) for r in rows]

    def update_episode(self, episode_id: int, **fields: Any) -> None:
        if not fields:
            return
        allowed = {"start_epoch", "end_epoch", "title", "title_locked", "tags", "origin", "open_task", "stats"}
        sets, params = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise KeyError(key)
            if key in ("tags", "stats"):
                value = json.dumps(value, ensure_ascii=False)
            if key in ("title_locked", "open_task"):
                value = int(bool(value))
            sets.append(f"{key} = ?")
            params.append(value)
        sets.append("updated_at = ?")
        params.append(_now())
        params.append(episode_id)
        self.execute(f"UPDATE episodes SET {', '.join(sets)} WHERE id = ?", params)

    def delete_episode(self, episode_id: int) -> None:
        self.execute("UPDATE events SET episode_id = NULL WHERE episode_id = ?", (episode_id,))
        self.execute("DELETE FROM episodes WHERE id = ?", (episode_id,))

    def episodes_referenced_by_docs(self) -> set[int]:
        rows = self.query("SELECT ref FROM doc_sources WHERE kind = 'episode'")
        return {int(r["ref"]) for r in rows if str(r["ref"]).isdigit()}

    # ------------------------------------------------------------------- docs
    @staticmethod
    def session_dict(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["meta"] = json.loads(d.get("meta") or "{}")
        return d

    def create_session(self, template: str, title: str, meta: dict[str, Any] | None = None) -> int:
        now = _now()
        cur = self.execute(
            "INSERT INTO doc_sessions(template, title, status, created_at, updated_at, meta) VALUES(?,?,?,?,?,?)",
            (template, title, "draft", now, now, json.dumps(meta or {}, ensure_ascii=False)),
        )
        return int(cur.lastrowid)

    def get_session(self, session_id: int) -> dict[str, Any] | None:
        rows = self.query("SELECT * FROM doc_sessions WHERE id = ?", (session_id,))
        return self.session_dict(rows[0]) if rows else None

    def list_sessions(self, status: str = "", template: str = "", limit: int = 30) -> list[dict[str, Any]]:
        sql = (
            "SELECT s.*, (SELECT MAX(version) FROM doc_versions v WHERE v.session_id = s.id) AS latest_version"
            " FROM doc_sessions s WHERE 1=1"
        )
        params: list[Any] = []
        if status:
            sql += " AND s.status = ?"
            params.append(status)
        if template:
            sql += " AND s.template = ?"
            params.append(template)
        sql += " ORDER BY s.updated_at DESC LIMIT ?"
        params.append(int(limit))
        return [self.session_dict(r) for r in self.query(sql, params)]

    def update_session(self, session_id: int, **fields: Any) -> None:
        allowed = {"title", "status", "meta", "template"}
        sets, params = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise KeyError(key)
            if key == "meta":
                value = json.dumps(value, ensure_ascii=False)
            sets.append(f"{key} = ?")
            params.append(value)
        sets.append("updated_at = ?")
        params.append(_now())
        params.append(session_id)
        self.execute(f"UPDATE doc_sessions SET {', '.join(sets)} WHERE id = ?", params)

    def add_source(self, session_id: int, kind: str, ref: str) -> bool:
        cur = self.execute(
            "INSERT OR IGNORE INTO doc_sources(session_id, kind, ref, added_at) VALUES(?,?,?,?)",
            (session_id, kind, str(ref), _now()),
        )
        return bool(cur.rowcount)

    def sources(self, session_id: int) -> list[dict[str, Any]]:
        rows = self.query(
            "SELECT kind, ref, added_at FROM doc_sources WHERE session_id = ? ORDER BY added_at, kind, ref",
            (session_id,),
        )
        return [dict(r) for r in rows]

    def add_version(self, session_id: int, markdown: str, change_note: str = "", author: str = "") -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS v FROM doc_versions WHERE session_id = ?", (session_id,)
            ).fetchone()
            version = int(row["v"]) + 1
            self.conn.execute(
                "INSERT INTO doc_versions(session_id, version, markdown, change_note, author, created_at)"
                " VALUES(?,?,?,?,?,?)",
                (session_id, version, markdown, change_note, author, _now()),
            )
            title_row = self.conn.execute("SELECT title FROM doc_sessions WHERE id = ?", (session_id,)).fetchone()
            title = title_row["title"] if title_row else ""
            if self.fts_mode != "like":
                self.conn.execute("DELETE FROM docs_fts WHERE session_id = ?", (session_id,))
                self.conn.execute(
                    "INSERT INTO docs_fts(title, body, session_id) VALUES(?,?,?)", (title, markdown, session_id)
                )
            self.conn.execute("UPDATE doc_sessions SET updated_at = ? WHERE id = ?", (_now(), session_id))
            self.conn.commit()
            return version

    def versions(self, session_id: int) -> list[dict[str, Any]]:
        rows = self.query(
            "SELECT version, change_note, author, created_at, LENGTH(markdown) AS chars FROM doc_versions"
            " WHERE session_id = ? ORDER BY version",
            (session_id,),
        )
        return [dict(r) for r in rows]

    def get_version(self, session_id: int, version: int | None = None) -> dict[str, Any] | None:
        if version:
            rows = self.query(
                "SELECT * FROM doc_versions WHERE session_id = ? AND version = ?", (session_id, version)
            )
        else:
            rows = self.query(
                "SELECT * FROM doc_versions WHERE session_id = ? ORDER BY version DESC LIMIT 1", (session_id,)
            )
        return dict(rows[0]) if rows else None

    def search_docs(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        rows: list[sqlite3.Row] = []
        use_fts = self.fts_mode == "unicode61" or (self.fts_mode == "trigram" and len(query) >= 3)
        if use_fts:
            phrase = '"' + query.replace('"', '""') + '"'
            try:
                rows = self.query(
                    "SELECT session_id, title, snippet(docs_fts, 1, '«', '»', '…', 16) AS snippet"
                    " FROM docs_fts WHERE docs_fts MATCH ? ORDER BY rank LIMIT ?",
                    (phrase, int(limit)),
                )
            except sqlite3.OperationalError:
                rows = []
        if not rows:
            rows = self.query(
                "SELECT v.session_id AS session_id, s.title AS title, substr(v.markdown, 1, 200) AS snippet"
                " FROM doc_versions v JOIN doc_sessions s ON s.id = v.session_id"
                " WHERE v.version = (SELECT MAX(version) FROM doc_versions WHERE session_id = v.session_id)"
                " AND (v.markdown LIKE ? OR s.title LIKE ?) LIMIT ?",
                (f"%{query}%", f"%{query}%", int(limit)),
            )
        return [dict(r) for r in rows]
