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

T-111 execution limit (2026-10-20): no real PNGs were produced in the Codex sandbox. The prescribed shared
Python launcher fails before startup with “The file cannot be accessed by the system”. Direct installed
Edge/Chrome headless probes also produced no PNG (Edge reported an unusable GPU process). No replacement
images or mock-process outputs are included here. The runner/reviewer must run the command, inspect and
commit the PNG set before considering the screenshot acceptance criterion complete.
