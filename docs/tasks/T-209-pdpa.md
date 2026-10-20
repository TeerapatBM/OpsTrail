# T-209 PDPA: notice + acceptance, export, erasure, retention, PII check, restricted customers

**Suggested owner:** Claude (reviewer GPT) · **Phase:** C · **Size:** L · **Blocked by:** Bro's approval of `docs/team-mode.md`, DPO/legal review of its §10 + Appendix A, T-204

**Status:** blocked · **Priority:** 28

## Goal
Team mode meets the PDPA design of `docs/team-mode.md` §10 before the whole team joins.

## Contract
- Notice: versioned Thai text in Hub settings (admin); `GET /v1/me` reports the required version; writes return
  428 until `POST /v1/me/notice`; the local web UI shows the notice on first sign-in and on each new version.
- `GET /v1/me/export` (zip of own items, revisions, reviews, audit entries; Thai field descriptions).
- `POST /v1/me/erase` + admin `POST /v1/admin/users/{oid}/offboard`: pseudonymize identity, delete
  pending/rejected items, keep approved entries/docs pseudonymized (design §10.3); legal hold
  `POST /v1/admin/items/{uuid}/hold` blocks withdraw and retention.
- Daily retention job with the defaults of design §10.5 (configurable), counts audited; local
  `[retention] raw_days = 180` purge of raw events + screenshots by the agent (documents kept).
- PII check (Thai national ID with checksum, Thai mobile numbers, personal e-mail addresses) as preview warnings
  and Hub reviewer flags; `[team] block_pii = true` makes it blocking.
- Restricted customers: the `groups` claim filters KB, reviews and reports (group overage > 200 → no restricted
  access + a Thai hint).

## Acceptance criteria
- [ ] tests for each right (export content, withdraw, erase/pseudonymize, legal hold) and retention with a fake clock
- [ ] local retention test (events/screenshots older than `raw_days` gone, doc sessions kept)
- [ ] PII detector tests incl. a 13-digit number with a wrong checksum (no warning)
- [ ] SPEC / README (Thai) updated; the notice text is the DPO-approved version
