# T-105 Daily digest to a Microsoft Teams channel

**Suggested owner:** GPT · **Phase:** B · **Size:** S

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
- [ ] pytest with a fake webhook server asserting the card shape and that no command text is included
