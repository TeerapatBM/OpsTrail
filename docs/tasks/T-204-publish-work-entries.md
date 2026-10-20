# T-204 Publish work entries: projection, preview, outbox, sync, Hub ingest

**Suggested owner:** Claude (reviewer GPT) · **Phase:** C · **Size:** L · **Blocked by:** Bro's approval of `docs/team-mode.md`, T-202, T-203

**Status:** blocked · **Priority:** 23

## Goal
An engineer sends this week's episodes as work entries after seeing exactly what leaves the laptop; nothing else
is ever uploaded. Design: `docs/team-mode.md` §6.1, §6.3, §7.

## Contract
- `src/opstrail/team/projection.py`: deterministic `project_episode()` → only the fields of design §6.1;
  `redact_obj` incl. extra patterns; warnings (auto title not confirmed, `[REDACTED]` present). The previewed
  payload and its SHA-256 are what is queued — no recomputation at send time.
- Additive local tables `team_outbox`, `team_items`; sync worker thread in the agent (every `sync_interval_min`
  and after a submit, backoff 1/5/15/60 min, never blocks capture); `GET /v1/me/items?since=` updates local states.
- Hub: `PUT /v1/items/{uuid}` (kind `work`): strict schema, field limits, owner fixed, idempotent on
  `(uuid, sha256)`, 409 for a different payload with the same rev, **Hub-side `opstrail.redact` again**;
  `DELETE` = withdraw. The notice gate (428) may be a stub until T-209.
- Submit only from the web UI ("ส่งงานสัปดาห์นี้" + preview dialog) and CLI `opstrail team submit --episode`;
  **no MCP submit tool**.

## Acceptance criteria
- [ ] test: the payload of an episode full of commands / window titles / URLs contains none of them
- [ ] test: a "modified client" sending a token in `summary` is redacted by the Hub
- [ ] outbox retry/offline tests with a fake Hub; idempotency and 409 tests
- [ ] SPEC / README (Thai) updated
