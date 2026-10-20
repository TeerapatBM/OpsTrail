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
