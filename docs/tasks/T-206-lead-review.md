# T-206 Lead review queue and status back to the author

**Suggested owner:** GPT (reviewer Claude) · **Phase:** C · **Size:** M · **Blocked by:** Bro's approval of `docs/team-mode.md`, T-204

**Status:** blocked · **Priority:** 25

## Goal
A lead approves or sends back submitted work entries and documents; the author sees the result and the comment
in their own OpsTrail. Design: `docs/team-mode.md` §7 (state machine), §8.

## Contract
- Hub: `GET /v1/review` (lead; filters customer/kind/member; excludes own items), `POST /v1/review/{uuid}`
  `{rev, decision: approve|reject|remove, comment}` (rev must be current, else 409), approve a member's week in one
  call, self-approval blocked unless `allow_self_approval`, every decision audited. Approved documents enter
  `kb_fts` at `approved_rev`; a newer pending revision keeps the old one visible.
- Customer is stored per revision (`work_revisions.customer`, `doc_revisions.customer`, not on `items`); all access
  goes through one `can_read(user, item)` (design §7): approved content needs the customers of `approved_rev` and
  of a pending newer revision; the queue needs the customers of `current_rev` and `approved_rev`.
- Client: local web "ทีม → รออนุมัติ" page for leads (fact-check findings and warnings shown, all text escaped);
  the author's episode/document views show state + comment (from `team_items`).

## Acceptance criteria
- [ ] state-machine tests (submit → reject → resubmit → approve → new rev pending → approve)
- [ ] self-approval test; a member cannot call review routes (matrix test)
- [ ] retag tests: approved rev on a restricted customer + pending rev retagged to a team customer → a lead outside
      the group sees neither in the queue nor the approved rev; team → restricted pending rev hides the approved rev
      from non-group users until approved/rejected
- [ ] web test: a comment containing `<script>` is escaped
- [ ] SPEC / README (Thai) updated
