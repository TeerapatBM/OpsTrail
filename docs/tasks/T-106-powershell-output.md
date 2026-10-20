# T-106 Capture command output (opt-in) for "expected result" sections

**Suggested owner:** Claude · **Phase:** B · **Size:** M

## Goal
SOPs need the expected output of each step. Capture the first N lines of each PowerShell command's output.

## Contract
- Opt-in `[capture] shell_output = false`, `shell_output_lines = 15`.
- PowerShell hook: `Start-Transcript` per session into `~/.opstrail/transcripts/`, then in `prompt`
  slice the transcript since the previous command and attach `data.output` (redacted at ingest, truncated).
- Bash/zsh: not in scope (document limitation).
- Source pack shows output under each command (max 15 lines) so the AI can write "ผลลัพธ์ที่คาดหวัง".

## Acceptance criteria
- [ ] Windows test (tests/test_windows.py) running the hook in PS 5.1 with a command that prints output
- [ ] redaction test: secrets in output are masked
- [ ] eval: new case where the SOP must mention a value that only appears in command output
