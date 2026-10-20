# OpsTrail PowerShell hook - records each command you run (Windows PowerShell 5.1 and PowerShell 7+).
# Installed by scripts/install.ps1 as a line in your $PROFILE:
#     . "<repo>\hooks\powershell\OpsTrail.ps1"
# Put that line at the END of your profile (after oh-my-posh/starship) so the prompt wrapper survives.
# Writes one JSON line per command to %USERPROFILE%\.opstrail\inbox (schema: SPEC.md section 4).
# Secrets are redacted when the agent ingests the inbox. Create ~/.opstrail/paused to stop recording.
# Opt-in: [capture] shell_output = true in config.toml also records the first lines of each command's output
# (Start-Transcript into ~/.opstrail/transcripts, read back in prompt; read when the shell starts).

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

# ---- opt-in command output capture (SPEC section 4: data.output) ----
# Lines to keep per command; 0 = off. Minimal TOML read: [capture] shell_output / shell_output_lines.
$global:OpsTrailOutputLines = & {
    $enabled = $false
    $lines = 15
    try {
        $file = Join-Path $global:OpsTrailHome 'config.toml'
        if (Test-Path -LiteralPath $file) {
            $section = ''
            foreach ($raw in [System.IO.File]::ReadAllLines($file)) {
                $t = ($raw -replace '#.*$', '').Trim()
                if ($t -match '^\[\s*([^\]]+?)\s*\]$') { $section = $Matches[1]; continue }
                if ($section -ne 'capture') { continue }
                if ($t -match '^shell_output\s*=\s*(true|false)$') { $enabled = ($Matches[1] -eq 'true') }
                elseif ($t -match '^shell_output_lines\s*=\s*(\d+)$') { $lines = [int]$Matches[1] }
            }
        }
    } catch { $enabled = $false }
    if ($enabled) { [math]::Min([math]::Max($lines, 0), 200) } else { 0 }
}
$global:OpsTrailTranscript = $null
$global:OpsTrailTranscriptPos = 0
if ($global:OpsTrailOutputLines -gt 0) {
    try {
        $__dir = Join-Path $global:OpsTrailHome 'transcripts'
        if (-not (Test-Path -LiteralPath $__dir)) { New-Item -ItemType Directory -Path $__dir -Force | Out-Null }
        # transcripts of shells that were closed without cleanup (a live shell keeps its file locked)
        Get-ChildItem -LiteralPath $__dir -Filter '*.txt' -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -lt (Get-Date).AddHours(-12) } |
            Remove-Item -Force -ErrorAction SilentlyContinue
        $__file = Join-Path $__dir ("pwsh-{0}-{1}.txt" -f $PID, $global:OpsTrailSession)
        Start-Transcript -LiteralPath $__file -ErrorAction Stop | Out-Null
        $global:OpsTrailTranscript = $__file
        $global:OpsTrailTranscriptPos = (Get-Item -LiteralPath $__file).Length
        $null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
            try { Stop-Transcript | Out-Null } catch { }
            Remove-Item -LiteralPath $global:OpsTrailTranscript -Force -ErrorAction SilentlyContinue
        }
    } catch {
        $global:OpsTrailTranscript = $null  # e.g. a host without transcription: record commands only
    }
    Remove-Variable __dir, __file -ErrorAction SilentlyContinue
}

function global:Read-OpsTrailTranscript {
    # Text appended to this session's transcript since the previous call (max 64 KB), or $null.
    if (-not $global:OpsTrailTranscript) { return $null }
    try {
        $fs = New-Object System.IO.FileStream($global:OpsTrailTranscript, [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read, [System.IO.FileShare]'ReadWrite, Delete')
        try {
            $len = $fs.Length
            $start = [math]::Min($global:OpsTrailTranscriptPos, $len)
            $global:OpsTrailTranscriptPos = $len
            $n = [int][math]::Min($len - $start, 65536)
            if ($n -le 0) { return $null }
            $buf = New-Object byte[] $n
            [void]$fs.Seek($start, [System.IO.SeekOrigin]::Begin)
            $read = 0
            while ($read -lt $n) {
                $r = $fs.Read($buf, $read, $n - $read)
                if ($r -le 0) { break }
                $read += $r
            }
            $text = [System.Text.Encoding]::UTF8.GetString($buf, 0, $read)
            if (($len - $start) -gt $n) { $text += "`n<opstrail:more>" }
            return $text
        } finally { $fs.Dispose() }
    } catch { return $null }
}

function global:Format-OpsTrailOutput {
    # Drop the echoed "PS C:\> <command>" line(s), keep the first $MaxLines lines of output.
    param([string]$Text, [string]$CommandLine, [int]$MaxLines)
    if (-not $Text -or $MaxLines -le 0) { return $null }
    $lines = @($Text -split "\r?\n")
    $cmdLines = @(($CommandLine -replace '\r', '') -split "\n")
    $first = $cmdLines[0].Trim()
    if ($first) {
        for ($i = 0; $i -lt [math]::Min($lines.Count, 5); $i++) {
            if ($lines[$i].Contains($first)) {
                $skip = [math]::Min($i + $cmdLines.Count, $lines.Count)
                $lines = if ($skip -lt $lines.Count) { @($lines[$skip..($lines.Count - 1)]) } else { @() }
                break
            }
        }
    }
    $more = $false
    $keep = New-Object System.Collections.Generic.List[string]
    foreach ($l in $lines) {
        if ($l -eq '<opstrail:more>') { $more = $true; continue }
        if ($l -match '^(PS>|>> )TerminatingError\(') { continue }  # transcript duplicate of the error record
        if ($keep.Count -eq 0 -and -not $l.Trim()) { continue }
        $keep.Add($l.TrimEnd())
    }
    while ($keep.Count -gt 0 -and -not $keep[$keep.Count - 1]) { $keep.RemoveAt($keep.Count - 1) }
    if ($keep.Count -eq 0) { return $null }
    if ($keep.Count -gt $MaxLines) { $more = $true; $keep = $keep.GetRange(0, $MaxLines) }
    $out = @($keep | ForEach-Object { if ($_.Length -gt 400) { $_.Substring(0, 400) + '...' } else { $_ } })
    [pscustomobject]@{ Text = ($out -join "`n"); Truncated = $more }
}

function global:Invoke-OpsTrailRecord {
    param([bool]$Ok, $ExitCode, [string]$Output)
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
        if ($Output) {
            try {
                $o = Format-OpsTrailOutput -Text $Output -CommandLine $h.CommandLine -MaxLines $global:OpsTrailOutputLines
                if ($o) {
                    $rec.data['output'] = $o.Text
                    if ($o.Truncated) { $rec.data['output_truncated'] = $true }
                }
            } catch { }  # keep the command even if its output cannot be read
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
    $out = Read-OpsTrailTranscript  # always consume, so the next command only gets its own output
    Invoke-OpsTrailRecord -Ok $ok -ExitCode $code -Output $out
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
