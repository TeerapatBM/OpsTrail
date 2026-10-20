# T-107 "ให้ AI ตรวจ" — a second model reviews the draft (Claude writes, GPT checks, or vice versa)

**Suggested owner:** GPT · **Phase:** B · **Size:** M

**Status:** todo · **Priority:** 8

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
- [ ] pytest with the fake LLM server returning a JSON review
- [ ] eval `--llm` gains an optional reviewer score column
