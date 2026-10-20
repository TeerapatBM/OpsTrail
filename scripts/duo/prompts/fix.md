You are {{AGENT}}, continuing {{TASK_ID}} - "{{TASK_TITLE}}" (card `{{CARD}}`) on branch `{{BRANCH}}`.
This is round {{ROUND}}. You run unattended; nobody can answer questions. Same hard rules as before
(read `AGENTS.md`): no git commit/push/checkout, no `gh`, no `~/.opstrail`, no new deps, ASCII .ps1.

## Environment
{{ENVNOTE}}

## Runner gate result (pytest + eval on Windows)
```text
{{GATE}}
```

## Review by {{REVIEWER}}
{{REVIEW}}

## Do this
1. Fix every gate failure, every blocker and every major. Fix cheap minors too.
2. If you disagree with a review point, do not change the code for it: add a line to the *Decision log* in
   `docs/HANDOFF.md` explaining why, and mention it under OPEN.
3. Re-run `{{PYTEST}}` and `{{EVAL}}` until green. Keep SPEC/README/HANDOFF current.

## Final message - exactly these headings:
SUMMARY: <one line>
CHANGES:
- <file>: <what changed>
TESTS: <result>
OPEN: <remaining issues / disagreements, or "none">
