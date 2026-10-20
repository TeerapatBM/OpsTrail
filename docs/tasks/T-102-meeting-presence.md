# T-102 Meeting presence: keep counting the meeting while you share your screen

**Suggested owner:** Claude · **Phase:** A+ · **Size:** S

## Goal
Today a meeting is detected only while the Teams meeting window has focus. When you share your screen and
work in a terminal for 20 minutes, the meeting episode ends. Detect "a meeting window exists" instead.

## Contract
- `agent/winapi.py`: `top_level_windows()` via `EnumWindows` + `IsWindowVisible` → `[(app, title)]`.
- Agent: every poll, if any visible window classifies as `meeting`, emit/extend a synthetic
  `presence` segment (type `window`, `data.app`, `data.title`, `data.presence = true`) while the user is
  active elsewhere. Segmentation: presence counts as meeting time; foreground work during it stays in the
  meeting episode (existing "inside a meeting span" rule).
- Config `[meetings] detect_background = true`.

## Acceptance criteria
- [ ] unit test with a fake window list: meeting episode spans the whole call although focus was elsewhere
- [ ] new golden-day case "screen-share-day" in `evals/cases.toml`
- [ ] Windows-only test for `top_level_windows()` in `tests/test_windows.py`
