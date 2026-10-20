# OpsTrail — เวรปฏิบัติการ (Operations watch)

Designed by GPT, 2026-10-20, for T-111. This is the implementation specification.

## Intent and layout

A quiet shift ledger for Thai security engineers: time, evidence, then documents.
The distinctive device is a vertical trail joining episode rows, echoed in the three-node
brand mark. No decorative charts, gradients, remote assets or new dependencies.
Desktop uses a 232px navigation rail, a restrained page heading and a compact five-part
summary strip. Content aligns left. The editor gets the full remaining width, with equal
Markdown/preview columns. Below 980px the rail becomes a compact header and editor tabs
switch between panes; below 600px lists become labelled rows and navigation is a five-item grid.
Thai labels stay visible beside navigation SVGs, including on phones.

## Colour tokens

| Token | Light | Dark | Role |
|---|---|---|---|
| bg | #edf2f5 | #101c29 | Workspace |
| panel | #ffffff | #172737 | Main surface |
| panel-2 | #e6edf2 | #203447 | Secondary surface |
| text | #172e40 | #e5eef5 | Main text |
| muted | #506577 | #a6bacb | Supporting text |
| border | #6c8292 | #648096 | Controls and rules |
| accent | #076b72 | #7bd9d4 | Links, selection, focus |
| accent-soft | #dcefee | #203e48 | Selected surface |
| on-accent | #ffffff | #102c34 | Primary button text |
| ok / ok-soft | #246944 / #e3f2e9 | #8cdbac / #203d33 | Success |
| warn / warn-soft | #805000 / #fff0ce | #f3ce80 / #413827 | Warning |
| bad / bad-soft | #a42d41 / #fce8ed | #ffacba / #432b39 | Error |
| code-bg | #f1f5f8 | #12202e | Evidence/code |

Text pairs target WCAG AA (4.5:1 normal, 3:1 large text); status uses words as well as colour.
Focus uses a 2px accent outline with 3px offset. Controls have visible boundaries.
Theme choices are auto/light/dark, stored as `opstrail.theme` with guarded storage access.
Auto follows live OS preference; explicit choices override it. An external, blocking
`theme.js` runs before CSS to avoid a wrong-theme flash. No server configuration change.

## Typography and geometry

Thai-first system stack: Leelawadee UI, Noto Sans Thai, Tahoma, Segoe UI, system-ui.
Body 14px/1.75; supporting text 12.5–13px/1.75; headings 24/18/15px with 1.65 line height.
Numbers use tabular figures. Code uses Cascadia Mono/Consolas with the Thai body stack as
fallback, 12.5px/1.8. Never uppercase or letter-space Thai, constrain input height, or clip tone marks.
Spacing scale: 4, 8, 12, 16, 24, 32, 48px. Radius: 6px controls, 8px panels, pill status.
Panels use borders rather than repeated shadows; elevation is reserved for dialogs/toasts.

## Components and states

- Navigation: SVG + text, hover surface, active inset trail marker and `aria-current=page`.
- Buttons: default, primary, danger, ghost, hover, disabled, keyboard focus; minimum 40px height.
- Fields: visible labels or accessible names, focus, readonly/disabled, wrapping help text.
- Episode: time column, editable title, labelled selection, metadata, expandable evidence.
- Summary: joined strip, numeric hierarchy; two columns on phones.
- Tables: quiet headers, hover rows; phone rows repeat column names via `data-label`.
- Editor: fixed pane geometry while streaming, scrollable preview, mobile edit/preview tabs.
  Version, source, diff, review and fact-check panels share semantic surfaces; diff also uses
  underline/strike-through so colour is not the only signal.
- Settings: heading first, theme then existing profile/provider/style/Teams/browser/capture
  panels. Voice configuration remains in the existing configuration/hotkey flow (no new API).
- Empty/loading: centered guidance and status text, busy overlay with spinner; errors and
  fact-check warnings use a labelled surface. Toasts announce through the existing live region.
- Dialog: native focus trapping/Escape, constrained viewport height, scrolling body and actions.

Motion is limited to 120ms colour/border feedback and the busy spinner; reduced-motion
disables animations/transitions. No entry choreography or auto-scrolling during streaming.

## Implementation and verification plan

1. Add static security/token tests and a dependency-free Node test for theme persistence,
   denied storage, invalid preferences, OS changes and synchronization of both selectors.
2. Build tokens/layout/components in app.css; preserve existing IDs, routes and escaping.
   Add theme.js and SVG navigation; label existing unlabelled inputs and phone table cells.
3. Add an ASCII PowerShell snapshot launcher plus a Python seed/server helper using only
   golden-day fixtures and a newly created temporary home. Never load real user settings.
   Capture day, worklogs, docs, editor, search and settings in both themes at 1440x900;
   day/editor also at 390x844. Edge first, Chrome fallback, isolated browser profiles.
4. Inspect generated screens when the installed runtime can launch; run pytest, eval,
   Node tests/syntax and diff checks. Record environment limits without claiming passing gates.

No schema, API, MCP, middleware or dependency changes. Runner handles commits and Claude review.

Execution: theme/contrast Node tests, syntax and the real PowerShell launcher with fake processes
passed (16 capture requests, hidden windows, isolated profiles, restored environment, stopped server).
Python pytest/eval and real snapshot generation are blocked by the shared Python launcher in this
sandbox; no PNGs are claimed. See `screens/README.md`. Live browser/mobile/Thai layout inspection remains
required. The test bootstrap is external JS served only by the synthetic helper, under LocalOnly.
