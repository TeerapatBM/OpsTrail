# T-201 Team Hub skeleton: store, API frame, authorization + audit log

**Suggested owner:** Claude (reviewer GPT) · **Phase:** C · **Size:** L · **Blocked by:** Bro's approval of `docs/team-mode.md`

**Status:** blocked · **Priority:** 20

## Goal
A runnable `opstrail hub serve` with the Hub data model, the permission matrix and the audit log in place, so the
following cards only add features. Design: `docs/team-mode.md` §3, §4 (matrix), §7, §8, §11.

## Contract
- New package `src/opstrail/hub/`: `config.py` (`hub.toml`), `store.py` (SQLite WAL, tables of design §7, additive
  migrations, portable SQL), `authz.py` (one `authorize(user, action, item)`, deny by default), `audit.py`
  (append-only, SHA-256 hash chain + `verify()`), `app.py` (Starlette, `/healthz`, `/v1/me`, JSON errors, body
  size limits, per-user rate limits), `auth.py` with a pluggable token verifier (a **fake verifier for tests**
  only; Entra validation is T-202). Business logic in a `HubService`; routes stay thin.
- CLI `opstrail hub serve|init|verify-audit` (thin).
- Binds `127.0.0.1:8770` by default; refuses to start without `tenant_id`/`audience` unless `--dev`.
- No new dependencies (Starlette/uvicorn come with `mcp`).
- SPEC.md: new section "Team Hub" (storage layout, routes so far).

## Acceptance criteria
- [ ] route × role matrix test that walks **every** registered route (fails when a new route has no rule)
- [ ] audit chain test (tampered row detected); `/healthz` reveals nothing; oversize body → 413; rate limit → 429
- [ ] tests run on Windows + Linux without any database server; `pytest` and `opstrail eval` green
