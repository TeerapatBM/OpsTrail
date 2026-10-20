# T-208 Weekly report + man-days per customer

**Suggested owner:** GPT (reviewer Claude) · **Phase:** C · **Size:** M · **Blocked by:** Bro's approval of `docs/team-mode.md` (incl. the man-day definition), T-206

**Status:** blocked · **Priority:** 27

## Goal
Every Monday a lead gets the team's weekly report and the man-days per customer without asking anyone; each
member sees their own. Design: `docs/team-mode.md` §9.

## Contract
- Hub, deterministic (like `recap.py`): `GET /v1/reports/weekly?week=YYYY-Www&scope=me|team` → markdown + JSON;
  `GET /v1/reports/mandays?from=&to=&group=customer|member&format=json|csv` (lead). Only `approved_rev` work
  entries; minutes = `claimed_min`, else `active_min + meeting_min`; man-days = minutes ÷ (`hours_per_manday` × 60),
  2 decimals, captured vs claimed shown; ISO week in the Hub `timezone`; `INTERNAL` reported separately.
- Local: template `templates/weekly-report/` (Thai skeleton/guide) so the report opens as a doc session for AI
  polish and .docx export; web "ทีม → รายงาน" and MCP `team_weekly(week)` (own scope).
- No ranking, no idle time, no per-hour timeline.

## Acceptance criteria
- [ ] golden fixture (`tests/hub_fixtures/`) with known totals per customer/member, incl. a claimed override, a
      week boundary at Sunday 23:30 Bangkok and unapproved entries excluded
- [ ] CSV test; a member cannot read team scope (matrix test)
- [ ] SPEC / README (Thai) updated
