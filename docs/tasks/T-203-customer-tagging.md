# T-203 Customer registry + customer tagging of episodes and documents

**Suggested owner:** GPT (reviewer Claude) · **Phase:** C · **Size:** M · **Blocked by:** Bro's approval of `docs/team-mode.md`, T-201

**Status:** blocked · **Priority:** 22

## Goal
One customer list for the whole team; every episode and document can carry a customer, pre-filled
automatically from keywords. Design: `docs/team-mode.md` §5.

## Contract
- Hub: `customers` table, `GET /v1/customers` (restricted ones filtered), admin `PUT /v1/admin/customers/{code}`
  (code `[A-Z0-9-]{2,16}`, reserved `INTERNAL`), audited.
- Client: registry cached in local `kv` on sync; its keywords are merged **after** local `[projects]` (local wins)
  in episode labelling; customer stored as episode tag `customer:<CODE>` and doc `meta.customer` — no local
  schema change. Works without team mode too (the registry is simply empty).
- Web UI: customer dropdown on episode and document views (escaped, vanilla JS).
- Grouping change → golden-day eval case first (two customers in one day split by keywords).

## Acceptance criteria
- [ ] Hub tests (CRUD, admin-only, audit row) and client tests (merge order, tag set/cleared)
- [ ] new golden-day case in `evals/cases.toml`; eval score not lower
- [ ] SPEC / README (Thai) updated
