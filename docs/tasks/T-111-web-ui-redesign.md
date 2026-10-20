# T-111 Web UI redesign: new visual identity and theme, designed end-to-end by GPT

**Suggested owner:** GPT (Codex) · **Phase:** B · **Size:** L

**Status:** todo · **Priority:** 1

> Bro: "อยากยกเครื่องธีมของ web UI ใหม่หมด ให้ GPT เป็นคนออกแบบทั้งหมด"
> GPT owns every design decision (concept, colours, typography, layout, components, icons, motion).
> Claude reviews only for regressions, accessibility, security and the rules below - not for taste.

## Goal
Replace the current generic look of the local web UI (`src/opstrail/web/static/`) with a distinctive, polished
design system that feels like a professional tool for a Thai MSSP security team: calm, information-dense,
fast to scan, excellent in dark mode, and great with Thai text. Every page gets the new design:
day/episode view, worklogs, documents list, document editor (versions, diff, streaming, fact-check banner,
AI review), search, settings (profile, AI provider, style lessons, Teams digest, browser token, voice), toasts,
modal dialogs, empty/loading/error states.

## Who uses it
Bro and (later) his team: security engineers working all day in SOC consoles (Sentinel, Stellar Cyber, Defender)
and terminals; often dark-themed screens, laptop 1920x1200 at 150 % scaling (Lenovo X1), sometimes a phone.
UI language: Thai with English technical terms.

## Contract
1. **Design doc first:** `docs/design/WEB-THEME.md` - concept + rationale, colour tokens (light + dark),
   type scale (Thai-first: Leelawadee UI / Noto Sans Thai fallbacks, line-height that keeps Thai vowels and
   tone marks unclipped), spacing scale, radius/elevation, component inventory with states, motion rules.
2. **Implementation** in `app.css` (rewrite freely), `index.html` and the render functions in `app.js`.
   - CSS custom properties on `:root`; dark theme via `prefers-color-scheme` **and** a manual theme switch
     (auto / light / dark) in the sidebar + Settings, remembered in `localStorage` (wrap in try/catch).
   - Icons: inline SVG only (you may add a small icon sprite in `static/`), no icon fonts.
   - Keep every element id / data-attribute that `app.js` logic and the tests rely on, or update the logic and
     tests together. No functional regressions.
3. **Snapshot tool** so humans and the reviewer can *see* the result:
   `scripts/ui-snapshots.ps1` (ASCII-only) that starts the web app on a throw-away `OPSTRAIL_HOME` seeded from
   the golden days in `evals/days/` (synthetic data only), then uses the installed headless Microsoft Edge
   (fallback Chrome; no Playwright, no downloads) with `--headless --screenshot --window-size=...`
   (`--force-dark-mode` for dark) to write PNGs to `docs/design/screens/`:
   each main page x {light, dark} at 1440x900, plus day view and editor at 390x844 (phone).
   Commit the resulting PNGs.
4. Optional: refresh the favicon/brand mark to match the new identity (inline SVG / data URI).

## Hard constraints (from AGENTS.md - do not break)
- Vanilla HTML/CSS/JS only: no framework, no build step, **no CDN, no web fonts from the internet**
  (system fonts or font files committed under `static/` with a compatible licence).
- CSP stays `script-src 'self'`: no inline scripts, no inline event handlers. Do not touch the `LocalOnly`
  middleware in `web/app.py`.
- All user/AI text still goes through `esc()` / `renderMd()`; never use `innerHTML` with unescaped data.
- Accessibility: WCAG 2.1 AA contrast in both themes, visible keyboard focus, `prefers-reduced-motion`,
  labels on every input, touch targets >= 40 px on phone width, no horizontal scroll at 360 px.
- Performance: no layout jank while AI text streams into the editor; CSS total under ~60 KB.

## Acceptance criteria
- [ ] `docs/design/WEB-THEME.md` exists and matches what was built
- [ ] all pages restyled; light, dark and auto theme switch works and persists
- [ ] `scripts/ui-snapshots.ps1` produces the PNG set in `docs/design/screens/` (committed)
- [ ] `pytest` + `opstrail eval` green; existing web tests updated only where markup legitimately changed
- [ ] a pytest that checks: no external URLs (`http://`/`https://` hosts) in `static/*`, no inline `<script>`
      or `on*=` attributes in `index.html`, theme tokens defined for both light and dark
- [ ] README (Thai): short note about the new theme switch and `scripts/ui-snapshots.ps1`

## Review guidance (for Claude)
Run `scripts/ui-snapshots.ps1` if you can and look at the PNGs. Ask for CHANGES only for: broken or
overlapping layout, unreadable/clipped Thai text, contrast below AA, lost functionality, missing states,
CSP/escaping/LocalOnly violations, external resources. Colour, style and layout *preferences* are GPT's call.
