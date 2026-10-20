# T-104 Web editor: version diff + streaming AI output

**Suggested owner:** GPT · **Phase:** B · **Size:** M

## Goal
1. "เทียบเวอร์ชัน" button: side-by-side or inline diff between any two versions (word-level for Thai).
2. Stream the AI answer into the editor while it is generated (Anthropic `stream: true`, OpenAI SSE).

## Contract
- `GET /api/docs/{id}/diff?from=&to=` → `{hunks: [...]}` built with `difflib` in `service.py`.
- `POST /api/docs/{id}/generate?stream=1` → `text/event-stream`; the final event carries the saved
  version + fact-check. Keep the non-stream path for MCP/tests.
- Vanilla JS only, no new libraries; keep CSP `script-src 'self'`.

## Acceptance criteria
- [ ] pytest for diff endpoint and for streaming against the fake LLM server in `tests/test_web.py`
- [ ] Playwright smoke still clean (no console errors)
