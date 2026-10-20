# OpsTrail Team mode — design (T-110)

**Status:** proposal, waiting for GPT review (PR comments) and Bro's approval · **Author:** Claude · 2026-10-20

No code here. When Bro approves, the cards `docs/tasks/T-201` … `T-210` change from `blocked` to `todo`
and `scripts/duo.ps1` builds them in Priority order (see §13).

## สรุปสำหรับ Bro (TL;DR)

- **ข้อมูลดิบไม่ออกจากเครื่อง** — command, window title, URL, output, screenshot ที่ไม่ได้อยู่ในเอกสาร ยังอยู่ใน
  `~/.opstrail` เหมือนเดิม สิ่งที่ขึ้น server มีแค่สิ่งที่เจ้าของงาน **กดส่งเองหลังดู preview**: (1) *work entry*
  ของ episode (ชื่องาน ลูกค้า เวลา นาทีที่ทำ สรุปสั้น) และ (2) *เอกสาร* final + รูปที่อยู่ในเอกสาร
- **OpsTrail Hub** = server กลางตัวเดียว (Python/Starlette ใน repo นี้ + SQLite) วางในเครือข่ายบริษัท / VPN
  ใช้ **Entra ID SSO**; role `member / lead / admin` มาจาก app role ใน Entra (ไม่มีระบบ user/password ของเราเอง)
- lead **อนุมัติ** ก่อนเอกสารเข้า knowledge base และก่อน work entry นับเป็น man-day
- ได้: ค้นเอกสารทั้งทีม (web + MCP `team_search`), weekly report, man-days ต่อลูกค้า, PDPA (ประกาศ, ยอมรับ,
  retention, export/ลบข้อมูลตัวเอง), audit log
- ต้องให้ Bro ตัดสิน: ดู §14 (ที่วาง server, dependency ใหม่ 2 ตัว, นิยาม man-day, ระยะเวลาเก็บข้อมูล, ฝ่าย legal/DPO)

## 1. Goals and non-goals

Goals (from the card):

1. A **central server** ("Hub") that the team's OpsTrail installs publish to.
2. **Sync of approved items only** — nothing leaves a laptop unless its owner submitted it after a preview;
   nothing reaches the team knowledge base or the man-day totals unless a lead approved it.
3. **Entra ID SSO** for every call; roles **member / lead / admin**.
4. **Per-customer tagging** of episodes and documents (one customer registry for the whole team).
5. **Team knowledge base search** over approved documents (Thai-friendly).
6. **Weekly report** and **man-days per customer**.
7. **PDPA**: notice, acceptance, retention, export and deletion of one's own data.
8. A **threat model** with mitigations that become tests.

Non-goals for team mode v1 (each can get its own card later):

- Uploading raw events, timelines, window titles, URLs, command output or screenshots that are not in a document.
- Real-time activity dashboards, idle tracking, productivity scores or rankings of people.
- Co-editing a document by several people (one author per item; others comment through review).
- A separate hub web frontend. Everybody (incl. leads) uses their local OpsTrail web UI, which calls the Hub.
- Cloud audit-log collectors (Azure Activity/Entra, Alibaba ActionTrail, vCenter) and SharePoint/Confluence
  publishing from the old backlog item 11 — separate cards; SharePoint needs the same Graph approval as T-109.
- Multi-tenant hosting for other companies. One Hub = one Entra tenant (Sysware).

## 2. Principles

1. **Local-first stays the default.** `[team] enabled = false`; with team mode off nothing changes.
2. **Push, never pull.** The Hub never reaches into a laptop. Clients push submissions and poll their status.
3. **What you see is what is sent.** One deterministic projection function builds both the preview and the
   upload payload; the upload is the previewed bytes (hash-checked), not a re-computation.
4. **Redact twice.** The client re-runs `redact` (incl. `extra_patterns`) on the projection; the Hub runs the
   same `opstrail.redact` again on ingest (a modified client cannot skip it).
