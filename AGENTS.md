# AGENTS.md — instructions for AI coding agents (Claude, GPT/Codex, Copilot)

This repo is built **jointly by Claude and GPT** for Bro (Security Engineer, Sysware / MSSP).
Read this file and `SPEC.md` before changing anything. `docs/HANDOFF.md` is the shared task board.

## What OpsTrail is

A background recorder + MCP server that turns a team's real ops work (shell commands, focused windows,
notes, screenshots) into documents: Daily worklog, SOP, Delivery doc, Guide. The AI client (Claude Desktop,
VS Code Copilot/GPT, Claude Code, Codex) writes the prose; OpsTrail supplies facts, templates and versioning.

## Repo map

```
SPEC.md                    architecture, event schema v1, MCP contract  ← the contract, keep it current
src/opstrail/
  config.py                config.toml defaults + paths (~/.opstrail, $OPSTRAIL_HOME)
  events.py                event schema: make/normalize/parse_ts/tsv/write_inbox
  redact.py                secret redaction (applied before anything is stored)
  ingest.py                inbox (*.jsonl / *.tsv) -> SQLite, atomic claim by rename
  store.py                 SQLite: events, episodes, doc_sessions, doc_sources, doc_versions, kv, FTS
  episodes.py              incremental grouping of events into episodes (work items)
  render.py                source-pack / timeline formatting
  recap.py                 deterministic daily worklog
  templates.py             templates/<name>/{template.toml, skeleton.md, guide.md, examples/, reference.docx}
  export.py                markdown -> .md (+assets) and .docx (python-docx, Thai fonts)
  service.py               OpsTrail facade used by MCP, CLI and agent  ← business logic lives here
  mcp_server.py            MCP tools/resources/prompts (mcp SDK v1 FastMCP and v2 MCPServer)
  web/app.py               local web UI: Starlette JSON API + LocalOnly security middleware
  web/static/              index.html, app.js (vanilla JS SPA, Thai UI), app.css – no CDN, no build step
  llm.py                   optional LLM providers for the web "AI write" button (stdlib HTTP only)
  secretstore.py           DPAPI protection for the stored API key
  locks.py                 cross-process file lock used by refresh()
  activity.py              activity classifier (rules in data/activity_rules.toml + ~/.opstrail override)
  quality.py               learn-from-edits diffs, style lessons, deterministic fact-check
  evals.py                 golden-day evaluation harness (`opstrail eval`)
evals/                     golden-day fixtures (days/*.jsonl) + expectations (cases.toml) — the referee
docs/tasks/                task cards (T-xxx, "**Status:** todo · **Priority:** n") → picked up by scripts/duo.ps1
scripts/duo.ps1            duo autopilot: Claude Code + Codex build/review task cards unattended (docs/COLLABORATION.md)
scripts/duo/               prompts (build/review/fix) + Claude permission files used by duo.ps1
  cli.py                   `opstrail` command
  agent/                   capture agent: daemon loop, winapi (ctypes), hotkeys, screenshot, tkinter popups
hooks/                     PowerShell / bash+zsh / Claude Code hooks that write to the inbox
templates/                 document templates (Thai)
scripts/install.ps1        Windows installer (venv, profile hook, startup, Claude Desktop, VS Code files)
setup/vscode, setup/github source of .vscode/*.json and .github/ (installer / init-github copy them)
setup/claude, setup/codex  source of .claude/settings.json and .codex/config.toml (duo.ps1 -Setup copies them);
                           edit the files in setup/ so the next install keeps your change
tests/                     pytest suite (runs on Linux CI without a display)
```

