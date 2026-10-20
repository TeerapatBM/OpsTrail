# HANDOFF — shared task board (Claude ↔ GPT ↔ Bro)

Protocol: see `AGENTS.md`. Claim with `[claimed: <agent> <YYYY-MM-DD>]`, move to *Done* with a summary.

## Status — v0.3.1 (2026-10-20, built by Claude)

v0.3.1: **duo autopilot** `scripts/duo.ps1` — Claude Code + Codex build and cross-review task cards unattended on Bro's
subscriptions (no API key, no approval prompts): worktree per card → builder → gate (pytest + eval, run by the
script) → reviewer of the other model → fix rounds → PR + CI → squash-merge → local pull + agent restart; nightly
via Task Scheduler. Prompts in `scripts/duo/prompts/`, Claude permission files in `scripts/duo/`, interactive
configs in `setup/claude`, `setup/codex`. Cards now carry `**Status:**` + `**Priority:**`. Claude review action
uses `CLAUDE_CODE_OAUTH_TOKEN` (subscription) and skips duo PRs. Claude Code hook honours `OPSTRAIL_NO_CAPTURE`.
Tested with fake claude/codex/gh CLIs on pwsh 7 (gate fail → fix, CHANGES → fix → APPROVE → merge, never-approved
→ needs-bro, Codex sandbox fallback, quota stop, local-only mode); `tests/test_duo.py` runs the script end-to-end
with fake CLIs (Windows PowerShell 5.1 on the Windows CI runner). Not yet run with the real CLIs on Bro's laptop.

v0.3 (Phase A): activity classifier (rules TOML), meetings as their own episodes with exact times +
post-meeting summary popup, notes attach to what just ended, `meeting-minutes` template, profile name
(fixes "Lenovo X1 Gen 9" as author), learn-from-edits + style lessons, deterministic fact-check after every AI
draft, AI episode titles, golden-day eval harness (`opstrail eval`), GitHub kit (CI on Windows/Linux incl.
PowerShell 5.1 checks + Windows-only tests, Claude PR review, Copilot setup steps, PR/issue templates,
`scripts/init-github.ps1`), task cards T-101…T-110. Tests: 91 (+5 Windows-only); v0.3.1: 97 (+5).
Repo: https://github.com/TeerapatBM/OpsTrail — push with `scripts/init-github.ps1` (Claude's session has no GitHub access).

v0.2.1: Bro ran it on Windows — installer, agent, web UI and DPAPI key storage work. Fixed: Claude API keys that
span several workspaces need the `anthropic-workspace-id` header → new "Workspace ID" setting + Thai hint in the
error; Settings warns when the chosen model isn't in the account's model list; new `opstrail stop|restart`.

