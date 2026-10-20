# setup/

Files that belong in `.vscode/`, `.github/`, `.claude/` and `.codex/` (they are kept here because remote tools may not write
into those folders). `scripts/install.ps1` copies them into place:

| source | installed to |
|---|---|
| `setup/vscode/*.json` | `.vscode/` (mcp.json = OpsTrail MCP for Copilot/GPT, tasks, launch, settings, extensions) |
| `setup/github/**` | `.github/` (CI, Claude review, Copilot setup, templates) — copied by `scripts/init-github.ps1` |
| `setup/claude/settings.json` | `.claude/settings.json` (Claude Code: no permission prompts, deny force-push + `~/.opstrail`) — `scripts/duo.ps1 -Setup` |
| `setup/codex/config.toml` | `.codex/config.toml` (Codex: `approval_policy = "never"`, `workspace-write`) — `scripts/duo.ps1 -Setup` |

Existing files are not overwritten unless you run `scripts\install.ps1 -ForceWorkspaceFiles`.
Manual alternative: copy the files yourself.
