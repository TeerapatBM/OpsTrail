<#
.SYNOPSIS
  Put this folder into the GitHub repo and push (one-time), so Claude and GPT can work through PRs.

.DESCRIPTION
  1. git init (branch main) if needed and set your name/email for this repo
  2. Copy setup/github -> .github (CI on Windows+Linux, Claude PR review, Copilot setup, PR/issue templates)
  3. Commit everything (.venv, caches and local data are ignored by .gitignore)
  4. Add the remote and push. If the GitHub repo already has a README/commit it is merged (our files win).
  5. Optional -CreateIssues: create one GitHub issue per task card in docs/tasks (needs GitHub CLI "gh")

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\init-github.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\init-github.ps1 -CreateIssues
#>
[CmdletBinding()]
param(
    [string]$Repo = 'https://github.com/TeerapatBM/OpsTrail.git',
    [string]$Branch = 'main',
    [switch]$CreateIssues,
    [switch]$Force
)

# 'Continue': git writes progress to stderr, which Windows PowerShell 5.1 would treat as a fatal error
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

function Write-Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git is not installed. Install it, open a new PowerShell and run this script again:" -ForegroundColor Yellow
    Write-Host "  winget install -e --id Git.Git"
    exit 1
}

Write-Step "Git repository"
if (-not (Test-Path -LiteralPath (Join-Path $Root '.git'))) {
    git init -b $Branch | Out-Host
}
if (-not (git config user.email)) {
    $name = Read-Host "Your name for git commits"
    $email = Read-Host "Your e-mail for git commits (the one on GitHub)"
    git config user.name $name
    git config user.email $email
}

Write-Step "GitHub files (.github)"
$src = Join-Path $Root 'setup\github'
$dst = Join-Path $Root '.github'
foreach ($f in Get-ChildItem -LiteralPath $src -Recurse -File) {
    $rel = $f.FullName.Substring($src.Length).TrimStart('\')
    $target = Join-Path $dst $rel
    $dir = Split-Path -Parent $target
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    if ((Test-Path -LiteralPath $target) -and -not $Force) {
        Write-Host "    kept .github\$rel"
    } else {
        Copy-Item -LiteralPath $f.FullName -Destination $target -Force
        Write-Host "    .github\$rel"
    }
}

Write-Step "Commit"
git add -A
$pending = git status --porcelain
if ($pending) {
    git commit -m "OpsTrail: import from MCP Doc folder" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`nClaude-Session: https://claude.ai/code/session_012SKGf3Uc5gmBvvEiLXsqP6" | Out-Host
    if ($LASTEXITCODE -ne 0) { Write-Host "git commit failed" -ForegroundColor Red; exit 1 }
} else {
    Write-Host "    nothing new to commit"
}

Write-Step "Push to $Repo"
$remotes = git remote
if ($remotes -notcontains 'origin') { git remote add origin $Repo }
git fetch origin *> $null
$remoteHasBranch = git ls-remote --heads origin $Branch 2> $null
if ($remoteHasBranch) {
    Write-Host "    the GitHub repo already has '$Branch' - merging it (our files win on conflicts)"
    git merge "origin/$Branch" --allow-unrelated-histories -X ours -m "Merge initial GitHub repo" | Out-Host
    if ($LASTEXITCODE -ne 0) { Write-Host "merge failed - resolve with 'git status' and run the script again" -ForegroundColor Red; exit 1 }
}
git push -u origin $Branch | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host "git push failed - sign in to GitHub when the browser/Git Credential Manager asks, then run again" -ForegroundColor Red; exit 1 }

if ($CreateIssues) {
    Write-Step "Issues from docs/tasks"
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        Write-Host "    GitHub CLI not found: winget install -e --id GitHub.cli   then: gh auth login" -ForegroundColor Yellow
    } else {
        gh label create task --color 0E8A16 --force 2>$null | Out-Null
        foreach ($card in Get-ChildItem -LiteralPath (Join-Path $Root 'docs\tasks') -Filter 'T-*.md' | Sort-Object Name) {
            $title = (Get-Content -LiteralPath $card.FullName -TotalCount 1 -Encoding UTF8) -replace '^#\s*', ''
            gh issue create --title $title --body-file $card.FullName --label task | Out-Host
        }
    }
}

Write-Host ""
Write-Host "Done. Next on GitHub:" -ForegroundColor Cyan
Write-Host "  1. Let Claude Code + Codex build the task cards on your subscriptions (no API key):"
Write-Host "       powershell -ExecutionPolicy Bypass -File .\scripts\duo.ps1 -Setup"
Write-Host "       powershell -ExecutionPolicy Bypass -File .\scripts\duo.ps1 -Schedule 22:30 -MaxTasks 2"
Write-Host "  2. Optional: secret CLAUDE_CODE_OAUTH_TOKEN (from 'claude setup-token') for Claude review of non-duo PRs"
Write-Host "  3. See docs/COLLABORATION.md"
