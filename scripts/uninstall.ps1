<#
.SYNOPSIS
  Remove OpsTrail hooks, startup entry and Claude Desktop registration.
  Data in ~/.opstrail is kept unless -PurgeData is given. The repo folder itself is not touched.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\uninstall.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\uninstall.ps1 -PurgeData
#>
[CmdletBinding()]
param([switch]$PurgeData)

$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
$home2 = if ($env:OPSTRAIL_HOME) { $env:OPSTRAIL_HOME } else { Join-Path $HOME '.opstrail' }

# stop the agent
$pidFile = Join-Path $home2 'agent.pid'
if (Test-Path -LiteralPath $pidFile) {
    $agentPid = [int](Get-Content -LiteralPath $pidFile -Raw)
    Stop-Process -Id $agentPid -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] agent stopped"
}

# startup shortcut
$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'OpsTrail Agent.lnk'
if (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk -Force; Write-Host "[OK] removed $lnk" }

# web shortcuts
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $u = Join-Path $dir 'OpsTrail.url'
    if ($dir -and (Test-Path -LiteralPath $u)) { Remove-Item -LiteralPath $u -Force; Write-Host "[OK] removed $u" }
}

# profile hook lines
$docs = [Environment]::GetFolderPath('MyDocuments')
foreach ($p in @((Join-Path $docs 'WindowsPowerShell\profile.ps1'), (Join-Path $docs 'PowerShell\profile.ps1'))) {
    if (Test-Path -LiteralPath $p) {
        $lines = Get-Content -LiteralPath $p
        $kept = $lines | Where-Object { $_ -notmatch 'OpsTrail\.ps1' }
        if ($kept.Count -ne $lines.Count) {
            Set-Content -LiteralPath $p -Value $kept -Encoding UTF8
            Write-Host "[OK] removed hook from $p"
        }
    }
}

# Claude Desktop entry
$venvPy = Join-Path $Root '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPy) {
    & $venvPy -m opstrail install-claude --remove
}

if ($PurgeData) {
    Remove-Item -LiteralPath $home2 -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] deleted $home2"
} else {
    Write-Host "Data kept in $home2 (use -PurgeData to delete). Exported documents are not touched."
}
