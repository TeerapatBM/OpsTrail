# T-202 Entra ID SSO: Hub token validation + desktop sign-in + IT setup guide

**Suggested owner:** Claude (reviewer GPT) · **Phase:** C · **Size:** L · **Blocked by:** Bro's approval of `docs/team-mode.md`, dependency approval (`msal`, `PyJWT[crypto]`), Entra app registrations by IT

**Status:** blocked · **Priority:** 21

## Goal
Every Hub call is authenticated with the user's Sysware Entra ID account; roles member / lead / admin come from
Entra app roles. Design: `docs/team-mode.md` §4.

## Contract
- Hub: `hub/auth.py` Entra verifier with `PyJWT[crypto]` (optional extra `hub`): RS256 only, JWKS from
  `https://login.microsoftonline.com/<tid>/discovery/v2.0/keys` (cached, refetch on unknown `kid` at most once a
  minute), checks `iss`, `tid`, `aud`, `azp` in `allowed_client_ids`, `scp` contains `Team.ReadWrite`,
  `exp`/`nbf` (120 s leeway); identity = `oid`; role = highest of `OpsTrail.Admin/Lead/Member`; upsert `users`.
- Client: `src/opstrail/team/auth.py` with `msal` (optional extra `team`): interactive auth code + PKCE,
  `--device` fallback, silent refresh; MSAL cache serialized through `secretstore` into `team_token.json`.
- `[team]` config keys (`enabled`, `hub_url`, `tenant_id`, `client_id`, `api_scope`, `sync_interval_min`);
  `opstrail team login [--device] | logout | status`; web Settings section "ทีม" with a sign-in button
  (local route `POST /api/team/login`; tokens never reach the browser).
- `docs/team-entra-setup.md` (Thai): the two app registrations, app roles, groups, admin consent, manifest
  `accessTokenAcceptedVersion = 2`, Conditional Access note.
- Missing optional libraries → Thai hint; single-user OpsTrail unaffected. No network in tests.

## Acceptance criteria
- [ ] fake JWKS + locally signed tokens: one test per rejection rule (bad signature, `alg=none`, HS256, other
      tenant, wrong aud/azp/scp, expired, no role) and the happy path for each role
- [ ] client tests with a fake MSAL (cache stored protected, logout deletes it)
- [ ] SPEC (auth + config keys) and README (Thai, how to sign in) updated
