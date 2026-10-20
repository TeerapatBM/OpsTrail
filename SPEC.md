# OpsTrail — Specification (v0.3, single-user + web UI + quality loop)

> Single source of truth for every contributor (human, Claude, GPT/Codex/Copilot).
> If you change behaviour, update this file in the same change.

## 1. Problem

The team executes a lot of work (deployments, troubleshooting, configuration) but
almost nothing gets documented. OpsTrail records work activity quietly in the
background, groups it into work items ("episodes"), writes an automatic daily
worklog, and lets an AI assistant (Claude / GPT) turn any episodes into a proper
document (SOP, Delivery doc, Guide, …) through a resumable **doc session**.

Design principles:

1. **Low friction** – capture runs by itself; the user only adds a note when it matters.
2. **Structured signals over video** – shell commands, focused windows, notes and
   on-demand screenshots. No continuous screen recording.
3. **Local-first & private** – everything stays in `~/.opstrail`; secrets are
   redacted before they reach the database; pause + exclusion lists.
4. **The AI writes, OpsTrail remembers** – OpsTrail supplies facts, templates and persistence; an LLM
   writes the prose – either the MCP client's model, or (web UI) a provider the user configures
   (Claude API, OpenAI-compatible incl. local Ollama, Azure OpenAI), or any chat via copy/paste. No training.
5. **Unit of documentation = work item, not day** – a document can pull episodes
   from many days, and a day can feed many documents.

## 2. Architecture

```
 ┌────────────── user's PC (Windows first) ──────────────┐
 │                                                        │
 │  PowerShell / bash hook ─┐                             │
 │  Claude Code hook ───────┼─► ~/.opstrail/inbox/*.jsonl │
 │  CLI (note/shot/task) ───┘          │                  │
 │                                     ▼ ingest + redact  │
 │  Capture Agent ───────────────► SQLite (opstrail.db)   │
 │  (window/idle poller, hotkeys,      ▲                  │
 │   screenshots, daily recap)         │                  │
 │                                     │                  │
 │  MCP Server (stdio | streamable HTTP)                  │
 │        ▲                    ▲                          │
 └────────┼────────────────────┼──────────────────────────┘
          │                    │
   Claude Desktop /     VS Code (Copilot/GPT, Codex,
   Claude Code          Claude Code) via .vscode/mcp.json
                               │
                     Export → .md / .docx (~/Documents/OpsTrail)
```

Processes:

| Process | Entry point | Responsibility |
|---|---|---|
| Capture agent | `opstrail agent` (pythonw at logon) | foreground window + idle polling, hotkeys, screenshots, inbox ingest, episode grouping, auto daily recap |
| Web UI | thread inside the agent, or `opstrail web` | http://127.0.0.1:8765 – day/episodes, worklogs, document editor with AI, search, settings |
| MCP server | `opstrail mcp` (spawned by the AI client) | tools/resources/prompts over the store; also ingests the inbox on every call |
| CLI | `opstrail …` | manual capture, admin, export, debugging |
| Shell hooks | `hooks/powershell/OpsTrail.ps1`, `hooks/bash/opstrail.sh` | append one line per executed command to the inbox |

Concurrency: SQLite in WAL mode with `busy_timeout`. Inbox files are claimed by an
atomic rename (`*.jsonl` → `*.processing-<pid>`), so the agent and the MCP server can
both ingest safely. Duplicate inserts are blocked by a content hash.

## 3. Data locations

```
~/.opstrail/                 (override with $OPSTRAIL_HOME)
  config.toml                user configuration (created on first run)
  opstrail.db                SQLite store
  inbox/                     *.jsonl / *.tsv written by hooks & CLI
  shots/YYYY-MM-DD/*.png     screenshots
  logs/agent.log
  llm.json                   web UI AI settings; API key DPAPI-encrypted on Windows
  refresh.lock               cross-process lock for ingest + grouping
  paused                     flag file – when present nothing is captured
~/Documents/OpsTrail/        exports (config: general.export_dir)
<repo>/templates/            document templates (config: general.templates_dir)
```

## 4. Event schema (contract between producers and the store) — v1

Every producer writes one JSON object per line to `~/.opstrail/inbox/<name>.jsonl`:

