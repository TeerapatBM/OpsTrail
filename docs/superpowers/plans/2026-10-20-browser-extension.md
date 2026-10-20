# Browser URL capture implementation plan

**Goal:** Implement docs/tasks/T-101-browser-extension.md in the existing worktree.
**Architecture:** Extension service worker posts to the local web server with a per-install token.
Browser capture validation/filtering lives in a module called by service.py; ingest remains the redaction boundary.
**Constraints:** No dependencies, no git mutations, Thai UI, no real user data, preserve LocalOnly.

- [x] Add endpoint/privacy/classifier tests, attempt focused pytest before implementation (launcher blocked).
- [x] Add browser event, filtering, token storage, service facade and narrow LocalOnly authentication.
- [x] Add MV3 extension with local options, focused-tab checks and three-second global debounce.
- [x] Expose token through protected Settings POST; include browser URLs in source packs.
- [x] Attempt pytest/eval, review diff, update SPEC/README/HANDOFF/card (Python launcher blocked).

Verification ledger: Node 3/3 passes, including a reproduced then fixed stale-timer trailing-update bug.
Python gates cannot start in this sandbox; no claim of passing Python tests/eval. Interactive browser
pairing is deferred to the runner's reviewer/Bro; normal capture still works with the extension absent.

Review focus: missing/wrong token and host; extension access to other routes; incognito/paused/exclusions;
fragment query secrets and credentials; service-worker restart/races and inactive tabs.
Execution: inline as requested by unattended runner; runtime failures are recorded, never treated as passing.
