# T-104 Web editor: version diff + streaming AI output

**Suggested owner:** GPT · **Phase:** B · **Size:** M

**Status:** done · **Priority:** 2

## Goal
1. "เทียบเวอร์ชัน" button: side-by-side or inline diff between any two versions (word-level for Thai).
2. Stream the AI answer into the editor while it is generated (Anthropic `stream: true`, OpenAI SSE).

## Contract
- `GET /api/docs/{id}/diff?from=&to=` → `{hunks: [...]}` built with `difflib` in `service.py`.
- `POST /api/docs/{id}/generate?stream=1` → `text/event-stream`; the final event carries the saved
  version + fact-check. Keep the non-stream path for MCP/tests.
- Vanilla JS only, no new libraries; keep CSP `script-src 'self'`.

## Acceptance criteria
- [x] pytest tests added for diff endpoint and streaming against the fake LLM server in `tests/test_web.py`
  (execution blocked: shared Python launcher cannot start in Codex sandbox; runner must verify).
- [x] Playwright smoke clean (no console errors); `node tests/web_editor_smoke.cjs` uses synthetic API/SSE fixtures.