5. **Identity comes from Entra.** The Hub stores no passwords and no client secret (API-only, validates
   bearer tokens with Entra's public signing keys). Roles are Entra app roles.
6. **Every privileged action is audited** in an append-only, hash-chained log.
7. **Boring tech, same repo.** Hub = `src/opstrail/hub/` using Starlette/uvicorn (already installed with `mcp`),
   SQLite + trigram FTS (already used locally), tested on Windows and Linux CI like the rest.

## 3. Architecture

```
 laptop (each engineer)                                   Sysware network / VPN
 ┌─────────────────────────────────────────┐              ┌──────────────────────────────┐
 │ capture → SQLite (raw, local only)      │              │  OpsTrail Hub (API only)     │
 │      │                                  │   HTTPS +    │  opstrail hub serve          │
 │      ▼ episode / final doc              │  Entra token │  ┌────────────────────────┐  │
 │ submit dialog (preview) ──► team_outbox ├─────────────►│  │ authz (roles, customer)│  │
 │                                         │  PUT items   │  │ redact again, validate │  │
 │ local web UI "ทีม" ─┐                    │◄─────────────┤  │ hub.db (SQLite WAL)    │  │
 │ MCP team_search ────┴► hub client       │  GET status, │  │ kb_fts, assets/, audit │  │
 │ (MSAL token cache, DPAPI)               │  KB, reports │  └────────────────────────┘  │
 └─────────────────────────────────────────┘              └──────────────┬───────────────┘
                                                                         │ JWKS (public keys)
                                                              login.microsoftonline.com (Entra ID)
```

- The **browser never talks to the Hub.** The local web UI calls new local `/api/team/*` routes; the local
  Python process calls the Hub. `LocalOnly`, CSP `connect-src 'self'` and the loopback bind stay unchanged.
- The Hub URL comes only from `config.toml` (`https://` required, except loopback in tests); no request can
  choose another destination (no SSRF through the local server).
- The team KB is **read online, not replicated** to laptops. Laptops hold only their owner's data plus
  whatever document they open (no team-wide customer data cached on every machine).

### Why SQLite on the Hub (and not Postgres as the old roadmap said)

Write volume is tiny (a team of ≤ 50 submits a few items per person per day); one Hub process; the store code,
Thai trigram FTS and tests already exist for SQLite; and — important for how this repo is built — the duo
runner's gate on Bro's laptop and both CI runners can run every Hub test without a database server. Backups
are `sqlite3 .backup` (online) to encrypted storage. The Hub store module uses portable SQL and one connection
factory so a later Postgres port is mechanical. **Trigger to move:** > 50 active users, a need for more than one
Hub instance (HA), or a hosting platform without a reliable local disk (SQLite on SMB/Azure Files is not allowed).

## 4. Identity and roles (Entra ID)

### App registrations (done once by Sysware IT; guide = card T-202)

| registration | type | settings |
|---|---|---|
| **OpsTrail Hub API** | web API | Expose scope `Team.ReadWrite`; `accessTokenAcceptedVersion = 2`; app roles `OpsTrail.Member`, `OpsTrail.Lead`, `OpsTrail.Admin`; *Assignment required = Yes* (users without a role get no token) |
| **OpsTrail Desktop** | public client | Redirect `http://localhost` (MSAL loopback); delegated permission `Team.ReadWrite`; admin consent; no secret |

Roles are assigned to Entra **groups** (`OpsTrail-Members`, `-Leads`, `-Admins`; group assignment needs Entra ID
P1/P2 — otherwise assign users directly). Conditional Access (MFA, compliant device) applies to the Desktop app
like any other app — Sysware IT's choice, nothing in OpsTrail.

### Client sign-in

- `msal` public client, interactive auth code + PKCE in the system browser; device-code flow as fallback
  (`opstrail team login --device`). Started from the web UI button "เข้าสู่ระบบทีม" or the CLI.
- The MSAL token cache is serialized into the existing `secretstore` (DPAPI on Windows, 0600 elsewhere) as
  `~/.opstrail/team_token.json`. Access tokens are short-lived (Entra default ≈ 1 h); refresh is silent.
- `opstrail team logout` deletes the cache. Disabling the user in Entra stops access at the next token refresh.

### Hub token validation (every request except `GET /healthz`)

RS256 signature against the tenant JWKS (`https://login.microsoftonline.com/<tid>/discovery/v2.0/keys`, cached,
refetched on unknown `kid`, at most once per minute); `iss = https://login.microsoftonline.com/<tid>/v2.0`;
`tid` = configured tenant; `aud` = Hub API client id; `azp` ∈ `allowed_client_ids` (the Desktop app);
`scp` contains `Team.ReadWrite`; `exp/nbf` with 120 s leeway. Identity = `oid` (never `upn`/email, which can
change). `roles` → effective role = highest of admin ⊇ lead ⊇ member; no role → 403. Library: `PyJWT[crypto]`
(needs Bro's approval, §14). The validator is one module with a fake-JWKS test double.

### Permission matrix

| action | member | lead | admin |
|---|:-:|:-:|:-:|
| submit / update / withdraw **own** work entries and documents | ✓ | ✓ | ✓ |
| see own items, review comments, own weekly report, own man-days | ✓ | ✓ | ✓ |
| search / read **approved** KB documents (customers they may see, §5) | ✓ | ✓ | ✓ |
| export own data, request erasure | ✓ | ✓ | ✓ |
| review queue: approve / reject submissions (not their own) | | ✓ | ✓ |
| team weekly report, man-days per customer / per member, CSV | | ✓ | ✓ |
| remove an approved document from the KB | | ✓ | ✓ |
| customer registry, retention settings, legal hold, offboarding/erasure, audit log | | | ✓ |

Self-approval is blocked even for leads/admins (four-eyes); a one-person team can set
`allow_self_approval = true` in `hub.toml` (audited as such).

## 5. Customers and tagging

- **Customer registry** on the Hub (admin): `code` (`[A-Z0-9-]{2,16}`, e.g. `KBANK`), Thai/English `name`,
  `keywords` (same semantics as local `[projects]`), `active`, `visibility` (`team` | `restricted`),
  `access_group` (Entra group object id, only for `restricted`). Reserved code `INTERNAL` for internal work.
- Clients fetch the registry on sync (`GET /v1/customers`) and cache it in local `kv`. Its keywords are merged
  **after** the user's own `[projects]` (local labels win), so episodes are pre-labelled with a customer.
- Locally the customer is an episode tag `customer:<CODE>` (existing `episodes.tags`) and `meta.customer` on a
  doc session — **no local schema change**. Web UI: customer dropdown on the episode and document views;
  MCP `update_episode(tags=…)` already works.
- Submitting requires a customer (default suggestion = the episode's label; `INTERNAL` if none).
- `restricted` customers (customer contracts that forbid team-wide sharing): only members of `access_group`
  (from the token's `groups` claim, or a Graph lookup if the user is in > 200 groups) see their KB documents and
  man-days; submitting still works for anyone, the item is visible to its author and to leads in the group.
  v1 ships the column and filter; the Entra `groups` claim setup is card T-209.

## 6. What gets published

### 6.1 Work entry (from one or more merged episodes)

| field | source | note |
|---|---|---|
| `uuid` | client, random v4 on first submit | idempotency key; maps to the local episode in `team_items` |
| `date`, `start`, `end` | episode | local date (Asia/Bangkok), ISO times |
| `segments` | source episodes | `[[start, end], …]`, one per merged episode; the Hub rejects (409) a segment that overlaps another live work entry of the same owner |
| `active_min` | Σ episode `stats.active_s` | **the** captured time — see "Minutes" below |
| `meeting_min` | breakdown of `active_min` | the part of `active_min` spent in meetings; never added to it (`meeting_min ≤ active_min`, Hub 400 otherwise) |
| `claimed_min` | **user**, optional | what the user says they spent (offline work, calls); report shows captured vs claimed |
| `customer` | user (pre-filled) | registry code |
| `title` | user (pre-filled) | **must be confirmed**: auto titles come from window titles/commands (same concern as T-105) |
| `summary` | user, optional, ≤ 1000 chars | free text, not taken from notes automatically |
| `activities` | focus windows of the episode | minutes per activity class (`terminal`, `console`, `meeting`, …), no subjects; Σ ≤ `active_min` |
| `tags` | episode tags minus `customer:` | |
| `doc_uuids` | links to submitted documents | |

Not included: commands, cwd, window titles, URLs, subjects, notes, output, screenshots, host, timeline.

**Minutes — one wall-clock minute is counted once.** The projection never adds overlapping sources:

- `active_min` = Σ `round(stats.active_s / 60)` of the source episodes. `active_s` is focused-window time only;
  background meeting presence (`data.presence`) is **not** added, because it overlaps the focus windows of the
  same minutes (T-102: `episodes.py` counts presence once, `test_agent.py` asserts a 35-min screen-shared call has
  `active_s = 35 min`). Episodes never overlap (T-102 reclaims foreground work during a call into the meeting
  episode), and each local episode can belong to at most one work entry (`team_items` mapping; the client refuses
  a second submit, the Hub's `segments` overlap check catches a modified client).
- `meeting_min` ⊆ `active_min`: a meeting episode (`origin = meeting`, focused **or** screen-shared) → its whole
  `active_min` (the call, incl. foreground work while sharing); any other episode → its focused minutes classified
  `meeting`. A presence-only episode has `active_s = 0` (T-102) → 0/0; the user can enter `claimed_min`.
- `activities` is recomputed from focus windows only (the local `stats.activities` also counts presence segments
  and a 30 s weight per command, which overlap focus time — fine for titles, wrong for minutes).

### 6.2 Document

Only doc sessions with local status `final`. Payload: `uuid`, `template`, `title`, `customer`, `markdown`
(latest version, ≤ 1 MB), `local_version`, deterministic `fact_check` result (shown to the reviewer) and the
images it embeds. `shot://<id>` references become `asset://<sha256>`; each image is uploaded once,
content-addressed (`PUT /v1/assets/<sha256>`, PNG/JPEG by magic bytes, ≤ 5 MB, ≤ 30 per document).
Images cannot be text-redacted, so the preview shows every image with a required checkbox
"ตรวจแล้วว่าไม่มีรหัสผ่าน/ข้อมูลส่วนบุคคล". A changed local document is submitted as a new revision.

### 6.3 Submit flow (client)

1. User selects episodes ("ส่งงานสัปดาห์นี้" lists this week's unsubmitted episodes) or a final document.
2. `team.project_*()` builds the payload → `redact_obj` (incl. extra patterns) → optional PII check
   (§10.4) → **preview** of exactly these fields (escaped) with a warning list (auto title not edited,
   `[TODO` left in the document, fact-check findings, `[REDACTED]` occurrences, images).
3. Confirm → payload + its SHA-256 go to the additive local table `team_outbox`. The sync worker (agent thread,
   every `sync_interval_min` and right after a submit) sends it; failures back off (1, 5, 15, 60 min). Sync never
   blocks capture; offline is normal.
4. Local table `team_items(uuid, kind, local_ref, rev, state, approved_rev, last_comment, hub_updated_at,
   payload_sha256)` keeps the Hub state that the client pulls with `GET /v1/me/items?since=`. The local web UI shows
   "ส่งแล้ว / รออนุมัติ / อนุมัติแล้ว / ส่งกลับให้แก้ (+ความเห็น)".

Submission is a **human action only**: web UI or CLI. No MCP tool can submit — an AI client must not publish
customer data on its own. MCP gets read-only team tools (§8).

## 7. Hub data model and state machine

```
users(oid PK, display_name, upn, first_seen, last_seen, active, notice_version, notice_accepted_at, pseudonym)
customers(code PK, name, keywords JSON, active, visibility, access_group, created_at, updated_at)
items(uuid PK, kind 'work'|'doc', owner_oid, state, current_rev, approved_rev, legal_hold, created_at, updated_at)
work_revisions(uuid, rev, customer, payload JSON, sha256, submitted_at, PK(uuid, rev))
doc_revisions(uuid, rev, customer, template, title, markdown, local_version, assets JSON, fact_check JSON, sha256, submitted_at, PK(uuid, rev))
assets(sha256 PK, mime, size, path, uploaded_by, created_at)          -- files under <hub_home>/assets/aa/<sha256>
reviews(id PK, uuid, rev, reviewer_oid, decision 'approve'|'reject'|'remove', comment, created_at)
audit(id PK, ts, actor_oid, action, target, detail JSON, prev_hash, hash)
kb_fts(title, body, uuid UNINDEXED, rev UNINDEXED)  -- trigram; only approved_rev of approved docs
settings(key PK, value)              -- hours_per_manday, retention, allow_self_approval, notice text/version
```

```
            submit (rev n)                approve (lead, not owner)
  (none) ───────────────► submitted ───────────────────────────► approved ──┐
                             │  ▲ reject (+comment)                   │      │ new revision:
                             ▼  │                                     │      │ state=submitted,
                          rejected ── resubmit (rev n+1) ─────────────┘      │ approved_rev kept
  withdraw (owner, any state except legal hold) → content deleted, audit keeps uuid + action
  remove (lead/admin on approved doc) → out of KB, content kept for retention, owner notified
```

- An approved document stays visible in the KB at `approved_rev` while a newer revision waits for review.
- **The customer belongs to a revision, not to the item** (a new revision may retag it). Access is checked by one
  function, `can_read(user, item)`, used by every read path (KB search SQL filter, `/kb/docs`, `/kb/assets`,
  weekly report, man-days, review queue):
  - approved content (KB, reports) — the user must be allowed to see the customer of `approved_rev` **and**, while
    a newer revision is pending (`state = submitted`), the customer of that revision too. So retagging
    `RESTRICTED → team customer` exposes nothing before a lead approves it, and retagging `team → RESTRICTED`
    hides the old approved revision from non-group members at once (fail closed);
  - the review queue / pending content — the reviewer must be allowed to see the customers of `current_rev` and
    `approved_rev`; the owner always sees their own revisions;
  - `/kb/assets/{sha256}` — only if some approved revision the user can read references that asset (assets are
    content-addressed and may be shared between documents).
  Man-days and the weekly report attribute minutes to the customer of `approved_rev`.
- Work entries count in reports only at `approved_rev`. Leads approve a member's week in one action
  ("อนุมัติทั้งสัปดาห์") or item by item.
- PUT is idempotent on `(uuid, sha256)`; a different payload for an already-stored rev → 409. Unknown JSON
  fields → 400 (strict schema). Owner of an existing uuid is fixed; another user's PUT → 403.

## 8. Hub API v1 (JSON, `Authorization: Bearer`, base `https://<hub>/v1`)

| route | role | purpose |
|---|---|---|
| `GET /healthz` (no `/v1`) | none | `{ok}` only, no version/user info |
| `GET /me` | member | oid, name, role, groups-derived customers, notice status |
| `POST /me/notice` `{version}` | member | accept the privacy notice (required before any other write) |
| `GET /customers` | member | registry (restricted ones only if allowed) |
| `PUT /assets/{sha256}` | member | upload image bytes (hash verified) |
| `PUT /items/{uuid}` `{kind, rev, payload, sha256}` | member (owner) | submit / new revision |
| `DELETE /items/{uuid}` | member (owner) | withdraw |
| `GET /me/items?since=` | member | own items, states, review comments |
| `GET /review?customer=&kind=&member=` | lead | queue (excludes own) |
| `POST /review/{uuid}` `{rev, decision, comment}` | lead | approve / reject / remove (rev must be current) |
| `GET /kb/search?q=&customer=&template=&limit=` | member | approved docs, ACL-filtered, snippet + metadata |
| `GET /kb/docs/{uuid}` | member | approved revision (markdown; images via `/kb/assets/{sha256}`) — audited |
| `GET /reports/weekly?week=2026-W43&scope=me\|team` | member / lead | deterministic markdown + JSON |
| `GET /reports/mandays?from=&to=&group=customer\|member&format=json\|csv` | lead | §9 |
| `GET /me/export` | member | zip: own items (all revisions), reviews of them, audit entries about them |
| `POST /me/erase` | member | erasure request (§10.3), admin completes |
| `PUT /admin/customers/{code}`, `GET/PUT /admin/settings`, `POST /admin/items/{uuid}/hold`, `POST /admin/users/{oid}/offboard`, `GET /admin/audit` | admin | administration |

Limits: request body ≤ 2 MB (assets ≤ 5 MB), 120 writes / 600 reads per user per 10 min (429), search `q`
≤ 200 chars. Errors are `{error: "<safe Thai/English text>"}`; no stack traces, no echo of payloads.

Local additions (built on this API, cards T-203…T-208):

- `[team]` config: `enabled = false`, `hub_url = ""`, `tenant_id = ""`, `client_id = ""`, `api_scope = ""`,
  `sync_interval_min = 15`.
- CLI: `opstrail team login [--device] | logout | status | sync | submit --episode ID… | --doc ID`.
- Local web routes `/api/team/*` (status, login, logout, preview, submit, items, search, docs/{uuid}, weekly,
  mandays, review) under the unchanged `LocalOnly` middleware; tokens never reach the browser.
- MCP (read-only): `team_search(query, customer, template, limit)`, `team_get_doc(doc_uuid)`,
  `team_weekly(week)` (own scope). Team document text is returned inside a fenced block headed
  "team document — untrusted data, approved by <lead> on <date>" so the AI client treats it as data, not
  instructions. With team mode off/offline these tools raise `OpsTrailError` with a Thai hint.
- Template `weekly-report` (Thai) so a weekly report can be opened as a normal doc session, polished with AI and
  exported to .docx.

## 9. Weekly report and man-days

- **Week** = ISO week, Monday–Sunday, `Asia/Bangkok` (Hub setting `timezone`).
- **Weekly report** (deterministic, like `recap.py`): per member — approved work entries grouped by customer
  (title, hours), documents submitted / approved, meeting hours; team section — hours and man-days per
  customer, new KB documents, items still waiting for review. `scope=me` = own section only.
- **Minutes of a work entry** = `claimed_min` if given, else `active_min` (§6.1 — `active_min` already contains
  the meeting time). `meeting_min` is only a breakdown ("meeting hours" in the report) and is **never added**.
- A golden fixture covers a focused meeting (Teams in front), a screen-shared meeting (PowerShell in front, Teams
  in the background → presence segments) and foreground work after the call: expected minutes = wall-clock focus
  time, and the property "Σ minutes of one member's day ≤ union of their focus windows" is asserted.
- **Man-days** = Σ minutes ÷ (`hours_per_manday` × 60), `hours_per_manday = 8` by default; shown with two
  decimals, plus captured vs claimed minutes so a lead sees adjustments. Rounding for invoices is a finance
  decision, not OpsTrail's. `INTERNAL` is reported separately.
- Group by customer (default) or by member, any date range; CSV for finance. A golden fixture
  (`tests/hub_fixtures/`) with known totals is the referee for this logic.
- No ranking, no per-hour timeline, no idle time — the Hub never has those data.

## 10. PDPA (พ.ร.บ. คุ้มครองข้อมูลส่วนบุคคล พ.ศ. 2562)

> This section is an engineering proposal, not legal advice. Sysware's DPO/legal must confirm the legal basis,
> the notice text and the retention periods before the pilot (§14).

### 10.1 Data and roles

| data | whose | controller | where |
|---|---|---|---|
| raw capture (commands, windows, URLs, notes, screenshots) | the engineer | the engineer's own tool; Sysware policy applies to the laptop | laptop only |
| work entries, identity (oid, name, upn), audit | the engineer (employee data) | **Sysware** | Hub |
| personal data *inside* documents (customer staff names, e-mails, phone numbers) | customer staff | the **customer**; Sysware = processor under the customer contract/DPA | Hub KB |

Proposed legal basis for work entries and reports: contract performance / legitimate interest (customer
billing, service delivery, knowledge sharing) — **not consent**, because consent from employees is hard to treat
as freely given. Team mode is still **opt-in per person** (`[team] enabled`) and per item (nothing is sent
without the person pressing "ส่ง"), and declining has no effect on what the Hub can see.

### 10.2 Notice and acceptance

- The Hub stores the current notice (Thai, versioned, set by admin; draft in Appendix A).
- `GET /me` returns `notice_version_required`; the local web UI shows the notice on first sign-in and after each
  new version. Writes return 428 until `POST /me/notice` with the current version. Acceptance = acknowledgement
  of the notice (timestamp + version stored in `users` and audited).

### 10.3 Rights: access, export, deletion

- **Access/export**: `GET /me/export` (any time, self-service) — JSON in a zip, Thai field descriptions.
- **Withdraw an item**: owner, any time, unless under legal hold → content deleted at once.
- **Erasure request** (`POST /me/erase`, or offboarding by admin): personal identifiers in `users` are replaced by
  a pseudonym (`member-<4 hex>`), `upn`/name removed. Pending/rejected items are deleted. Approved work entries
  are kept pseudonymized as long as accounting/contract retention requires (§10.5), approved documents stay in
  the KB as company work product with the author pseudonymized unless a lead removes them. The requester gets the
  result in the audit/export. Admin completes within 30 days (PDPA-style response time, to be confirmed by DPO).
- Local data is the person's own: `opstrail purge`, plus the new local retention (§10.5).

### 10.4 Minimising personal data in documents

Publish-time PII check (warnings in the preview, and the Hub flags them for the reviewer): Thai national ID
(13 digits with checksum), Thai mobile numbers, e-mail addresses that are not role accounts. Optional
`[team] block_pii = true` turns warnings into a hard stop. Existing secret redaction still runs first.

### 10.5 Retention (proposed defaults, admin-configurable in `hub.toml`)

| data | default | after |
|---|---|---|
| rejected / withdrawn-but-held items | 30 days after last change | deleted |
| approved work entries | 5 years (Thai accounting records) | deleted, aggregates per customer/month kept without person |
| approved documents (KB) | while relevant; review at 3 years | lead decides keep / remove |
| audit log | 2 years | deleted (hash chain re-anchored) |
| pseudonymised users | with their last retained item | deleted |
| local raw events + screenshots (laptop) | `[retention] raw_days = 180` (new, local) | purged daily by the agent; documents are kept |

A daily Hub job applies retention (skipping `legal_hold` items) and logs counts to the audit log. Backups
expire after 35 days, so deletions reach backups within that window (stated in the notice).

### 10.6 Other obligations

- **Breach**: audit log + Hub logs support the investigation; the PDPC must be notified within 72 h of
  becoming aware of a breach with risk to persons — runbook in the ops guide (T-210).
- **Cross-border**: prefer hosting in Thailand (Sysware DC or a Thai cloud region). Hosting abroad needs the
  PDPA cross-border transfer rules checked by legal. LLM use of KB documents (MCP `team_get_doc` → Claude
  Desktop) follows the same rule as today's local documents: use Azure OpenAI / local models for customers that
  require it.
- **Records of processing (ROPA)**: Appendix B gives the entry for Sysware's ROPA.

## 11. Threat model

Assets: **customer documents** (SOPs list hostnames, IPs, procedures — for an MSSP this is a map of customer
networks, the most valuable asset), work entries (employee data), tokens, the audit log.
Actors: external attacker, curious/malicious member, compromised laptop, compromised Hub host,
misconfigured Entra, prompt-injected AI client.

| # | threat (STRIDE) | mitigation | test / evidence |
|---|---|---|---|
| T1 | Hub reachable from the Internet (I, D) | bind to internal network; access via VPN or Entra Application Proxy; TLS 1.2+; `/healthz` reveals nothing | ops checklist T-210 |
| T2 | forged or foreign-tenant token (S) | full validation §4 (sig, iss, tid, aud, azp, scp, exp); reject `alg=none`/HS*; JWKS only from configured tenant URL | fake-JWKS tests for each rule |
| T3 | stolen token from a laptop (S, I) | DPAPI cache, short access tokens, Conditional Access, Entra revocation, user `active=false` on offboarding | token cache test; offboarding test |
| T4 | member acts as lead/admin (E) | role only from `roles` claim; one `authorize(user, action, item)` function; deny by default | route × role matrix test (every route) |
| T5 | member reads others' pending items or restricted customers, incl. via a retagged revision (I) | ACL in SQL filters for search/read/report; customer per revision + one `can_read` (§7); owner check on items | matrix test incl. restricted customer and retag in both directions |
| T6 | secrets/PII leave the laptop in a submission (I) | projection without raw fields, redaction on client **and** Hub, preview with warnings, image checkbox, lead review, PII check | tests: payload never contains cmd/title/url fields; Hub re-redacts a token sent by a "modified client" |
| T7 | modified client pushes raw data in allowed fields (I) | strict schema, field length limits, re-redaction, review before KB/reports | schema tests |
| T8 | approved doc carries prompt injection into AI clients (T) | approved-only, author+approver shown, untrusted-data framing in MCP output, docs never executed | MCP output test |
| T9 | stored XSS through KB content in the local web UI (T) | existing `esc()`/`renderMd()` escaping, CSP `script-src 'self'` unchanged | web test with `<script>` in a team doc |
| T10 | someone denies approving/removing/reading (R) | append-only audit (submit, review, remove, KB doc read, export, erase, admin changes), SHA-256 hash chain, admin cannot edit rows via API | audit chain verify test |
| T11 | insider bulk-downloads the KB (I) | per-user rate limit, every document read audited, lead/admin report of unusual read counts | rate-limit test |
| T12 | Hub host compromise (all) | Hub holds no secrets (public JWKS only), disk encryption, encrypted backups, minimal admins, patching | ops checklist |
| T13 | local server used as a proxy to other hosts (SSRF) | Hub URL only from config, https only, no URL parameters, no redirects followed | client test |
| T14 | DoS by large uploads (D) | body/asset limits, 30 images per doc, 429 rate limits | limit tests |
| T15 | lost/unencrypted laptop (I) | local raw retention, BitLocker recommendation in README, team token revocable in Entra | — |
| T16 | dependency supply chain | two pinned, widely used libraries (`msal`, `PyJWT[crypto]`); no build step, no CDN | CI |

## 12. Deployment and operations (detail in T-210)

- `opstrail hub serve --config hub.toml` (uvicorn, one process). Runs as a Windows service or systemd unit
  behind IIS/nginx/Caddy terminating TLS; `trusted_proxies` in `hub.toml` for the client IP in audit/rate limits.
- `hub.toml`: `tenant_id`, `audience`, `allowed_client_ids`, `home` (db + assets), `bind = "127.0.0.1:8770"`,
  `timezone`, `hours_per_manday`, retention values, `allow_self_approval`.
- Backups: nightly `sqlite3 .backup` + assets folder to encrypted storage, keep 35 days; quarterly restore test.
- Monitoring: `/healthz`, log of request counts and errors (never payloads, tokens or titles).
- Upgrades: additive schema migrations on start (same pattern as the local store), version in `settings`.

## 13. Phasing → task cards

All cards are created with `**Status:** blocked` (blocked by: Bro's approval of this design) so the nightly duo run
does not start them early. Bro approves → change each to `todo`. Priority = build order.

| card | title | owner (builder → reviewer) | depends on |
|---|---|---|---|
| T-201 | Hub skeleton: store, API frame, authz + audit, fake auth for tests | Claude → GPT | — |
| T-202 | Entra ID SSO: Hub token validation + desktop MSAL sign-in + IT setup guide | Claude → GPT | T-201, deps approval, app registrations |
| T-203 | Customer registry + customer tagging of episodes/documents | GPT → Claude | T-201 |
| T-204 | Publish work entries: projection, preview, outbox, sync, Hub ingest | Claude → GPT | T-202, T-203 |
| T-205 | Publish documents + images (assets) | Claude → GPT | T-204 |
| T-206 | Lead review queue + status back to the author | GPT → Claude | T-204 |
| T-207 | Team knowledge base search (Hub FTS + web + MCP read-only tools) | GPT → Claude | T-205, T-206 |
| T-208 | Weekly report + man-days per customer | GPT → Claude | T-206 |
| T-209 | PDPA: notice/acceptance, export, erasure, retention (Hub + local), PII check, restricted customers | Claude → GPT | T-204 |
| T-210 | Deployment + ops guide, hardening checklist, backup/restore | Claude → GPT | T-202 |

Pilot after T-208: Bro + one lead, one customer, two weeks; then T-209 must be done before the whole team joins.

## 14. Decisions Bro needs to make (เรื่องที่ต้องให้ Bro ตัดสิน)

1. **Approve this design** (or comment in the PR) → flip T-201…T-210 to `todo`.
2. **Dependencies**: `msal` (extra `team`, client) and `PyJWT[crypto]` (extra `hub`, pulls `cryptography`).
   Both optional extras; the single-user install stays unchanged. *Recommended: yes.*
3. **Where the Hub runs**: Sysware DC/VM reachable over VPN (recommended) vs. a cloud VM; region inside Thailand?
4. **Entra**: who in IT creates the two app registrations and groups; Entra ID P1 available (group → role)?
5. **Man-day**: 8 h? Do meetings count (proposed: yes — they are part of `active_min`, §6.1)? Is `claimed_min`
   allowed, and should a lead see the captured value?
6. **Lead approval for work entries** — required (proposed) or only for documents?
7. **Retention values** in §10.5 and **DPO/legal review** of §10 + Appendix A before the pilot.
8. **Restricted customers** needed from day one (which customers' contracts forbid team-wide sharing)?

## Appendix A — privacy notice draft (Thai, for DPO review)

> **ประกาศความเป็นส่วนตัว OpsTrail Team (ฉบับร่าง v1)**
>
> 1. **ข้อมูลที่อยู่บนเครื่องของคุณเท่านั้น**: คำสั่ง, ชื่อหน้าต่าง, URL, ผลลัพธ์คำสั่ง, โน้ต และภาพหน้าจอที่ OpsTrail
>    บันทึก จะไม่ถูกส่งขึ้น OpsTrail Hub
> 2. **ข้อมูลที่ส่งขึ้น Hub เมื่อคุณกด "ส่ง" เท่านั้น**: work entry (วันที่ เวลา จำนวนนาที ลูกค้า ชื่องาน สรุปสั้น
>    ประเภทกิจกรรม) และเอกสารที่คุณเลือกส่งพร้อมรูปในเอกสาร คุณเห็นข้อมูลทั้งหมดก่อนส่ง
> 3. **ข้อมูลระบุตัวตน**: ชื่อ, บัญชี Microsoft (Entra ID) และบันทึกการใช้งาน (audit log)
> 4. **วัตถุประสงค์**: สรุปงานรายสัปดาห์, คำนวณ man-day ต่อลูกค้าเพื่อการให้บริการและออกใบแจ้งหนี้,
>    คลังความรู้ของทีม — **ไม่ใช้เพื่อจัดอันดับหรือประเมินผลงานรายบุคคลจากข้อมูลการใช้งานคอมพิวเตอร์**
> 5. **ผู้ที่เห็นข้อมูล**: lead อนุมัติงานและเห็นรายงานของทีม; สมาชิกทุกคนค้นเอกสารที่อนุมัติแล้วได้
>    (ยกเว้นลูกค้าที่จำกัดสิทธิ์); admin ดูแลระบบและ audit log
> 6. **ระยะเวลาเก็บ**: ตามตารางที่ประกาศใน Hub (ค่าเริ่มต้น: work entry 5 ปี, audit log 2 ปี, งานที่ถูกส่งกลับ 30 วัน,
>    backup 35 วัน)
> 7. **สิทธิของคุณ**: ดาวน์โหลดข้อมูลของคุณ ("ส่งออกข้อมูลของฉัน"), ถอนงานที่ส่ง, ขอลบ/ทำให้ไม่ระบุตัวตน,
>    ขอแก้ไข และร้องเรียนได้ที่ DPO ของ Sysware: [TODO: ช่องทางติดต่อ DPO]
> 8. **ฐานทางกฎหมาย**: [TODO: DPO ยืนยัน — เสนอ: การปฏิบัติตามสัญญา / ประโยชน์โดยชอบด้วยกฎหมาย]
> 9. **ที่เก็บข้อมูล**: [TODO: ที่ตั้ง server]

## Appendix B — ROPA entry (draft)

Activity: "OpsTrail Team — work log, man-days and knowledge base". Controller: Sysware. Data subjects:
employees using team mode; customer staff named in documents (processor role). Categories: identity (name,
Entra oid/upn), work entries, documents, audit log. No sensitive data (PDPA s.26) intended; PII check warns.
Recipients: Sysware leads/admins; customers receive delivery documents through normal channels (outside
OpsTrail). Storage: Hub (location §14.3). Retention: §10.5. Security: §11.
