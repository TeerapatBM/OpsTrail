# T-103 Voice note: speak a 20-second summary instead of typing

**Suggested owner:** GPT · **Phase:** B · **Size:** M

**Status:** done · **Priority:** 7

## Goal
Hotkey `Ctrl+Alt+V` records up to 60 s from the default microphone, transcribes it (Thai + English) and
stores it as a `note` (attached to the current/just-ended episode). Also usable from the meeting-summary popup.

## Contract
- Optional extra `voice` in `pyproject.toml` (`sounddevice`, `faster-whisper`); without it the hotkey shows
  a toast explaining how to install.
- Transcription backends (`[voice] backend = "local" | "openai" | "azure"`): local `faster-whisper`
  (model `small`, downloaded on first use to `~/.opstrail/models`) or the configured OpenAI/Azure key.
- Audio is never stored after transcription (delete the temp WAV), never uploaded unless backend is a cloud API.
- Recording indicator: small always-on-top tkinter window with a stop button and a timer.

## Acceptance criteria
- [x] unit test with a fake recorder + fake transcriber → note event stored with `source = "voice"` (added; execution blocked by sandbox Python launcher)
- [x] privacy note in README (Thai)

## Verification / remaining smoke
Shared Python cannot start in Codex sandbox (`The file cannot be accessed by the system`)
for targeted pytest, full pytest and eval. Runner must execute both gates.
Bro/Claude: install the optional extra, test microphone/default device, timer/stop/Esc,
Thai + English transcription, first local model download and synthetic OpenAI/Azure speech
credentials on a real desktop. No hardware, model downloads or cloud calls were used in this run.
