# HANDOFF — shared task board (Claude ↔ GPT ↔ Bro)

Protocol: see `AGENTS.md`. Claim with `[claimed: <agent> <YYYY-MM-DD>]`, move to *Done* with a summary.

## Status — v0.3.0 (2026-10-20, built by Claude)

v0.3 (Phase A): activity classifier (rules TOML), meetings as their own episodes with exact times +
post-meeting summary popup, notes attach to what just ended, `meeting-minutes` template, profile name
(fixes "Lenovo X1 Gen 9" as author), learn-from-edits + style lessons, deterministic fact-check after every AI
draft, AI episode titles, golden-day eval harness (`opstrail eval`), GitHub kit (CI on Windows/Linux incl.
PowerShell 5.1 checks + Windows-only tests, Claude PR review, Copilot setup steps, PR/issue templates,
`scripts/init-github.ps1`), task cards T-101…T-110. Tests: 91 (+5 Windows-only).
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

0. [ ] **Push to GitHub** (`scripts/init-github.ps1 -CreateIssues`) + add `ANTHROPIC_API_KEY` secret — _owner: Bro_
- T-101 browser extension (GPT) · T-102 meeting presence while screen sharing (Claude) · T-103 voice note (GPT)
- T-104 web diff + streaming (GPT) · T-105 Teams digest (GPT) · T-106 PowerShell output capture (Claude)
- T-107 cross-model reviewer "ให้ AI ตรวจ" (GPT) · T-108 tray icon (GPT) · T-109 M365 connector (Claude, blocked: M365 approval)
- T-110 team-mode design (Claude → reviewed by GPT)

Older backlog items (kept for reference):

1. [ ] **Windows smoke test** on Bro's laptop (partly done 2026-10-20: install, agent, web, DPAPI OK — still to check
   hotkeys/popups/screenshots/PowerShell hook over a full day): run `scripts/install.ps1`, `opstrail doctor`, use hotkeys for
   an hour, check `opstrail timeline` / `episodes`, ask Claude Desktop + Copilot for a daily recap. Fix what breaks.
   _owner: Bro + any agent_
2. [ ] **Import the team's real document formats** (Bro will provide a folder): put good examples into
   `templates/<type>/examples/`, company Word template as `reference.docx`, adapt `skeleton.md` / `guide.md`.
3. [ ] **Teams digest** at recap time: optional `[recap] teams_webhook_url` (Power Automate Workflows webhook),
   post a short Adaptive Card with today's work items + link to the doc. _suggested: GPT_
4. [ ] **PowerShell output capture** (opt-in): `Start-Transcript` per session, attach the first N lines of output
   to each shell event for "expected result" sections in SOPs. _suggested: Claude_
5. [ ] **Tray icon** (pystray): status, pause/resume, open today's recap, open exports folder. _suggested: GPT_
6. [ ] **Better episode titles** using MCP sampling (ask the client model for a 6-word title) with fallback
   to the current heuristic.
7. [ ] **Remote SSH capture**: helper to pull `~/.opstrail/inbox/*.tsv` from servers where the bash hook is
   sourced, or wrap `ssh` with `script` logging.
8. [ ] **Browser URL capture** via UI Automation (Edge/Chrome address bar) — opt-in, respect exclusions.
9. [ ] **Web UI polish**: streaming AI output, diff view between versions, drag-drop images into docs,
   per-section "rewrite this section" button. _suggested: GPT_
10. [ ] **ChatGPT (web/desktop) as an MCP client**: expose HTTP MCP through Cloudflare Tunnel with OAuth
   (lower priority now that the web UI + copy/paste covers ChatGPT).
11. [ ] **Team mode (v0.3)**: central server (Postgres), per-user auth, cloud audit-log collectors
    (Azure Activity/Entra, Alibaba ActionTrail, vCenter), web review UI, SharePoint publishing.

## Done

- v0.1.0 initial implementation — Claude, 2026-10-20 (all files).
- v0.2.0 local web UI + LLM providers — Claude, 2026-10-20 (`web/`, `llm.py`, `secretstore.py`, service web helpers).
- v0.3.0 Phase A quality loop — Claude, 2026-10-20 (`activity.py`, `quality.py`, `evals.py`, episodes meetings, web, setup/github, docs/tasks).

## Review requests

- [ ] GPT: review `src/opstrail/episodes.py` grouping heuristics and `export.py` markdown→docx edge cases.
- [ ] GPT: review `web/static/app.js` (renderMd escaping, editor dirty-state) and `web/app.py` LocalOnly middleware.

## Decision log

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
