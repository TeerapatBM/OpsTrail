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

### Agent system tray

Optional `agent` extra includes `pystray>=0.19` and `Pillow>=10.0`. A daemon thread
inside the agent runs the tray backend; unavailable libraries, headless backends and
unsupported menus leave the agent running without a tray. macOS is skipped because
its tray backend requires the main-thread Cocoa runloop (see
[pystray threading requirements](https://pystray.readthedocs.io/en/latest/usage.html)).
Generated icon: green = recording enabled, grey = paused flag present (not an idle indicator).
Thai menu: open web, pause/resume, note, screenshot, today's Daily worklog, exit.
Callbacks enqueue actions; the agent drains them during its loop/sleep (every 250 ms
while sleeping), keeping SQLite/screenshot work on the agent thread. Pause uses
`Agent.hotkey_pause`; note uses `osapi.spawn_popup`; screenshot uses the existing
screenshot hotkey handler; browser links use `web.app.url` (configured loopback port).
Today's worklog opens the saved session, creating it only if absent; web-disabled
mode opens the existing review popup. Exit requests normal agent shutdown, including
segment flush/heartbeat reset and tray stop with a bounded thread join. External pause
changes refresh both icon and menu. No new config keys, events, API routes or storage.

## 3. Data locations

```
~/.opstrail/                 (override with $OPSTRAIL_HOME)
  config.toml                user configuration (created on first run)
  opstrail.db                SQLite store
  inbox/                     *.jsonl / *.tsv written by hooks & CLI
  shots/YYYY-MM-DD/*.png     screenshots
  transcripts/pwsh-<pid>-<session>-<n>.txt   PowerShell transcripts (only with [capture] shell_output = true;
                             raw output, deleted on pause / shell exit / after 12 h by the next shell start)
  logs/agent.log
  llm.json                   web UI AI settings; API key DPAPI-encrypted on Windows
  recap.json                 Teams webhook secret (DPAPI on Windows, base64/0600 elsewhere)
  browser_token              random per-install browser ingest token (Settings → extension Options)
  browser_token.lock         cross-process pairing-token creation lock
  refresh.lock               cross-process lock for ingest + grouping
  voice.lock                 cross-process voice capture/transcription lock
  models/                    faster-whisper small model cache (downloaded on first local use)
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
| `shell` | `cmd`*, `cwd`, `success`, `exit_code`, `shell`, `session`, `output`, `output_truncated` (see 4a) |
| `window` | `app`*, `title`, `pid`, `presence` (written by the agent with `duration_s`; `presence: true` = a meeting window open in the background while the user works elsewhere, not focus time) |
| `browser` | `url`*, `title`, `domain` (HTTP/HTTPS active tab, point-in-time; source `browser-extension`) |
| `note` | `text`*, `episode_id` |
| `screenshot` | `path`*, `app`, `title`, `caption` |
| `task` | `action`* (`start`/`stop`), `title` |
| `ai` | `tool`*, `cmd`, `file`, `description`, `cwd` (from Claude Code hooks) |
| `idle` | – (with `duration_s`) |
| `system` | `message` |

Alternative compact line format for POSIX shells (`*.tsv`):
`tsv1<TAB>epoch<TAB>exit_code<TAB>base64(cwd)<TAB>base64(cmd)<TAB>host<TAB>user<TAB>shell<TAB>session`

All string values are passed through the redactor (`opstrail.redact`) before storage.

### Voice notes (T-103)

Optional extra `voice = [sounddevice>=0.4, faster-whisper>=1.0]`; absent/broken optional
libraries show a Thai install toast, leaving ordinary notes/capture available.
`[hotkeys] voice = "<ctrl>+<alt>+v"` uses the existing RegisterHotKey path on Windows.
`opstrail popup voice [--episode ID]` and the meeting-summary popup's voice button launch
a separate process with an always-on-top Tk timer, stop/transcribe button and cancel action.
Default microphone, mono PCM int16 at 16 kHz, 100 ms reads, at most 60 seconds of frames.
The indicator also signals stop at 60 seconds. No automatic meeting audio capture.

`[voice] backend = "local"` (default), `"openai"` or `"azure"`:
- local: faster-whisper `small`, CPU/int8, automatic language detection (Thai/English),
  VAD enabled; model cache under `$OPSTRAIL_HOME/models`. First use downloads model weights.
  No audio uploads. No fallback to cloud on local failure.
- openai: HTTPS `https://api.openai.com/v1/audio/transcriptions`, multipart WAV + `whisper-1`.
- azure: configured Settings `azure_endpoint`, `azure_api_version`; separate
  `[voice] azure_deployment = ""` must name a Whisper deployment. HTTPS deployment audio
  transcriptions route. Cloud uses protected Settings key only when its provider matches
  backend, otherwise backend-specific `OPENAI_API_KEY` / `AZURE_OPENAI_API_KEY`.
  Never reuse a saved key from another provider. 120-second HTTP timeout, no redirects/retries.
  See [OpenAI transcription API](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create)
  and [Azure Whisper REST quickstart](https://learn.microsoft.com/en-us/azure/ai-services/openai/whisper-quickstart?pivots=rest-api).

Audio exists only in a restricted temporary `opstrail-voice-*.wav` in system TEMP;
delete in `finally` on success, cancellation, recording/transcription/storage failure.
Forced process termination/power loss can leave a temporary file; no durable audio inbox.
Cloud backends explicitly opt in to raw audio upload (audio cannot be text-redacted).
Esc/close cancels; in-flight transcription finishes for cleanup but its result is discarded.
Pause prevents recording and discards results before transcription/save; UI observes pause
every 100 ms while open. Missing microphone/model/network/key returns a generic Thai error,
without logging upstream bodies or raw transcript. One capture/transcription per home via voice.lock.

`OpsTrail.record_voice` delegates to `voice.capture_note`; worker owns its SQLite connection.
Freeze explicit meeting episode or most recent current/just-ended episode within
`episodes.note_attach_min` (default 15) before transcription; otherwise use normal note grouping.
Save through `add_note`/`record` redaction as existing schema-v1 `note`, `source = "voice"`.
No new MCP tool, API route, event type or database column.

## 4a. Command output (opt-in, PowerShell only)

`[capture] shell_output = false` (default) / `shell_output_lines = 15`. When enabled (read by the hook when the
shell starts), `hooks/powershell/OpsTrail.ps1` runs `Start-Transcript` per session into `~/.opstrail/transcripts/`.
In `prompt` it reads what the transcript gained since the previous prompt (≤ 64 KB), drops the echoed
`PS …> <command>` line(s), trims blank edges, keeps the first `shell_output_lines` lines (each ≤ 400 chars) and
attaches them as `data.output` (`\n`-separated; `data.output_truncated = true` when more existed). The transcript
offset advances on every prompt, so each command only gets its own output. An `Exiting` handler stops the transcript
and deletes the file; files older than 12 h (shells closed with X) are deleted by the next shell start.
Pause (`~/.opstrail/paused`): a shell started while paused does not start the transcript; when the flag appears, the
next `prompt` stops the transcript and deletes the file (that prompt's output is discarded). The first `prompt`
after the flag is removed starts a new file (`-<n>` suffix), so the first command after resume has no output.
Lazy transcript headers are stripped with or without a UTF-8 BOM (Windows PowerShell 5.1), including after resume.
Ingest redacts `output` like every string, then (`events.normalize`) drops it unless `shell_output` is on and cuts it
to `shell_output_lines`. `text`/search stay command-only. Source packs list each command's output (max 15 lines,
`    │ ` prefix, `│ …` when truncated) under the command; worklogs and title prompts don't. Not captured: bash/zsh
(no portable transcript), hosts without transcription (command still recorded), and output after the user runs
`Stop-Transcript` (it stops OpsTrail's transcript too).

## 4b. Activity classification

Every stored event gets `activity` + `subject` columns (`opstrail.activity`), from ordered regex rules in
`src/opstrail/data/activity_rules.toml` (user overrides in `~/.opstrail/activity_rules.toml`, checked first).
Activities: `meeting, chat, email, terminal, remote, console, research, docs, code, ai, files, other`
(notes/tasks keep their own type). `subject` = meeting subject, chat partner, console product, remote host…
Old rows are back-filled on refresh.

Browser events use these same ordered rules; default rule types now include `browser` and `@browser`
matches browser events without a process name. Optional `url_regex` matches `data.url`; when both it and
`title_regex` are supplied, both must match. A named `subject` group in the URL takes precedence over the
title group. Invalid `url_regex` rules are skipped. Built-in URL rules identify Azure portal and Sentinel
before ambiguous title rules. Browser URL/title appear in timeline/search and chronological source packs.
They have no measured focus duration; the existing episode-span fallback still applies without focus windows.

## 4c. Browser extension capture (opt-in)

Load `extension/` unpacked in Edge/Chrome 103+ (Manifest V3). Settings → Browser extension → show/copy token
calls `POST /api/browser/token` (requires `X-OpsTrail: 1` and the usual same-origin policy, no extension
origin). Response `{token}` has `Cache-Control: no-store`; token is never in status or GET APIs.
Creation is locked, random 32 bytes URL-safe encoded (43 chars), stored in `browser_token` (0600 on POSIX;
inherited user-directory permissions on Windows). Delete that file to re-pair all extensions.

`POST /api/ingest/browser` accepts `{url, title, tab_id, ts, incognito?: false}`. Requires both
`X-OpsTrail: 1` and `X-OpsTrail-Browser-Token: <token>` even for local callers. LocalOnly still validates
Host first. Only this POST accepts `chrome-extension://<32 a-p characters>` Origin with a matching token;
other origins/routes remain blocked. No wildcard CORS or preflight allowance. The privileged extension
worker uses loopback host permissions ([Chrome network request model](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests));
web pages/content scripts cannot use this route cross-origin. CSP and other LocalOnly headers remain.
Returns `{stored: bool, event_id: int|null}` (false for paused/excluded/deduplicated); invalid payload = 400,
missing/wrong token/header/host/origin = 403. `tab_id` is validated but not stored; `ts` uses schema §4.

Before `OpsTrail.record` → `store_event` → `redact_obj`, the service validates HTTP/HTTPS URL and removes
userinfo; derives lowercase hostname (without port); applies `exclude_title_patterns`, `exclude_domains`
(case-insensitive exact domain + all subdomains, optional `*.` prefix), and the paused flag.
`[capture] browser_keep_query = false` strips the main query and `?…` inside SPA fragments while retaining
fragment routes (Azure blades). Set true to retain query parameters, still subject to the redactor.
Default excluded domains: mail.google.com, outlook.live.com, mail.yahoo.com, proton.me, kasikornbank.com,
kbank.co.th, scb.co.th, krungthai.com, bangkokbank.com, krungsri.com. This is a starter list; users must add
their personal services. Change config.toml then restart the agent/web server.

Worker sends active tabs only in the focused browser window on activation, URL/title change, focus change
or extension options change. Debounces bursts and sends at most once per 3 seconds globally; last attempt
time alone lives in `storage.session` across worker restarts. No incognito support (`not_allowed` plus runtime
checks), content scripts, browsing history, telemetry or durable URL queue. Token/port use `storage.local`
(not sync); only network destination is `http://127.0.0.1:<port>/api/ingest/browser`. No redirects, 5s timeout;
offline/errors drop the event silently. Unsupported/missing tabs and unavailable web service degrade to
normal window-title capture. No extension-store publishing or additional Python dependencies.

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
   time (activity `meeting`) but not as focus/active time (`active_s`, window summaries, worklog totals; a
   presence-only episode has `active_s = 0`). When presence starts or stops, the focused window's segment is cut at
   that moment, so foreground work after the call never stretches the meeting.
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
* **Teams digest (opt-in)**: `[recap] teams_webhook_url = ""` is an empty placeholder only;
  nonempty TOML values are ignored. Configure the actual secret in web Settings, stored only in
  `recap.json` via `secretstore` (same protection as LLM keys). Empty input keeps the current secret;
  explicit removal disables delivery. Invalid/unreadable secrets disable delivery with a safe log.
  When the agent creates an automatic recap (including yesterday's catch-up/revision), its existing
  `recap_done:<date>` gate dispatches one daemon thread. Manual CLI/MCP/web recaps do not send.
  The worker receives only URL + projected payload, never uses SQLite, POSTs with a 10-second timeout
  and retries once immediately on failure (including non-2xx). No redirects; failure logs contain
  neither URL, response body nor exception text. No durable retry queue; shutdown may interrupt delivery,
  and an ambiguous timeout can duplicate a delivered card. Failed sends do not undo the local recap.
  Payload: `{type: "message", attachments: [{contentType: "application/vnd.microsoft.card.adaptive",
  contentUrl: null, content: {type: "AdaptiveCard", version: "1.4", body: [...]}}]}`.
  Sections: work items, meetings, doc candidates (same SOP/Delivery thresholds as the worklog).
  Only titles and local start/end times leave the machine, at most 15 entries per section and 100
  characters per title, with an omitted-item count. Heuristic titles and meeting subjects come from
  capture, so they become `งาน #id` / `ประชุม #id`; locked titles (manual or AI-renamed) are redacted again,
  with Markdown syntax removed. A locked title repeating a captured command/window title/subject
  anywhere in that day's capture (case-insensitive, normalized whitespace) is replaced by the generic label too.
  No commands, window titles, notes, output, screenshots,
  source packs, author identity or document bodies are posted. HTTPS required; HTTP allowed only
  for loopback tests. Webhook URL authorizes the Workflows request; tenant-authenticated webhooks
  requiring OAuth are not supported.

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
  titles, exact meeting time, secrets redacted in stored text + data, source-pack facts `[case.pack] must_contain`;
  per-case `capture = {…}` config; with `--llm`: must-mention facts, forbidden strings,
  fact-check, skeleton coverage ≥ 70 %). Deterministic evals run in CI; the eval is the referee for changes.

## 7b. Web UI (localhost)

* Starlette app (`opstrail.web.app`), vanilla-JS SPA in `web/static` (no CDN, no build step).
* Bound to 127.0.0.1 (`[web] port`, default 8765). Middleware `LocalOnly`: Host header must be loopback
  (DNS-rebinding defence); non-GET requests need `X-OpsTrail: 1` and a same-origin Origin (CSRF defence);
  CSP `script-src 'self'`, `frame-ancestors 'none'`, `Cross-Origin-Resource-Policy: same-origin`.
* Screenshots are only served from inside `~/.opstrail/shots` (path-checked).
* JSON API (all under `/api`): `status`, `capture`, `day/{date}`, `day/{date}/recap`, `timeline`,
  `episodes/{id}` (GET/POST), `episodes/merge`, `notes`, `shots/{id}`, `templates`, `docs` (GET/POST),
  `docs/{id}` (+`/meta`, `/save`, `/generate`, `/diff`, `/prompt`, `/sources`, `/download`), `recaps`, `search`,
  `llm` (GET/POST), `llm/test`, `profile` (GET/POST), `docs/{id}/factcheck`, `day/{date}/ai-titles`,
  `style/{template}` (GET/POST), `style/{template}/learn`.
* `recap/settings` (GET/POST): GET returns only `{has_webhook: bool}`. POST accepts
  `{teams_webhook_url?: str, clear_webhook?: bool}` (clear wins); same safe response, never the URL
  or protected token. Normal LocalOnly/CSRF protection applies. Validation/storage failures are safe JSON 400.
* AI generation (`OpsTrail.generate_draft`): system + user prompt = source pack (mode "api") + current draft
  (for revisions) + optional user instruction → provider in `opstrail.llm` → new version (author = provider:model).
  Copy prompt / Paste result offers the same flow without an API key.
* Saved-version comparison: `GET /api/docs/{id}/diff?from=<version>&to=<version>` requires two positive,
  existing version numbers belonging to that session (invalid/missing versions → JSON 400). Service uses
  `difflib.SequenceMatcher` and returns `{hunks: [{op, before, after}, ...]}`; `op` is `equal`, `insert`,
  `delete` or `replace`. Concatenating each side reconstructs the exact saved Markdown. Tokens preserve
  whitespace, Latin words and Thai combining clusters. The web comparison shows two escaped text columns
  and expands changed clusters to complete Thai words with built-in `Intl.Segmenter("th")`; older browsers
  fall back to cluster highlights. Any two saved versions may be selected; unsaved edits are excluded.
* `POST /api/docs/{id}/generate?stream=1` (same JSON `{instruction}` and CSRF rules) returns
  `text/event-stream`, `Cache-Control: no-cache`. Frames have named SSE events and JSON data containing
  `event`: `delta` adds `{text}`, `done` carries the same saved `{session_id, version, markdown, model,
  truncated, fact_check}` as non-stream generation, and `error` carries a safe `{error}` message.
  Validation of the document happens before streaming (JSON 400). Provider/configuration failures after
  the stream opens are `error` events with HTTP 200. Anthropic uses Messages `stream: true` through
  `message_stop`; OpenAI-compatible/Azure use Chat Completions SSE through `[DONE]` after a finish reason.
  Only successful terminal streams save one version (including explicitly token-limited answers, marked
  `truncated`): accepted reasons are Anthropic `end_turn`/`stop_sequence`/`max_tokens` and OpenAI/Azure
  `stop`/`length`. Refusal/filter/tool/unknown reasons and empty/error/malformed/interrupted answers save
  nothing. The editor displays deltas live,
  locks editing/save/version switching until completion, and restores its prior content on stream failure.
  Requests without `stream=1` retain the synchronous JSON contract. No dependencies or CSP changes.
* At recap time the agent opens `#/day/<date>?review=1` in the browser (`[web] open_on_recap`).

## 8. Privacy & security

* Redaction patterns: private keys (also a block cut off by truncation), cloud keys, JWTs, bearer tokens, URL
  credentials, `--password`/`-Password`/`ConvertTo-SecureString` arguments, `key=value` secrets (incl. env-style
  `SPLUNK_PASSWORD=`),
  `net user` passwords, `mysql -p…`, `sshpass -p`. Extendable via `redaction.extra_patterns`.
* Exclusions: `capture.exclude_apps`, `capture.exclude_title_patterns` (private
  browsing, banking, chat, password managers by default).
* Pause: hotkey, `opstrail pause`, or the `paused` flag file (hooks honour it too).
* Command output capture is off by default. Its transcript file holds raw (unredacted) output on the local disk
  while the shell runs; pausing stops and deletes it at the next prompt (see §4a for cleanup).
  Output lines are cut at 400 chars, so a quoted secret whose closing quote was cut off is masked to the end of
  the line.
* Hotkeys on Windows use `RegisterHotKey` (only our combos are delivered – no keyboard hook / keylogging).
* `refresh()` (ingest + grouping) runs under a cross-process file lock (`~/.opstrail/refresh.lock`).
* `opstrail purge` deletes raw events by date.
* HTTP transport binds to 127.0.0.1 by default; set a token before exposing it.
* The opt-in Teams Workflows webhook is an additional outbound destination at automatic recap time;
  see §6 for its restricted projection and secret handling. Off by default; no telemetry or new dependency.

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
