# setup/

Files that belong in `.vscode/` and `.github/` (they are kept here because remote tools may not write
into those folders). `scripts/install.ps1` copies them into place:

| source | installed to |
|---|---|
| `setup/vscode/*.json` | `.vscode/` (mcp.json = OpsTrail MCP for Copilot/GPT, tasks, launch, settings, extensions) |
| `setup/github/copilot-instructions.md` | `.github/copilot-instructions.md` |

Existing files are not overwritten unless you run `scripts\install.ps1 -ForceWorkspaceFiles`.
Manual alternative: copy the files yourself.
