# Voice note implementation plan

Goal: implement T-103's microphone note hotkey and meeting-summary action.
Spec: docs/tasks/T-103-voice-note.md. Execute inline, unattended; no commits or installs.

Architecture: optional sounddevice recording in a popup worker; bounded 60-second mono
PCM WAV, deleted in finally. Local faster-whisper small by default, explicit cloud
backends using existing protected provider credentials. Service module saves through add_note.

- [x] Write fake recorder/transcriber tests for voice source, redaction, attachment,
  empty/error/cancel cleanup, pause and unavailable dependencies; attempt targeted pytest.
- [x] Implement voice module, service entry point, defaults and optional extra.
- [x] Add popup indicator/timer/stop/cancel, hotkey and meeting action; test routing.
- [x] Update SPEC, Thai README, card and HANDOFF decisions/review request.
- [x] Attempt full pytest and eval with shared Python; report actual outcomes.

Review focus: cleanup on recorder/transcriber failure; cancellation before upload;
backend/key mismatch; concurrent popup recordings; attachment fixed before slow transcription.
Real microphone, tkinter and model download/cloud tenant smoke require Bro's desktop.

Execution ledger: targeted pytest, full pytest and eval blocked before startup by shared
Python launcher error: "The file cannot be accessed by the system". Static diff review
performed; no passing runtime claims. Runner supplies gates and Claude review.
