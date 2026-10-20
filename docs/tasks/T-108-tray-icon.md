# T-108 System tray icon

**Suggested owner:** GPT · **Phase:** B · **Size:** S

**Status:** todo · **Priority:** 5

## Goal
Tray icon (pystray) showing recording state (green/grey), with menu: เปิดหน้าเว็บ, หยุด/บันทึกต่อ,
โน้ต, ถ่ายรูป, Daily worklog วันนี้, ออก.

## Contract
- Optional dependency in the `agent` extra (`pystray`, `Pillow`); runs in the agent process on its own thread.
- Uses existing `Agent.hotkey_pause`, `osapi.spawn_popup`, `web.app.url`.

## Acceptance criteria
- [ ] menu actions unit-tested with a fake pystray
- [ ] agent still starts when pystray is not installed
