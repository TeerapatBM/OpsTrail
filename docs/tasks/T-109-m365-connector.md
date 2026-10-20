# T-109 Microsoft 365 connector (calendar, Teams transcripts, chats, mail) — when M365 access is approved

**Suggested owner:** Claude · **Phase:** B/C · **Size:** L · **Blocked by:** Entra app registration / admin consent

**Status:** blocked · **Priority:** 99

## Goal
Exact meeting subjects/attendees from the calendar, the meeting **transcript** (when transcription was on),
and the user's own Teams chat/mail subjects — as events attached to the right episodes.

## Contract
- Delegated Microsoft Graph with MSAL device-code or auth-code + PKCE; tokens in DPAPI-protected cache.
- Scopes: `Calendars.Read`, `OnlineMeetings.Read`, `OnlineMeetingTranscript.Read.All`, `Chat.Read`, `Mail.ReadBasic`.
- New event types `calendar`, `transcript` (stored as a file reference + summary, not inline), `message`.
- Collector runs in the agent every 15 min; transcripts summarised by the configured LLM into a note.
- A permission-request document for IT (`docs/m365-permissions.md`) explaining data flow and retention.

## Acceptance criteria
- [ ] fake Graph server tests; no network in CI
- [ ] eval case with a transcript fixture → meeting minutes must contain the decisions from the transcript