```json
{
  "v": 1,
  "ts": "2026-10-20T09:15:02+07:00",
  "type": "shell",
  "source": "powershell",
  "host": "DESKTOP-01",
  "user": "teerapat",
  "duration_s": 1.8,
  "data": { "cmd": "Get-Service splunkd", "cwd": "C:\\", "success": true }
}
```

| field | required | notes |
|---|---|---|
| `v` | yes | schema version, currently `1` |
| `ts` | yes | ISO-8601 **start** time; offset recommended (naive = configured tz). Epoch seconds also accepted |
| `type` | yes | one of the types below |
| `source` | no | producer id (`powershell`, `bash`, `zsh`, `agent`, `cli`, `claude-code`, `mcp`) |
| `host`, `user` | no | default to the local machine/user |
| `duration_s` | no | seconds |
| `data` | yes | type-specific object |

| type | `data` fields |
|---|---|
| `shell` | `cmd`*, `cwd`, `success`, `exit_code`, `shell`, `session` |
| `window` | `app`*, `title`, `pid`, `presence` (written by the agent with `duration_s`; `presence: true` = a meeting window open in the background while the user works elsewhere, not focus time) |
| `note` | `text`*, `episode_id` |
| `screenshot` | `path`*, `app`, `title`, `caption` |
| `task` | `action`* (`start`/`stop`), `title` |
| `ai` | `tool`*, `cmd`, `file`, `description`, `cwd` (from Claude Code hooks) |
| `idle` | – (with `duration_s`) |
| `system` | `message` |

Alternative compact line format for POSIX shells (`*.tsv`):
`tsv1<TAB>epoch<TAB>exit_code<TAB>base64(cwd)<TAB>base64(cmd)<TAB>host<TAB>user<TAB>shell<TAB>session`

All string values are passed through the redactor (`opstrail.redact`) before storage.

## 4b. Activity classification

Every stored event gets `activity` + `subject` columns (`opstrail.activity`), from ordered regex rules in
`src/opstrail/data/activity_rules.toml` (user overrides in `~/.opstrail/activity_rules.toml`, checked first).
Activities: `meeting, chat, email, terminal, remote, console, research, docs, code, ai, files, other`
(notes/tasks keep their own type). `subject` = meeting subject, chat partner, console product, remote host…
Old rows are back-filled on refresh.

## 5. Episodes (work items)

Incremental grouping (`opstrail.episodes.assign_episodes`), run on every refresh:

1. Only events without an episode are processed; existing episode IDs never change.
2. An event that falls inside an existing episode's time span joins it.
3. `task start "<title>"` opens a **manual** episode (title locked) that collects
   everything until `task stop` or the end of the day.
4. Otherwise a new episode starts when the gap since the current episode's end
   exceeds `episodes.idle_split_min` (default 25 min), or when the **project label**
   changes and the new label lasts at least `episodes.min_run_min` (default 5 min).
5. Project labels come from `[projects]` keyword lists in `config.toml`
   (matched against window titles, commands, cwd, notes).
6. Auto titles are regenerated from stats until a user/AI renames the episode
   (`title_locked = 1`). `merge_episodes` combines episodes.
7. `idle` and `system` events are never assigned (`episode_id = 0`).
8. **Meetings first**: meeting-window events with the same subject and gaps ≤ `[meetings] merge_gap_min`
   form one meeting episode (`origin = "meeting"`, title `ประชุม: <subject>`, tag `meeting`). Anything that
   happens inside a meeting's span (a glance at Outlook) belongs to the meeting. Work after a meeting starts
   a new episode.
   **Background presence** (`[meetings] detect_background = true`, Windows): every poll the agent enumerates the
   visible top-level windows (`EnumWindows` + `IsWindowVisible`); while one classifies as `meeting` and the user is
   active in another window (e.g. sharing the screen and typing in a terminal), it records synthetic `window` segments
   (`data.presence = true`, ≤ 5 min each, not while idle/paused, excluded apps/titles respected). They count as meeting
   time (activity `meeting`) but not as focus/active time (`active_s`, window summaries, worklog totals).
   Because these segments arrive every few minutes, a meeting that grows in a refresh takes back events an earlier
   refresh put into an `auto` episode inside its new span; manual, merged, renamed (`title_locked`) and
   document-referenced episodes are never touched, and a work episode left empty is deleted.