v0.2 adds the **local web UI** (http://127.0.0.1:8765, served by the agent or `opstrail web`): day/episode view,
worklogs, document editor with "AI write/revise" (Claude API, OpenAI-compatible incl. Ollama, Azure OpenAI),
copy/paste prompt, version history, .docx/.md download, search, settings. Tested: 59 pytest tests (API,
security middleware, providers against a fake LLM server) + Playwright e2e (create doc with AI, save,
download, recap, search, settings, mobile/dark) with no console errors.

v0.1 baseline:

Working and tested (pytest: 46 tests, Python 3.10 + 3.13, mcp SDK 1.30 and 2.3; PowerShell hook simulated on pwsh 7.4):
- Inbox ingest with redaction, dedupe, crash recovery; PowerShell + bash/zsh + Claude Code hooks
- Episode grouping (gap split, project keywords, manual tasks, merge/rename), daily recap
- Doc sessions with versions, source packs, 4 Thai templates, export .md (+assets) / .docx (+screenshots,
  optional company `reference.docx`), Thai-friendly full-text search
- MCP server: 18 tools, 1 resource template, 3 prompts; stdio + streamable HTTP (optional bearer token)
- CLI, capture agent (window/idle polling, hotkeys, screenshots, auto recap + review popup), installer

**Not yet verified on a real Windows desktop** (the build machine was Linux): winapi.py, RegisterHotKey
hotkeys, screenshots, tkinter popups (focus), install.ps1, PowerShell hook under Windows PowerShell 5.1.
→ first backlog item.

## Backlog (top = next) — detailed cards in docs/tasks/

0. [ ] **Push to GitHub** (`scripts/init-github.ps1`), then `scripts/duo.ps1 -Setup` and `-Schedule 22:30 -MaxTasks 2`
   (optional secret `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`) — _owner: Bro_. Order of work = card Priority.
- ~~T-101 browser extension (GPT)~~ done · T-103 voice note (GPT)
- ~~T-105 Teams digest (GPT)~~ done · ~~T-106 PowerShell output capture (Claude)~~ done
- T-107 cross-model reviewer "ให้ AI ตรวจ" (GPT) · T-109 M365 connector (Claude, blocked: M365 approval)
- T-110 team-mode design (Claude → reviewed by GPT)

Older backlog items (kept for reference):

1. [ ] **Windows smoke test** on Bro's laptop (partly done 2026-10-20: install, agent, web, DPAPI OK — still to check
   hotkeys/popups/screenshots/PowerShell hook over a full day): run `scripts/install.ps1`, `opstrail doctor`, use hotkeys for
   an hour, check `opstrail timeline` / `episodes`, ask Claude Desktop + Copilot for a daily recap. Fix what breaks.
   _owner: Bro + any agent_
2. [ ] **Import the team's real document formats** (Bro will provide a folder): put good examples into
   `templates/<type>/examples/`, company Word template as `reference.docx`, adapt `skeleton.md` / `guide.md`.
3. [x] **Teams digest** at recap time (T-105): optional protected Workflows webhook, title/time-only Adaptive Card.
4. [x] (T-106) **PowerShell output capture** (opt-in): `Start-Transcript` per session, attach the first N lines of output
   to each shell event for "expected result" sections in SOPs. _suggested: Claude_
5. [x] **Tray icon** (T-108): status, pause/resume, web, note, screenshot, today's recap, exit; exports-folder shortcut deferred (outside card).
6. [ ] **Better episode titles** using MCP sampling (ask the client model for a 6-word title) with fallback
   to the current heuristic.
7. [ ] **Remote SSH capture**: helper to pull `~/.opstrail/inbox/*.tsv` from servers where the bash hook is
   sourced, or wrap `ssh` with `script` logging.
8. [x] **Browser URL capture** (T-101): opt-in Edge/Chrome extension, token pairing and exclusions.
9. [ ] **Web UI polish**: streaming AI output, diff view between versions, drag-drop images into docs,
   per-section "rewrite this section" button. _suggested: GPT_
10. [ ] **ChatGPT (web/desktop) as an MCP client**: expose HTTP MCP through Cloudflare Tunnel with OAuth
   (lower priority now that the web UI + copy/paste covers ChatGPT).
11. [ ] **Team mode (v0.3)**: central server (Postgres), per-user auth, cloud audit-log collectors
    (Azure Activity/Entra, Alibaba ActionTrail, vCenter), web review UI, SharePoint publishing.

## Done

- T-101 browser URL capture — GPT, 2026-10-20 [claimed: GPT 2026-10-20]. MV3 focused-tab capture, per-install
  pairing Settings, protected ingest, privacy filters/redaction, URL classification and source-pack facts.
  Files: `extension/`, `browser.py`, service/events/config/activity/render/web, `tests/test_browser*`, SPEC/README/card/plan. Node 3/3; pytest/eval blocked by shared Python launcher; interactive browser smoke pending.

- T-108 system tray — GPT, 2026-10-20. Optional background tray with queued Thai menu actions, green/grey
  pause state, existing-worklog preservation and graceful missing/backend fallback; normal shutdown cleanup.
  Files: `agent/tray.py`, `agent/daemon.py`, `pyproject.toml`, `tests/test_tray.py`, `tests/test_windows.py`, SPEC/README/card. Python gates blocked by sandbox launcher; runner + desktop smoke pending.
  Round 2: fixed the gate's lazy PowerShell transcript header parsing for UTF-8 BOM; added a focused Windows regression.
  Direct PowerShell regression and 10/10 unchanged pause/resume scripts pass; full pytest/eval remain blocked by the shared Python launcher.

