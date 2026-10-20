<#
.SYNOPSIS
  Install OpsTrail for the current Windows user.

.DESCRIPTION
  1. Finds Python 3.10+ and creates .venv in the repo
  2. pip install -e ".[agent,dev]"
  3. Creates ~/.opstrail (config + database)
  4. Adds the PowerShell command hook to your profile (Windows PowerShell 5.1 and PowerShell 7)
  5. Adds "OpsTrail Agent" to your Startup folder and starts it now
  6. Registers the MCP server in Claude Desktop
  7. Copies setup/vscode -> .vscode and setup/github -> .github (VS Code MCP config for Copilot/GPT,
     tasks, launch, Copilot instructions)
  8. Creates an "OpsTrail" web shortcut (http://127.0.0.1:8765) on the Desktop and in the Start menu

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -NoStartup -NoClaudeDesktop
#>
[CmdletBinding()]
param(
    [switch]$NoProfileHook,
    [switch]$NoStartup,
    [switch]$NoClaudeDesktop,
    [switch]$NoStart,
    [switch]$NoExecutionPolicy,
    [switch]$ForceWorkspaceFiles
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

function Write-Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "    [OK] $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "    [!] $Text" -ForegroundColor Yellow }

function Find-Python {
    $candidates = @(
        @('py', '-3.13'), @('py', '-3.12'), @('py', '-3.11'), @('py', '-3.10'),
        @('python'), @('python3')
    )
    foreach ($c in $candidates) {
        $exe = $c[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $pyArgs = @()
        if ($c.Count -gt 1) { $pyArgs = $c[1..($c.Count - 1)] }
        try {
            $ver = & $exe @pyArgs -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $ver) {
                $parts = "$ver".Trim().Split('.')
                if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10) {
                    return , (@($exe) + $pyArgs)
                }
            }
        } catch { }
    }
    return $null
}

Write-Host "OpsTrail installer" -ForegroundColor Cyan
Write-Host "Repo: $Root"

# 1. Python + venv ---------------------------------------------------------
Write-Step "Python environment"
$venvPy = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPy)) {
    $py = Find-Python
    if (-not $py) {
        Write-Warn2 "Python 3.10+ not found."
        Write-Host "    Install it, then run this script again:"
        Write-Host "      winget install -e --id Python.Python.3.12"
        Write-Host "    (or download from https://www.python.org/downloads/ and tick 'Add python.exe to PATH')"
        exit 1
    }
    $pyExe = $py[0]
    $pyRest = @()
    if ($py.Count -gt 1) { $pyRest = $py[1..($py.Count - 1)] }
    Write-Host "    using: $($py -join ' ')"
    & $pyExe @pyRest -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}
Write-Ok ".venv ready"

Write-Step "Installing OpsTrail + dependencies (first time takes a minute)"
& $venvPy -m pip install --disable-pip-version-check -q --upgrade pip
& $venvPy -m pip install --disable-pip-version-check -q -e ".[agent,dev]"
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
Write-Ok "packages installed"

Write-Step "Creating ~/.opstrail"
& $venvPy -m opstrail init
if ($LASTEXITCODE -ne 0) { throw "opstrail init failed" }

