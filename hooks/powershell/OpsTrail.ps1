# OpsTrail PowerShell hook - records each command you run (Windows PowerShell 5.1 and PowerShell 7+).
# Installed by scripts/install.ps1 as a line in your $PROFILE:
#     . "<repo>\hooks\powershell\OpsTrail.ps1"
# Put that line at the END of your profile (after oh-my-posh/starship) so the prompt wrapper survives.
# Writes one JSON line per command to %USERPROFILE%\.opstrail\inbox (schema: SPEC.md section 4).
# Secrets are redacted when the agent ingests the inbox. Create ~/.opstrail/paused to stop recording.

if ($global:OpsTrailHookLoaded) { return }
$global:OpsTrailHookLoaded = $true

$global:OpsTrailHome = if ($env:OPSTRAIL_HOME) { $env:OPSTRAIL_HOME } else { Join-Path $HOME '.opstrail' }
$global:OpsTrailInbox = Join-Path $global:OpsTrailHome 'inbox'
$global:OpsTrailSession = [guid]::NewGuid().ToString().Substring(0, 8)
$global:OpsTrailInboxFile = Join-Path $global:OpsTrailInbox ("pwsh-{0}-{1}.jsonl" -f $env:COMPUTERNAME, $PID)
$global:OpsTrailShell = if ($PSVersionTable.PSEdition -eq 'Core') { "pwsh $($PSVersionTable.PSVersion)" } else { "powershell $($PSVersionTable.PSVersion)" }
$__last = Get-History -Count 1
$global:OpsTrailLastId = if ($__last) { $__last.Id } else { 0 }
Remove-Variable __last -ErrorAction SilentlyContinue
$global:OpsTrailOriginalPrompt = $function:prompt

function global:Invoke-OpsTrailRecord {
    param([bool]$Ok, $ExitCode)
    try {
        $h = Get-History -Count 1
        if (-not $h -or $h.Id -eq $global:OpsTrailLastId) { return }
        $global:OpsTrailLastId = $h.Id
        if (Test-Path -LiteralPath (Join-Path $global:OpsTrailHome 'paused')) { return }
        if (-not (Test-Path -LiteralPath $global:OpsTrailInbox)) {
            New-Item -ItemType Directory -Path $global:OpsTrailInbox -Force | Out-Null
        }
        $duration = $null
        if ($h.EndExecutionTime -and $h.StartExecutionTime) {
            $duration = [math]::Round(($h.EndExecutionTime - $h.StartExecutionTime).TotalSeconds, 2)
        }
        $rec = [ordered]@{
            v          = 1
            ts         = $h.StartExecutionTime.ToString('o')
            type       = 'shell'
            source     = 'powershell'
            host       = $env:COMPUTERNAME
            user       = $env:USERNAME
            duration_s = $duration
            data       = [ordered]@{
                cmd       = $h.CommandLine
                cwd       = (Get-Location).ProviderPath
                success   = $Ok
                exit_code = $ExitCode
                shell     = $global:OpsTrailShell
                session   = $global:OpsTrailSession
            }
        }
        $line = ($rec | ConvertTo-Json -Compress -Depth 5) + "`n"
        [System.IO.File]::AppendAllText($global:OpsTrailInboxFile, $line, (New-Object System.Text.UTF8Encoding($false)))
    } catch {
        # never break the user's prompt
    }
}

function global:prompt {
    $ok = $?
    $code = $global:LASTEXITCODE
    Invoke-OpsTrailRecord -Ok $ok -ExitCode $code
    $global:LASTEXITCODE = $code
    if ($global:OpsTrailOriginalPrompt) { & $global:OpsTrailOriginalPrompt }
    else { "PS $($executionContext.SessionState.Path.CurrentLocation)$('>' * ($nestedPromptLevel + 1)) " }
}

# Shortcuts: ot-note "why I did this", ot-task start "Install Splunk UF", ot-task stop, ot-shot
$global:OpsTrailExe = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) '.venv\Scripts\opstrail.exe'
if (-not (Test-Path -LiteralPath $global:OpsTrailExe)) { $global:OpsTrailExe = 'opstrail' }
function global:ot-note { param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest) & $global:OpsTrailExe note @Rest }
function global:ot-task { param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest) & $global:OpsTrailExe task @Rest }
function global:ot-shot { param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest) & $global:OpsTrailExe shot @Rest }
if ($global:OpsTrailExe -ne 'opstrail') {
    # make `opstrail ...` work in every shell without activating the venv
    function global:opstrail { param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest) & $global:OpsTrailExe @Rest }
}