- T-105 Teams digest — GPT, 2026-10-20. Opt-in protected Settings webhook, title/time-only Adaptive Card 1.4,
  daemon-thread POST with one retry and safe logs; automatic recap gate includes yesterday's catch-up.
  Files: `teams.py`, `service.py`, `config.py`, `agent/daemon.py`, `web/app.py`, `web/static/app.js`, `tests/test_teams.py`, `tests/test_windows.py`, SPEC/README/card/plan. Python gates blocked by sandbox launcher; runner + tenant smoke pending.

- T-106 PowerShell output capture (opt-in) — Claude, 2026-10-20. `[capture] shell_output` → hook runs `Start-Transcript`
  per session, slices it in `prompt` into `data.output` (first `shell_output_lines`); ingest redacts, drops it unless
  opted in, cuts lines; source pack shows `│` output under each command; eval case `sop-output-day` (+ `[case.pack]`).
  Files: `hooks/powershell/OpsTrail.ps1`, `config.py`, `events.py`, `redact.py`, `render.py`, `evals.py`, `evals/`,
  `tests/test_shell_output.py`, `tests/test_windows.py`, SPEC §3/§4/§4a/§6b/§8, README, card.
  Round 2 (GPT review): unterminated quoted secrets (cut at 400 chars) are redacted; pause stops + deletes the
  transcript and a shell started paused never transcribes (`Start-/Stop-OpsTrailTranscript`). Tests:
  `test_quoted_secret_cut_by_line_truncation_is_redacted`, `test_powershell_51_hook_does_not_transcribe_while_paused`.
- T-104 web diff + streaming — GPT, 2026-10-20. Added difflib saved-version API + Thai word comparison;
  Anthropic/OpenAI/Azure SSE into the editor, save-on-success + fact-check, safe failure recovery.
  Files: `service.py`, `llm.py`, `web/app.py`, `web/static/app.js`, `app.css`, `tests/test_web.py`, `tests/web_editor_smoke.cjs`, SPEC/README/card/plan.
  Verification: Playwright fixture smoke clean; pytest/eval blocked because sandbox cannot launch shared Windows Store Python (runner must run both).
- v0.1.0 initial implementation — Claude, 2026-10-20 (all files).
- v0.2.0 local web UI + LLM providers — Claude, 2026-10-20 (`web/`, `llm.py`, `secretstore.py`, service web helpers).
- v0.3.1 duo autopilot — Claude, 2026-10-20 (`scripts/duo.ps1`, `scripts/duo/`, `setup/claude`, `setup/codex`, cards, workflow, docs).
- v0.3.0 Phase A quality loop — Claude, 2026-10-20 (`activity.py`, `quality.py`, `evals.py`, episodes meetings, web, setup/github, docs/tasks).
- T-102 meeting presence while screen sharing — Claude, 2026-10-20. Agent enumerates visible windows each poll; an open
  meeting window while focus is elsewhere → `window` segments with `data.presence = true`; a growing meeting reclaims
  work grouped into auto episodes inside its span; presence is meeting time, not focus time. Files: `agent/winapi.py`,
  `agent/osapi.py`, `agent/daemon.py`, `episodes.py`, `events.py`, `render.py`, `recap.py`, `service.py`, `config.py`,
  `evals/` (screen-share-day), tests, SPEC §4/§5, README.
  Round 2 (GPT review): focus segment is split when presence starts/stops (`Agent._split_focus`); presence-only
  episodes report `active_s = 0` (fallback span ignores presence). Tests in `test_agent.py`, `test_ingest_episodes.py`.

## Review requests

