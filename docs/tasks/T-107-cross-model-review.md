# T-107 "ให้ AI ตรวจ" — a second model reviews the draft (Claude writes, GPT checks, or vice versa)

**Suggested owner:** GPT · **Phase:** B · **Size:** M

**Status:** done · **Priority:** 8

## Goal
Button in the editor that sends the draft + source pack to a *reviewer* provider (can differ from the writer)
and shows a list of issues: claims without evidence in the sources, missing steps, unclear wording,
secrets. Optionally "แก้ตามที่ตรวจ" applies the fixes via the writer model.

## Contract
- Settings: second provider profile `reviewer` in `~/.opstrail/llm.json` (same schema as the writer).
- `service.review_draft(session_id)` → `{issues: [{severity, quote, problem, suggestion}], model}`;
  the model must answer JSON only (validate; retry once on invalid JSON).
- Combine with the deterministic `quality.fact_check` result.
- Store review results as a `doc_reviews` table (session, version, json, model, created_at).

## Acceptance criteria
- [x] pytest with the fake LLM server returning a JSON review (added; execution blocked by shared Python launcher)
- [x] eval `--llm` gains an optional reviewer score column (advisory, separate from gate)

## Implementation (GPT, 2026-10-20)

Separate protected reviewer profile/settings; saved-version review with strict JSON + one validation
retry, deterministic fact-check warnings, redaction and doc_reviews persistence. Thai editor button
locks controls, saves pending edits, shows escaped issues. Optional apply-fixes deferred; edits remain manual.
Tests cover fake HTTP JSON, credential isolation, failed validation, retry recovery, concurrent versions,
redaction, API protection and optional eval scoring. Node syntax/diff checks pass. Shared-Python
pytest/eval cannot start ("The file cannot be accessed by the system"); runner gates remain required.
Playwright smoke extended but unavailable here (module missing; no install).
