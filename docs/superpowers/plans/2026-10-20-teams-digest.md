# Teams digest implementation plan

**Goal:** Implement T-105 using stdlib HTTP and the existing secretstore, without dependencies.
**Spec:** `docs/tasks/T-105-teams-digest.md`, SPEC sections 3, 6, 7b, 8.
**Execution:** Inline, unattended; runner owns commits and Claude cross-review.

- [x] Write fake-webhook tests for Adaptive Card 1.4, privacy, retry, safe errors, opt-out and nonblocking dispatch; Settings tests for secret preservation/removal and CSRF.
- [x] Add `teams.py` for secret settings, safe title projection, bounded card construction and HTTP delivery. Expose service methods; only automatic agent recap dispatches a daemon thread with a data snapshot (no SQLite use in worker).
- [x] Add Settings controls and `/api/recap/settings` GET/POST; default `teams_webhook_url` stays empty in TOML, actual value only in protected `recap.json`.
- [x] Update SPEC, Thai README, card and HANDOFF; attempt full pytest and eval with shared Python.

Execution ledger: shared Python failed at process creation for targeted pytest, full pytest and eval
("The file cannot be accessed by the system"). Runtime red/green cycle is unverified; runner must run gates.
Node syntax and git whitespace checks passed. Read-only GPT reviewer found no blocker/major;
applied its whitespace-normalization privacy hardening with a cross-episode regression test.

Review focus: generated titles can contain commands/window titles (replace with generic titles); corrupt secrets fail closed; redirects must not forward payload; retry is exactly once with bounded timeout and safe logs; recap repeats must follow the existing recap_done gate. Real Teams tenant smoke is outside this environment.
