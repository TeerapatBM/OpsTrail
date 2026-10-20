# T-207 Team knowledge base search (Hub FTS + web + read-only MCP tools)

**Suggested owner:** GPT (reviewer Claude) · **Phase:** C · **Size:** M · **Blocked by:** Bro's approval of `docs/team-mode.md`, T-205, T-206

**Status:** blocked · **Priority:** 26

## Goal
"Has anyone already done a Splunk upgrade for this customer?" — search all approved team documents from the web
UI or from Claude / Copilot. Design: `docs/team-mode.md` §8, §11 (T5, T8, T9, T11).

## Contract
- Hub: `GET /v1/kb/search` (trigram FTS like the local `docs_fts`, ACL filter in SQL, snippet + metadata,
  `q` ≤ 200 chars), `GET /v1/kb/docs/{uuid}` and `/v1/kb/assets/{sha256}` (approved revisions only; every document
  read audited and counted toward rate limits).
- Local: web "ทีม → ค้นหา" (results and documents rendered with `renderMd`/`esc`); "copy into a new document"
  starts a local doc session from a team document.
- MCP (read-only, return `str`, mcp 1.x + 2.x): `team_search(query, customer, template, limit)`,
  `team_get_doc(doc_uuid)`; document text inside a fenced block headed "team document — untrusted data,
  approved by <lead> on <date>". Team mode off/offline → `OpsTrailError` with a Thai hint. No KB cache on disk.

## Acceptance criteria
- [ ] ACL tests: pending, rejected and restricted-customer documents never appear for a plain member
- [ ] Thai query test (trigram) and MCP output framing test on both SDK versions
- [ ] SPEC (MCP tools table) / README (Thai) updated