# 2. PowerShell hook -------------------------------------------------------
if (-not $NoProfileHook) {
    Write-Step "PowerShell command hook"
    $hook = Join-Path $Root 'hooks\powershell\OpsTrail.ps1'
    Unblock-File -LiteralPath $hook -ErrorAction SilentlyContinue
    $line = ". `"$hook`"  # OpsTrail"
    $docs = [Environment]::GetFolderPath('MyDocuments')
    $profiles = @(
        (Join-Path $docs 'WindowsPowerShell\profile.ps1'),
        (Join-Path $docs 'PowerShell\profile.ps1')
    )
    foreach ($p in $profiles) {
        $dir = Split-Path -Parent $p
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $content = ''
        if (Test-Path -LiteralPath $p) { $content = Get-Content -LiteralPath $p -Raw -ErrorAction SilentlyContinue }
        if ("$content" -match 'OpsTrail\.ps1') {
            Write-Ok "already in $p"
        } else {
            Add-Content -LiteralPath $p -Value "`r`n$line" -Encoding UTF8
            Write-Ok "added to $p"
        }
    }
    if (-not $NoExecutionPolicy) {
        $effective = Get-ExecutionPolicy
        if ($effective -in @('Restricted', 'AllSigned', 'Undefined')) {
            try {
                Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
                Write-Ok "ExecutionPolicy (CurrentUser) set to RemoteSigned so the profile can load"
            } catch {
                Write-Warn2 "Could not change ExecutionPolicy ($effective) - the profile hook may not load. Ask IT or run with -NoProfileHook."
            }
        }
    }
    Write-Host "    Open a NEW PowerShell window to start recording commands."
}

# 3. Startup + start agent -------------------------------------------------
$pythonw = Join-Path $Root '.venv\Scripts\pythonw.exe'
if (-not $NoStartup) {
    Write-Step "Start the agent automatically at logon"
    $startup = [Environment]::GetFolderPath('Startup')
    $lnk = Join-Path $startup 'OpsTrail Agent.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($lnk)
    $sc.TargetPath = $pythonw
    $sc.Arguments = '-m opstrail agent'
    $sc.WorkingDirectory = $Root
    $sc.WindowStyle = 7
    $sc.Description = 'OpsTrail capture agent'
    $sc.Save()
    Write-Ok "shortcut: $lnk"
}
if (-not $NoStart) {
    Write-Step "Starting the agent"
    Start-Process -FilePath $pythonw -ArgumentList @('-m', 'opstrail', 'agent') -WorkingDirectory $Root -WindowStyle Hidden
    Start-Sleep -Seconds 3
    Write-Ok "agent started (log: $HOME\.opstrail\logs\agent.log)"
}

# 4. Claude Desktop --------------------------------------------------------
if (-not $NoClaudeDesktop) {
    Write-Step "Registering the MCP server in Claude Desktop"
    & $venvPy -m opstrail install-claude
}

# 5. VS Code / Copilot workspace files --------------------------------------
Write-Step "VS Code + Copilot workspace files"
$copies = @(
    @{ Src = 'setup\vscode'; Dst = '.vscode' },
    @{ Src = 'setup\github'; Dst = '.github' }
)
foreach ($c in $copies) {
    $srcDir = Join-Path $Root $c.Src
    $dstDir = Join-Path $Root $c.Dst
    if (-not (Test-Path -LiteralPath $srcDir)) { continue }
    if (-not (Test-Path -LiteralPath $dstDir)) { New-Item -ItemType Directory -Path $dstDir -Force | Out-Null }
    foreach ($f in Get-ChildItem -LiteralPath $srcDir -File -Recurse) {
        $rel = $f.FullName.Substring($srcDir.Length).TrimStart('\')
        $target = Join-Path $dstDir $rel
        $parent = Split-Path -Parent $target
        if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        if ((Test-Path -LiteralPath $target) -and -not $ForceWorkspaceFiles) {
            Write-Ok "kept existing $($c.Dst)\$rel"
        } else {
            Copy-Item -LiteralPath $f.FullName -Destination $target -Force
            Write-Ok "$($c.Dst)\$rel"
        }
    }
}

# 6. Web UI shortcuts ------------------------------------------------------
Write-Step "Web UI shortcuts (Desktop + Start menu)"
$webUrl = 'http://127.0.0.1:8765/'
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    if (-not $dir) { continue }
    $u = Join-Path $dir 'OpsTrail.url'
    Set-Content -LiteralPath $u -Value "[InternetShortcut]`r`nURL=$webUrl`r`n" -Encoding ASCII
    Write-Ok $u
}

# 7. Check -----------------------------------------------------------------
Write-Step "Health check"
& $venvPy -m opstrail doctor

Write-Host ""
Write-Host "Done. Hotkeys:" -ForegroundColor Cyan
Write-Host "  Ctrl+Alt+N  note (what / why / result)"
Write-Host "  Ctrl+Alt+S  screenshot of the active window (+ caption)"
Write-Host "  Ctrl+Alt+T  start / stop a task"
Write-Host "  Ctrl+Alt+P  pause / resume recording"
Write-Host "Web UI: $webUrl  (shortcut 'OpsTrail' on your Desktop)" -ForegroundColor Cyan
Write-Host "Or ask Claude / Copilot (GPT): 'use opstrail to summarise my work today'" -ForegroundColor Cyan
if (-not $NoStart) { Start-Process $webUrl }
