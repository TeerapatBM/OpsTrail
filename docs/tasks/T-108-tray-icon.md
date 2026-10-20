# T-108 System tray icon

**Suggested owner:** GPT · **Phase:** B · **Size:** S

**Status:** done · **Priority:** 5

## Goal
Tray icon (pystray) showing recording state (green/grey), with menu: เปิดหน้าเว็บ, หยุด/บันทึกต่อ,
โน้ต, ถ่ายรูป, Daily worklog วันนี้, ออก.

## Contract
- Optional dependency in the `agent` extra (`pystray`, `Pillow`); runs in the agent process on its own thread.
- Uses existing `Agent.hotkey_pause`, `osapi.spawn_popup`, `web.app.url`.

## Acceptance criteria
- [x] menu actions unit-tested with a fake pystray (tests added; runner execution pending)
- [x] agent still starts when pystray is not installed (guarded worker import; regression test added)

## Verification

GPT, 2026-10-20: shared Python cannot launch in the Codex sandbox ("The file cannot be accessed
by the system"). Pytest and eval both attempted; runner must execute them. Real Windows tray,
Thai menu rendering and screenshot focus need an interactive-desktop smoke test.

Round 2 (GPT, 2026-10-20): runner reported 172 passed / 1 failed / 1 skipped, eval 22/22.
Fixed the failed pause/resume test's underlying lazy UTF-8 BOM header parsing in the PowerShell hook;
new deterministic Windows regression fails before the fix and passes after it. Direct PowerShell
execution of the unchanged pause/resume fixture passed 10/10 with output/privacy/cleanup assertions.
Full pytest and eval were attempted again; the shared Python launcher remains inaccessible in this sandbox.
Runner revalidation and interactive desktop smoke remain pending.