- [ ] Claude (Claude Code): review T-101 token/Origin/Host isolation, URL query/fragment privacy,
  classification/source-pack integration and worker debounce/focus races. Run pytest + eval (shared Python
  launcher cannot start in Codex sandbox), then real Edge/Chrome load-unpacked pairing and InPrivate smoke.

- [ ] Claude (Claude Code): review T-108 tray startup/shutdown races, queued actions and worklog preservation;
  run pytest + eval (shared Python cannot launch in Codex sandbox), then Windows desktop smoke (Thai menu, colors, screenshots, exit).
  Round 2 review request: include UTF-8 BOM handling in lazy transcript headers and `test_powershell_51_lazy_transcript_header`.

- [ ] Claude (Claude Code): review T-105 secret persistence/API, capture-derived title suppression and background
  delivery/retry; run pytest + eval (shared Python cannot start in Codex sandbox), then synthetic Teams tenant smoke.

- [ ] GPT (Codex): review T-106 — transcript slicing in `hooks/powershell/OpsTrail.ps1` (`Read-OpsTrailTranscript`,
  `Format-OpsTrailOutput`: echo-line stripping, offset handling, cleanup), `events._shell_output`, the two redaction
  pattern changes in `redact.py` (env-style `*_PASSWORD=`, truncated PEM) and `render.command_lines(with_output=)`.
- [ ] Claude (Claude Code): review T-104 provider terminal/error handling, save-once lifecycle, Thai word diff,
  and editor state/escaping; run pytest + eval (shared Python launcher is inaccessible in Codex sandbox).
- [ ] GPT: review `src/opstrail/episodes.py` grouping heuristics and `export.py` markdown→docx edge cases.
- [ ] GPT: review `web/static/app.js` (renderMd escaping, editor dirty-state) and `web/app.py` LocalOnly middleware.
- [ ] GPT (Codex): review T-102 — `Agent.presence_tick` in `agent/daemon.py`, `winapi.top_level_windows`, and
  `_reclaim_for_meetings` in `episodes.py` (moving already-assigned events between episodes is new).

## Decision log

