# Copilot / GPT instructions for OpsTrail

Read `AGENTS.md` (rules + collaboration protocol with Claude) and `SPEC.md` (architecture, event schema,
MCP contract) before making changes. Key points:

- Business logic in `src/opstrail/service.py`; keep `mcp_server.py` and `cli.py` thin.
- Every captured string must go through `opstrail.redact` (use `OpsTrail.record` / `ingest.store_event`).
- Windows first, Python ≥ 3.10, ctypes instead of pywin32, `.ps1` files ASCII-only.
- Code must work with `mcp` SDK 1.x and 2.x; MCP tools return `str`; user errors raise `OpsTrailError`.
- Run `.venv\Scripts\python -m pytest -q` — it must stay green; add tests for behaviour changes.
- Claim tasks and record results in `docs/HANDOFF.md`; commit prefix `[gpt]` / `[copilot]`.
- User-facing text in Thai (+ English technical terms); code and comments in English.

When chatting in VS Code you can also use the `opstrail` MCP server (configured in `.vscode/mcp.json`, source: `setup/vscode/mcp.json`) to
summarise work or write SOP / delivery documents from Bro's captured activity.