## Commands

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File scripts\install.ps1   # first time
.venv\Scripts\python -m pytest -q                               # must stay green
.venv\Scripts\python -m opstrail doctor
```
```bash
# Linux/macOS (dev/CI)
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" && pytest -q
```

## Rules

1. **SPEC.md is the contract.** Changing the event schema, MCP tool names/params or storage layout →
   update SPEC.md in the same change. Event schema changes must stay backward compatible (bump `v` if not).
2. **Business logic goes in `service.py`** (or a module it calls). `mcp_server.py` and `cli.py` stay thin.
3. **Every captured string passes through `redact`** (use `ingest.store_event` / `OpsTrail.record`,
   never insert raw rows). Never log raw commands to the agent log.
4. **Windows first.** Python ≥ 3.10. No pywin32 – use ctypes. Keep `.ps1` files ASCII-only
   (Windows PowerShell 5.1 reads BOM-less files as ANSI). Quote paths: the repo lives under
   `C:\Users\Lenovo X1 Gen 9\Downloads\MCP Doc\OpsTrail` (spaces!).
5. **MCP SDK compatibility:** code must run on `mcp` 1.x (FastMCP) and 2.x (MCPServer). Tools return `str`.
   User-facing errors raise `OpsTrailError` (converted to MCP `ToolError`).
6. **Tests + eval:** add/adjust tests for every behaviour change; `pytest -q` and `opstrail eval` must pass and
   the eval score must not drop. When you fix a grouping/classification bug, add a golden-day case first.
   Windows-only behaviour gets a test in `tests/test_windows.py` (runs on the CI Windows runner). Agent code is tested with
   fake OS functions (see `tests/test_agent.py`); never require a display in tests.
7. **Dependencies:** keep them light (currently mcp, python-docx, mss, psutil; pynput only on Linux/macOS).
   Never add a global keyboard hook on Windows – hotkeys use `RegisterHotKey`. Ask in HANDOFF before adding deps.
8. **Docs/UX language:** user-facing text (templates, popups, README) in Thai with English technical terms;
   code, comments, commit messages in English.
9. **Privacy:** local-first. No telemetry. The only outbound call is the user-configured LLM provider when
   they press "AI write". The web UI binds to 127.0.0.1 and keeps the `LocalOnly` middleware (Host check,
   `X-OpsTrail` header for writes, CSP) – never loosen it. The HTTP MCP transport must bind to 127.0.0.1 unless
   a token is configured. Never return API keys from any endpoint.
10. **Web UI:** vanilla JS only (no framework, no CDN, no inline scripts – CSP is `script-src 'self'`).
   All user/AI text is HTML-escaped before rendering (see `esc()` / `renderMd()` in app.js).

## Claude ↔ GPT collaboration protocol

The repo is https://github.com/TeerapatBM/OpsTrail — one task card = one branch = one PR. Normally
`scripts/duo.ps1` drives it: card owner builds, the other model reviews, CI (Windows + Linux) gates the merge.
Everything runs on Bro's Claude / ChatGPT subscriptions – never add code that needs an API key for development.
Full workflow: `docs/COLLABORATION.md`.

- `docs/HANDOFF.md` has the backlog. **Claim** a task by writing `[claimed: <agent> <date>]` next to it before
  you start; when done, move it to *Done* with a 1–3 line summary + files touched.
- One task per PR. Commit prefix: `[claude]`, `[gpt]`, `[copilot]`, `[duo]` (runner) or `[bro]`.
- Don't silently rewrite another agent's design: add an entry to the *Decision log* in HANDOFF explaining why.
- After finishing a task, add a **Review request** line for the other agent; the reviewer answers in HANDOFF.
- If something in SPEC.md looks wrong, propose the change in HANDOFF first unless it is a clear bug.

## Unattended runs (scripts/duo.ps1)

Most of the time you are started by `scripts/duo.ps1` with no human watching. Then:

- You work in a git worktree on branch `duo/T-xxx`; PYTHONPATH, TEMP and OPSTRAIL_HOME are set for you.
  Use the shared venv python the prompt names; do not create venvs or pip install.
- Do **not** commit, push, merge, switch branches or call `gh` – the runner commits each round, runs the gate
  (pytest + eval) itself, asks the other model to review, and merges only when both are green.
- Builder: finish with the `SUMMARY / CHANGES / TESTS / OPEN` block. Reviewer: stay read-only and end with
  `VERDICT: APPROVE` or `VERDICT: CHANGES` (only blockers/majors justify CHANGES).
- Nobody can answer questions: decide, record the decision in HANDOFF's Decision log, list leftovers under OPEN.
- When a card is impossible to finish here (needs hardware, an account, an approval), implement what you can
  behind a graceful fallback and say so under OPEN – the PR then goes to Bro as `needs-bro`.

## Dogfooding

`.vscode/mcp.json` (from `setup/vscode/`) registers the OpsTrail MCP server for VS Code chat, so agents working in this repo can
call `list_episodes`, `daily_recap`, `start_doc_session` … against Bro's real data. Treat that data as
confidential customer information: never paste it into commits, issues or tests.