9. A note written ≤ `[episodes] note_attach_min` (15) after an episode ended is attached to it (e.g. the
   meeting summary). Notes/tasks never stretch an episode's time span.
10. After a meeting ≥ `[meetings] min_minutes` ends (no meeting window for `grace_minutes`), the agent asks
   once for a summary (ประเด็น / การตัดสินใจ / action items) → note on the meeting episode.

## 6. Documents

* **Template** = folder `templates/<name>/` containing
  `template.toml` (title, description), `skeleton.md` (structure),
  `guide.md` (what each section must contain), optional `examples/` (good real
  documents: `.md`, `.txt`, `.docx`) and optional `reference.docx` (Word styles for export).
* **Doc session** = one document. It has a template, a title, a status
  (`draft` → `review` → `final`), a list of sources (episodes and/or whole dates)
  and an append-only list of versions (markdown).
* Flow: `start_doc_session` → returns a *source pack* (template guide + skeleton +
  facts from the sources) → the AI writes markdown → `save_draft` (new version) →
  later `get_doc_session` / `add_doc_sources` to continue → `export_doc` (.md/.docx).
* Screenshots are referenced in markdown as `![caption](shot://<event_id>)` and are
  resolved to real image files on export.
* Unknown facts must be written as `[TODO: …]` – the AI must never invent values.
* **Daily recap**: at `recap.time` (default 18:00) the agent builds a deterministic
  daily worklog (session with template `daily-worklog`, author `opstrail-auto`). An AI
  can later polish it with `daily_recap` + `save_draft`.

## 7. MCP interface

Server name `opstrail`. Transports: stdio (default) and streamable HTTP
(`opstrail mcp --http`, port 8766, optional bearer token via `OPSTRAIL_MCP_TOKEN`).

Tools (all return text — JSON or markdown):

| tool | purpose |
|---|---|
| `status` | capture state, today's counts, paths |
| `get_timeline(date, types, limit)` | raw events for a date |
| `search_activity(query, date_from, date_to, limit)` | find past commands/windows/notes |
| `list_episodes(date, date_to)` | work items with stats |
| `get_episode(episode_id, max_events)` | episode detail |
| `update_episode(episode_id, title, tags, note)` | rename / tag / annotate |
| `merge_episodes(episode_ids, title)` | combine work items |
| `add_note(text, episode_id)` | record context ("why") |
| `list_templates` | available document types |
| `start_doc_session(template, title, episode_ids, date, date_to)` | new document + source pack |
| `list_doc_sessions(status, template, limit)` | existing documents |
| `get_doc_session(session_id, include_sources)` | latest draft + history (+ source pack) to continue |
| `add_doc_sources(session_id, episode_ids, date, date_to)` | pull more work into a document |
| `save_draft(session_id, markdown, change_note)` | store a new version |
| `set_doc_status(session_id, status)` | draft/review/final |
| `export_doc(session_id, format)` | write .md and/or .docx |
| `daily_recap(date, save)` | deterministic worklog for a date |
| `search_docs(query, limit)` | full-text search over documents (Thai-friendly trigram) |
| `fact_check(session_id, version)` | values in a draft that are not in the captured sources |

Resources: `opstrail://templates/{name}`.
Prompts: `daily_worklog(date)`, `write_document(template, topic, date, date_to)`,
`continue_document(session_id)`.

## 6b. Quality loop

* **Learn from edits**: when a non-AI save follows an AI version, the unified diff is stored in `feedback`
  (`session_id, template, from_version, to_version, diff`). Prompts/source packs include the 2 latest
  corrections for that template and the template's **style lessons** (`~/.opstrail/style/<template>.md`),
  which the user edits or regenerates from the diffs ("เรียนรู้จากการแก้ไข", one LLM call).
* **Fact-check** (`opstrail.quality.fact_check`, deterministic): IPv4/CIDR/ports, x.y.z versions and
  hostnames in a draft that do not occur in the sources (+ skeleton) are reported as unsupported; run after
  every AI generation, on demand in the editor, via MCP `fact_check`, and by the eval.
