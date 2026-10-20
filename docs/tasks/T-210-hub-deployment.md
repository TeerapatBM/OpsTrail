# T-210 Hub deployment + operations guide, hardening, backup/restore

**Suggested owner:** Claude (reviewer GPT) · **Phase:** C · **Size:** M · **Blocked by:** Bro's approval of `docs/team-mode.md`, hosting decision (design §14.3), T-202

**Status:** blocked · **Priority:** 29

## Goal
Bro (or Sysware IT) can install, back up, restore and upgrade the Hub from a Thai guide in under an hour.
Design: `docs/team-mode.md` §11 (T1, T12), §12.

## Contract
- `docs/team-hub-ops.md` (Thai): Windows service (and systemd) setup, reverse proxy (IIS/nginx/Caddy) with TLS,
  `trusted_proxies`, exposure via VPN or Entra Application Proxy, hardening checklist, monitoring, breach runbook
  (PDPC within 72 h), upgrade steps.
- `opstrail hub backup --to <dir>` (online SQLite backup + assets, keep N days) and `opstrail hub restore`;
  `scripts/install-hub.ps1` (ASCII-only) registers the service.
- Startup self-check: refuses a non-loopback `bind` unless TLS-terminating proxy settings are configured; warns
  when no recent backup exists.

## Acceptance criteria
- [ ] backup → restore round-trip test (db + assets; the audit chain still verifies)
- [ ] PowerShell 5.1 parse check of the new script on the Windows CI runner (`tests/test_windows.py`)
- [ ] README (Thai) links the guide
