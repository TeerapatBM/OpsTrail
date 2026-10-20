# T-101 Browser extension: capture the real URL of admin consoles

**Suggested owner:** GPT (Codex / Copilot) · **Phase:** B · **Size:** M

## Goal
Edge/Chrome extension (Manifest V3) that reports the active tab's URL + title to the local OpsTrail agent, so
documents can say *exactly* which portal page was used (Azure blade, Sentinel rule, vCenter object).

## Why
Window titles are ambiguous ("Microsoft Azure"); URLs are precise and make SOP steps reproducible.

## Contract
- New endpoint in `src/opstrail/web/app.py`: `POST /api/ingest/browser` body `{url, title, tab_id, ts}`.
  - Must keep `LocalOnly`: requires header `X-OpsTrail: 1` **and** a per-install token
    (`~/.opstrail/browser_token`, shown in Settings → copy into the extension options page).
  - Origin will be `chrome-extension://<id>` → allow only when the token matches.
- New event type `browser` (SPEC §4): `data = {url, title, domain}`; strip query strings by default
  (`[capture] browser_keep_query = false`), redact via `redact_obj`, honour `exclude_title_patterns`
  and a new `exclude_domains` list (banking, personal mail by default) and the `paused` flag.
- Classifier: `browser` events go through the same rules (match on title + a new `url_regex` field).
- Extension lives in `extension/` (manifest.json, background.js, options.html). Debounce: send on tab
  activation/URL change, at most 1 event / 3 s; never send incognito tabs.

## Acceptance criteria
- [ ] pytest: endpoint rejects missing/wrong token, wrong host, and incognito flag; stores redacted event
- [ ] classifier test for 3 Azure/Sentinel URLs
- [ ] README section "ติดตั้ง extension" (load unpacked) in Thai
- [ ] `opstrail eval` still passes

## Out of scope
Publishing to the Chrome/Edge store.