* **AI episode titles**: one LLM call renames the day's auto-titled episodes (JSON contract), locking titles.
* **Evals** (`evals/`, `opstrail eval [--llm]`): golden-day fixtures + expectations (episode count, meetings,
  titles, exact meeting time, secrets redacted; with `--llm`: must-mention facts, forbidden strings,
  fact-check, skeleton coverage ≥ 70 %). Deterministic evals run in CI; the eval is the referee for changes.

## 7b. Web UI (localhost)

* Starlette app (`opstrail.web.app`), vanilla-JS SPA in `web/static` (no CDN, no build step).
* Bound to 127.0.0.1 (`[web] port`, default 8765). Middleware `LocalOnly`: Host header must be loopback
  (DNS-rebinding defence); non-GET requests need `X-OpsTrail: 1` and a same-origin Origin (CSRF defence);
  CSP `script-src 'self'`, `frame-ancestors 'none'`, `Cross-Origin-Resource-Policy: same-origin`.
* Screenshots are only served from inside `~/.opstrail/shots` (path-checked).
* JSON API (all under `/api`): `status`, `capture`, `day/{date}`, `day/{date}/recap`, `timeline`,
  `episodes/{id}` (GET/POST), `episodes/merge`, `notes`, `shots/{id}`, `templates`, `docs` (GET/POST),
  `docs/{id}` (+`/meta`, `/save`, `/generate`, `/prompt`, `/sources`, `/download`), `recaps`, `search`,
  `llm` (GET/POST), `llm/test`, `profile` (GET/POST), `docs/{id}/factcheck`, `day/{date}/ai-titles`,
  `style/{template}` (GET/POST), `style/{template}/learn`.
* AI generation (`OpsTrail.generate_draft`): system + user prompt = source pack (mode "api") + current draft
  (for revisions) + optional user instruction → provider in `opstrail.llm` → new version (author = provider:model).
  Copy prompt / Paste result offers the same flow without an API key.
* At recap time the agent opens `#/day/<date>?review=1` in the browser (`[web] open_on_recap`).

## 8. Privacy & security

* Redaction patterns: private keys, cloud keys, JWTs, bearer tokens, URL credentials,
  `--password`/`-Password`/`ConvertTo-SecureString` arguments, `key=value` secrets,
  `net user` passwords, `mysql -p…`, `sshpass -p`. Extendable via `redaction.extra_patterns`.
* Exclusions: `capture.exclude_apps`, `capture.exclude_title_patterns` (private
  browsing, banking, chat, password managers by default).
* Pause: hotkey, `opstrail pause`, or the `paused` flag file (hooks honour it too).
* Hotkeys on Windows use `RegisterHotKey` (only our combos are delivered – no keyboard hook / keylogging).
* `refresh()` (ingest + grouping) runs under a cross-process file lock (`~/.opstrail/refresh.lock`).
* `opstrail purge` deletes raw events by date.
* HTTP transport binds to 127.0.0.1 by default; set a token before exposing it.

## 9. Roadmap

* **v0.1** – single user, Windows-first agent, SQLite, MCP stdio/HTTP, 4 templates, md/docx export.
* **v0.2** – local web UI with AI providers (Claude API / OpenAI-compatible / Azure OpenAI), copy/paste prompt.
* **v0.3 (this)** – activity classifier, meeting episodes + post-meeting summary prompt, meeting-minutes template,
  learn-from-edits + style lessons, fact-check, AI episode titles, golden-day evals, GitHub CI (Windows) + task cards.
  v0.3.1: development autopilot `scripts/duo.ps1` (Claude Code + Codex on subscriptions, cross-review, gated merge).
* **next (Phase B, task cards T-101…T-108)** – browser URL capture, meeting presence while screen sharing, voice
  notes, web diff + streaming, Teams digest, PowerShell output capture, cross-model draft review, tray icon.
* **later** – M365 connector (T-109, needs approval); team mode (T-110): central server (Postgres), per-user auth,
  cloud audit-log collectors (Azure Activity/Entra, Alibaba ActionTrail, vCenter events), web review UI,
  SharePoint/Confluence publishing, knowledge-base search across the team.
