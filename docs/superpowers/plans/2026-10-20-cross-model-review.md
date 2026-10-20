# T-107 implementation plan

Goal: independently configured AI review of a saved draft, combined with deterministic checks.
Spec: docs/tasks/T-107-cross-model-review.md; SPEC.md.
Execution: inline/unattended, runner supplies Claude review; no commits or installs.

- Add tests for separate protected reviewer credentials, fake-server JSON review, schema retry,
  redaction, saved-version association, API protections and optional eval score.
- Extend llm profile helpers with optional reviewer profile, preserving legacy writer JSON.
- Implement strict JSON validation/retry and service review snapshot; persist doc_reviews.
- Add protected review/settings routes and escaped Thai editor/settings controls.
- Add optional reviewer score to --llm report without changing deterministic gate scoring.
- Update SPEC, README, card and HANDOFF; run shared-Python pytest and eval plus JS syntax check.

Review focus: no writer key fallback; no raw provider error echo; invalid/truncated JSON never
stored; concurrent edits retain reviewed version; historical editor versions cannot silently
review latest; AI text always escaped. Optional apply-fixes is deferred to avoid extra scope.

Execution ledger: implementation/tests/docs supplied. Focused and full shared-Python pytest
and eval were attempted but process creation is blocked by the launcher. Node syntax and
git diff checks pass. Extended Playwright smoke is blocked by missing playwright module;
no dependency installation. Runner/Claude review and runtime gates remain required.
