# UI screenshots

Run from the repository root on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ui-snapshots.ps1 -Python ".venv\Scripts\python.exe"
```

In the duo worktree, pass the shared OpsTrail venv interpreter instead. No install/download is performed.
Expected: 16 PNGs plus manifest.json. Day, worklogs, docs, editor, search and settings each have light/dark
1440x900 captures; day/editor also have light/dark 390x844 captures. Only synthetic `evals/days` data is used.
The development server preselects each theme through an external script so the light captures also work
on a dark Windows desktop; dark captures additionally use `--force-dark-mode`.
Desktop captures use the headless screenshot flags. Phone captures use loopback DevTools through
PowerShell 5.1's built-in ClientWebSocket: set 390x844 mobile metrics before navigating, wait for seeded
content at an actual 390px width without overflow, then capture the viewport with Page.captureScreenshot.
This avoids Windows Chromium's minimum headless window width cropping a wider page into a phone PNG.

T-111 round 2 execution limit (2026-10-20): the prescribed shared Python still fails before startup with
“The file cannot be accessed by the system”; the capture command exits at snapshot-server startup.
Claude successfully captured on the host during round 1, but those phone PNGs used the old cropped
window path. Run the corrected command on the host, inspect all 16 PNGs and commit them with manifest.json.
No replacement images or mock-process outputs are included here; the screenshot criterion remains open.
