# T-205 Publish documents and their images

**Suggested owner:** Claude (reviewer GPT) · **Phase:** C · **Size:** M · **Blocked by:** Bro's approval of `docs/team-mode.md`, T-204

**Status:** blocked · **Priority:** 24

## Goal
A final SOP / Delivery doc / Guide can be submitted to the team together with its screenshots. Design:
`docs/team-mode.md` §6.2.

## Contract
- Only local status `final`. Payload: uuid, template, title, customer, markdown (≤ 1 MB), local_version,
  `fact_check` result; `shot://<id>` → `asset://<sha256>`.
- Hub: `PUT /v1/assets/{sha256}` (hash verified, PNG/JPEG magic bytes, ≤ 5 MB, ≤ 30 per document, stored under
  `<hub_home>/assets/aa/<sha256>`); `doc_revisions`; a new local version = a new revision.
- Preview shows every image with a required checkbox "ตรวจแล้วว่าไม่มีรหัสผ่าน/ข้อมูลส่วนบุคคล", plus warnings
  for `[TODO`, fact-check findings and `[REDACTED]`.
- Reuses the outbox/sync of T-204; text redacted on client and Hub.

## Acceptance criteria
- [ ] tests: wrong hash / non-image / too large / too many images → rejected; an unchecked image blocks submit
- [ ] round-trip test: exporting the Hub copy resolves `asset://` images
- [ ] SPEC / README (Thai) updated
