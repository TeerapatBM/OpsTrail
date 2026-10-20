# T-208 Weekly report + man-days per customer

**Suggested owner:** GPT (reviewer Claude) · **Phase:** C · **Size:** M · **Blocked by:** Bro's approval of `docs/team-mode.md` (incl. the man-day definition), T-206

**Status:** blocked · **Priority:** 27

## Goal
Every Monday a lead gets the team's weekly report and the man-days per customer without asking anyone; each
member sees their own. Design: `docs/team-mode.md` §9.

## Contract
- Hub, deterministic (like `recap.py`): `GET /v1/reports/weekly?week=YYYY-Www&scope=me|team` → markdown + JSON;
  `GET /v1/reports/mandays?from=&to=&group=customer|member&format=json|csv` (lead). Only `approved_rev` work
  entries; minutes = `claimed_min`, else `active_min` (`meeting_min` is a breakdown of `active_min`, never added —
  design §6.1 "Minutes"); man-days = minutes ÷ (`hours_per_manday` × 60), 2 decimals, captured vs claimed shown;
  minutes attributed to the customer of `approved_rev`, read access via `can_read` (design §7); ISO week in the Hub
  `timezone`; `INTERNAL` reported separately.
- Local: template `templates/weekly-report/` (Thai skeleton/guide) so the report opens as a doc session for AI
  polish and .docx export; web "ทีม → รายงาน" and MCP `team_weekly(week)` (own scope).
- No ranking, no idle time, no per-hour timeline.

## Acceptance criteria
- [ ] golden fixture (`tests/hub_fixtures/`) with known totals per customer/member, incl. a claimed override, a
      week boundary at Sunday 23:30 Bangkok and unapproved entries excluded
- [ ] no double counting: the fixture has a focused meeting and a screen-shared (background) meeting with
      foreground work; totals equal wall-clock focus time and `meeting_min` never adds to them
- [ ] shell-only entry (`active_min = 0`, `claimed_min = 20`): counted as 20 *claimed* minutes, 0 captured; the
      same entry without `claimed_min` adds 0 to the totals
- [ ] a work entry whose pending revision moved it to a restricted customer is hidden from non-group leads' reports
- [ ] CSV test; a member cannot read team scope (matrix test)
- [ ] SPEC / README (Thai) updated
