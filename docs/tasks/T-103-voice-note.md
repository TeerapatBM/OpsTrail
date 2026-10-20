# T-103 Voice note: speak a 20-second summary instead of typing

**Suggested owner:** GPT · **Phase:** B · **Size:** M

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
- [ ] unit test with a fake recorder + fake transcriber → note event stored with `source = "voice"`
- [ ] privacy note in README (Thai)