- 2026-10-20 — T-101 (GPT): Settings reveals the per-install token only via protected POST `/api/browser/token`
  with no-store (never GET/status). Creation uses existing cross-process lock; random 32-byte token in
  `browser_token`, 0600 on POSIX / inherited directory permissions on Windows. Delete file to re-pair.
  Browser ingest requires X-OpsTrail plus X-OpsTrail-Browser-Token even for local callers. Only this POST
  permits a valid chrome-extension Origin; no CORS/preflight wildcard, no changes to other routes/Host/CSP.
  The privileged MV3 worker's loopback host permission permits cross-origin requests without CORS approval
  (Chrome's official extension network model). No content scripts or page messaging surface.
- 2026-10-20 — T-101 (GPT): filter in browser.py called by service.py, then normal record/store_event redaction.
  Drop userinfo, strip query in both URL and SPA fragment by default while retaining Azure blade routes;
  derive domain before redaction, match exclusions by exact/suffix boundary (including trailing dot).
  Broken title exclusion fails closed. Store URL/title/domain only; tab id validates input but is discarded.
  Browser events are additive schema v1, point-in-time facts with no focus duration; source packs explicitly
  include URLs. Existing ordered classifier gains browser/@browser and ANDed url_regex; URL rules identify
  Azure/Sentinel before ambiguous titles, invalid URL regex rules are skipped. No unrelated grouping changes.
- 2026-10-20 — T-101 (GPT): extension stores only pairing token/port locally (never sync) and last attempt time
  in storage.session so worker restart keeps the three-second limit. Query the current focused window/tab
  again at dispatch; incognito denied in manifest and runtime. No durable URL queue; offline/timeout drops
  capture, no redirects/retries. Chrome/Edge 103+ APIs; missing web service leaves ordinary window capture.
  A synthetic slow-fetch regression reproduced a dropped trailing update: a fired timer's stale handle
  suppressed rescheduling after busy requests. Clear it at flush entry; Node harness now passes 3/3.
- 2026-10-20 — T-101 (GPT): focused pytest, full pytest and eval attempted using the prescribed shared venv;
  all blocked before startup by "The file cannot be accessed by the system". No substitute interpreter or
  dependency installation. Node harness and syntax checks pass; Python gates and real load-unpacked desktop
  smoke are pending runner/Claude/Bro. This is an execution limit, not a passing Python/eval claim.

- 2026-10-20 — T-108 round 2 (GPT): gate failure came from T-106's lazy transcript header parser, not tray code.
  Reproduced missing output after the second resume; a deterministic synthetic-header test fails only with BOM.
  UTF8.GetString preserves U+FEFF, so the anchored opening delimiter failed. Allow an optional BOM, keeping
  the existing pause/output/privacy assertions unchanged. A timing hypothesis was disproven by waiting for
  the output on disk; no sleeps or retries were added. Direct new regression passes and the extracted original
  pause/resume script passes 10/10 with command/output/secret/cleanup assertions. Full pytest and eval were
  attempted again but the shared Python launcher reports "The file cannot be accessed by the system";
  runner gates remain required. No dependencies, schema or tray design changes.

- 2026-10-20 — T-108 (GPT): card authorizes optional pystray/Pillow in `agent`; generate a simple status dot
  in memory (no asset/download). Run backend on its own daemon thread and enqueue callbacks for the agent
  thread to avoid cross-thread SQLite and screenshot work. Poll queue/state during existing sleep (250 ms).
  Pause reuses hotkey_pause; exit uses normal loop shutdown. Missing/headless/unsupported-menu backends
  log a generic fallback; skip macOS explicitly because pystray requires the main Cocoa runloop there.
- 2026-10-20 — T-108 (GPT): today's worklog opens an existing session without regenerating edits, otherwise
  creates it via daily_recap; web links use configured loopback port via web.app.url. With web disabled,
  worklog uses the existing review popup and open-web explains how to enable it. No config/schema changes.
  Exports-folder action from the older backlog is deferred because the task card's menu is the contract.
- 2026-10-20 — T-108 (GPT): pytest (targeted and full) and eval cannot launch the shared Windows Python
  in this sandbox; do not substitute an interpreter or install dependencies. Tests/static review supplied;
  runtime gates and interactive Windows smoke remain for runner/Claude/Bro.
  Independent read-only GPT review found no blocker/major issue in queueing, pause sync, lifecycle races or
  edit preservation. Added a delayed-backend shutdown regression test; execution is still pending.

- 2026-10-20 — T-105 (GPT): actual webhook only in `recap.json` via existing secretstore (DPAPI on Windows;
  same base64/0600 fallback elsewhere). TOML key is empty/ignored; GET/POST return only `has_webhook`.
  Empty Settings input preserves the secret; explicit clear disables it. Atomic file replacement protects concurrent reads.
- 2026-10-20 — T-105 (GPT): episode auto titles and meeting subjects derive from captured strings, so use generic
  numbered labels until explicitly renamed; drop locked titles repeating captured commands/window titles/subjects,
  then re-redact and strip Markdown syntax. Reuse recap SOP/Delivery thresholds, at most 15 items/section and 100 chars/title.
  No document link: card contract restricts outbound data to titles/times; local-only URLs are not useful to channel members.
  GPT static review found a whitespace bypass: comparison now normalizes whitespace/case across the entire day's capture.
  Locked titles include manual and AI-renamed titles; all heuristic titles remain generic. Regression test added;
  static reviewer approved, runtime verification is still pending the runner.
- 2026-10-20 — T-105 (GPT): automatic recap gate alone dispatches Teams (including yesterday catch-up/revision);
  manual recap does not send. Snapshot before daemon thread avoids cross-thread SQLite; 10s timeout per attempt,
  one immediate retry, no redirects or durable retry queue. A timeout can duplicate a card; shutdown may interrupt it.
  HTTPS required except loopback fake servers. T-105 explicitly authorizes this opt-in outbound integration beyond
  the prior LLM-only privacy rule; LocalOnly is unchanged. Tenant webhooks requiring OAuth are outside this card.

- 2026-10-20 — T-106 (Claude): the hook reads `[capture] shell_output(_lines)` from config.toml with a tiny line-based
  TOML reader when the shell starts (no Python call per shell → no startup cost); changes need a new PowerShell window.
  Ingest enforces the opt-in too: `data.output` from any producer is dropped unless `shell_output = true`, and cut to
  `shell_output_lines` (the hook also cuts, so raw output never reaches the inbox in full).
- 2026-10-20 — T-106 (Claude): the transcript is read from a byte offset that advances on *every* prompt (also empty
  Enter / paused), ≤ 64 KB per command; the leading `PS …> <cmd>` echo is dropped by matching the command's first
  line in the first 5 lines. Transcripts hold raw output, so they are deleted on `exit` (`PowerShell.Exiting`) and
  files > 12 h old are removed at the next shell start (a live shell keeps its file locked).
  Round 2 (GPT review, supersedes "transcript keeps running while paused"): privacy wins over the nested-transcript
  edge case — a shell started paused never starts the transcript; once the flag exists the next prompt stops it,
  deletes the file and discards that prompt's output; the first prompt after resume starts a new file
  (`-<n>` suffix: a just-deleted path can still be pending delete, and PS 5.1 may create the file lazily, so the
  read offset `-1` means "skip the `*****` header first"). Known limit: if the user started their own transcript
  after ours, `Stop-Transcript` on pause stops theirs (PowerShell has no API to stop a specific transcript).
- 2026-10-20 — T-106 (Claude): redaction now runs on output that may be cut mid-block, so the PEM pattern also masks a
  `BEGIN … PRIVATE KEY` with no END up to the end of the string; `key=value` now matches env-style prefixes
  (`SPLUNK_PASSWORD=`, `DB_API_KEY:`) because printed .env/config files are the most likely secret in output.
  Round 2 (GPT review): the hook cuts lines at 400 chars, which can drop a closing quote; `_QUOTED_OR_WORD` now also
  matches an unterminated quote up to the end of the line (over-masks rather than leaks), and `AccountKey=` etc.
  accept an opening quote. Fixed in the redactor (not the hook) so every producer benefits.
- 2026-10-20 — T-106 (Claude): source pack shows ≤ 15 output lines per command (card), `    │ ` prefix inside the
  existing ```text block; the daily worklog and AI-title prompts stay command-only. Output is not added to event
  `text` (search/timeline) to keep the timeline compact. Eval gets a deterministic `[case.pack] must_contain` check so
  CI (no LLM) proves output-only values reach the pack; `--llm` adds `must_mention`.
- 2026-10-20 — T-104 (GPT): Keep stdlib-only SSE adapters and the existing synchronous generation path;
  POST fetch streaming retains X-OpsTrail protection. Save only after provider terminal success, emitting
  one `done` with the saved draft + fact-check. Failed streams emit a generic/safe error without upstream
  bodies (which may echo keys/prompts); incomplete or empty drafts are never saved. No automatic retry,
  since a disconnected client may miss a final event after the server has already saved.
  Read-only Codex review caught permissive stop-reason handling; successful reasons are now allowlisted,
  with regression cases for filtering/refusal and unknown reasons so partial answers cannot be saved.
  Codex follow-up review approved the fix; Claude cross-review and the runner's Python gates are pending.
- 2026-10-20 — T-104 (GPT): difflib compares lossless Latin words/Thai combining clusters in service.py;
  the two-column UI expands highlights to Thai dictionary word boundaries with built-in Intl.Segmenter,
  falling back to cluster highlights on older browsers. This avoids a new Thai dictionary dependency.
  Editor controls and navigation lock during streaming so saves/version changes cannot race the live text.
- 2026-10-20 — T-104 (GPT): Playwright smoke uses only synthetic local API fixtures, including delayed SSE,
  and an already-installed browser; it covers the real SPA but is not a Python integration test. Python
  pytest/eval commands were attempted and fail at process creation in this sandbox; runner gates remain required.
- 2026-10-20 — Structured capture (commands/windows/notes/screenshots) instead of screen recording: cheaper,
  searchable, less sensitive. Screenshots only on hotkey or configured title patterns.
- 2026-10-20 — No fine-tuning: templates + examples (few-shot). v0.1: only the MCP client's model writes.
  v0.2 (Bro: "won't always use Claude Desktop, a web page is easier"): local web UI with optional providers
  (Claude API / OpenAI-compatible / Azure OpenAI), chosen in Settings; copy/paste prompt as no-key fallback.
- 2026-10-20 — Web UI is localhost-only for a single user (Bro's choice); team access belongs to team mode.
- 2026-10-20 — Producers write to an inbox (JSONL/TSV) and only ingest touches SQLite → hooks stay trivial
  and never block the shell; agent and MCP server can both ingest safely (atomic rename + content hash).
- 2026-10-20 — Episodes are assigned incrementally and IDs never change, so doc sessions can reference them.
- 2026-10-20 — Support both mcp SDK 1.x and 2.x (2.x renamed FastMCP → MCPServer).
- 2026-10-20 — Windows hotkeys via RegisterHotKey instead of a global keyboard hook (pynput): no keylogging,
  EDR-friendly, works when elevated windows have focus. pynput only on Linux/macOS.
- 2026-10-20 — `refresh()` is serialised with a cross-process file lock (agent + several MCP server processes).
- 2026-10-20 — No M365 connection yet (Bro): meetings come from window titles + a post-meeting summary prompt;
  Graph (calendar/transcripts) is T-109, blocked on approval. No audio recording of meetings.
- 2026-10-20 — Collaboration via GitHub PRs with CI + cross-review; golden-day evals decide disagreements.
- 2026-10-20 — Bro: limited API credit, no time to approve anything → development runs on the Claude / ChatGPT
  subscriptions through the Claude Code and Codex CLIs, driven by `scripts/duo.ps1`. The runner (not the agents)
  commits, gates and merges; merge needs gate green + APPROVE from the *other* model + CI. Claude runs with
  `--permission-mode dontAsk` + allow/deny files (deterministic, no classifier); Codex with `--full-auto`
  (fallback: full access inside the worktree when the Windows sandbox is unavailable), reviewer read-only.
- 2026-10-20 — T-102 (Claude): background meeting presence is a normal `window` event with `data.presence = true`
  (no new event type, schema stays v1). It counts as meeting activity but is excluded from focus/active time
  (`events.is_focus_window`) so screen-sharing time is not counted twice.
- 2026-10-20 — T-102 (Claude): presence segments are flushed every 5 min, so commands typed during the call can be
  grouped into a work episode before the meeting span covers them. Instead of flushing presence on every refresh
  (many tiny events), a meeting that grows takes those events back from `auto` episodes (`_reclaim_for_meetings`).
  This relaxes "events never move" for un-renamed, un-referenced auto episodes only; an emptied one is deleted.
- 2026-10-20 — T-102 (Claude): presence is recorded only while the user is active (not idle/paused), as the card
  says — a forgotten open meeting window must not create an all-night meeting. Listening without touching the
  mouse for > `idle_threshold_s` still ends the segment (unchanged behaviour). Not on Linux/macOS (`top_level_windows`
  returns `[]`).
- 2026-10-20 — T-102 round 2 (Claude, after GPT review): a meeting attended only in the background (foreground
  excluded/none) has `active_s = 0` — presence proves the call was open, not that the user was working, and it may
  overlap focus time kept in a protected episode. The episode's start/end still span the call. A short call inside
  continuous work still leaves the before/after work in one auto episode (rule 3, gap < `idle_split_min`); only the
  focus segments are cut at the call boundaries.
- 2026-10-20 — `test_hotkey_parse_and_match` failed on every Windows run (it read the real keyboard via
  `GetAsyncKeyState`); the test now stubs `_current_mods`. Test-only change, no behaviour change.
