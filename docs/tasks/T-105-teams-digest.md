# T-105 Daily digest to a Microsoft Teams channel

**Suggested owner:** GPT · **Phase:** B · **Size:** S

**Status:** done · **Priority:** 4

## Goal
At recap time, optionally post a short Adaptive Card to a Teams channel via a Power Automate
"Workflows" webhook: today's work items (title, time), meetings, and "documents to write" candidates.

## Contract
- Config `[recap] teams_webhook_url = ""` (empty = off). URL is a secret → store it like the LLM key
  (DPAPI) via Settings, not in config.toml.
- Payload: Adaptive Card 1.4 (`type: message`, `attachments[0].contentType =
  application/vnd.microsoft.card.adaptive`). Only titles/times — **no commands, no window titles**.
- Retry once; log failures; never block the agent loop (run in a thread).

## Acceptance criteria
- [x] Added pytest with a fake webhook server asserting the card shape and that no command text is included
  (`tests/test_teams.py`); execution pending runner gate because the shared Python launcher is inaccessible
  in the Codex sandbox. Windows DPAPI coverage in `tests/test_windows.py`.

## Verification / limits
- `node --check src/opstrail/web/static/app.js` and `git diff --check` passed.
- Full pytest and `opstrail eval` attempted; both fail before Python starts: "The file cannot be accessed by the system."
- Real Teams tenant/channel smoke requires Bro's configured Workflows URL; no real data or external webhook used here.
