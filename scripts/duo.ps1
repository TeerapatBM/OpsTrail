<#
.SYNOPSIS
  Duo autopilot: Claude Code and Codex build OpsTrail together, unattended, on your Claude / ChatGPT
  subscriptions (no API key, no approval prompts).

.DESCRIPTION
  For each task card in docs/tasks that says "**Status:** todo":
    1. new git worktree + branch duo/T-xxx from origin/main (your running OpsTrail copy is not touched)
    2. BUILDER (the card's owner: Claude or GPT) implements the card ........ claude -p / codex exec
    3. GATE: this script runs pytest + "opstrail eval" itself, on your machine
    4. REVIEWER (the other model) reviews the diff, read-only ................. VERDICT: APPROVE | CHANGES
    5. gate red or CHANGES -> the builder fixes it (up to -MaxRounds rounds)
    6. approved + green -> PR on GitHub, wait for CI, squash-merge, update your local copy, restart agent
       anything else    -> PR labelled "needs-bro", nothing is merged
    7. Windows notification + .duo\last-run.md (logs of every step in .duo\logs\<run>)

  API keys (ANTHROPIC_API_KEY, OPENAI_API_KEY, ...) are removed from the environment of the AI processes,
  so both CLIs use your subscription logins and no API credit can be spent by accident.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\duo.ps1 -Setup          # one time
  powershell -ExecutionPolicy Bypass -File .\scripts\duo.ps1                 # next todo task
  powershell -ExecutionPolicy Bypass -File .\scripts\duo.ps1 -Task T-104     # one specific task
  powershell -ExecutionPolicy Bypass -File .\scripts\duo.ps1 -Schedule 22:30 -MaxTasks 2   # every night
  powershell -ExecutionPolicy Bypass -File .\scripts\duo.ps1 -Status
#>
[CmdletBinding()]
param(
    [string]$Task = '',
    [ValidateSet('auto', 'claude', 'gpt')][string]$Builder = 'auto',
    [int]$MaxTasks = 1,
    [int]$MaxRounds = 3,
    [int]$BuildTimeoutMin = 60,
    [int]$ReviewTimeoutMin = 30,
    [int]$GateTimeoutMin = 20,
    [int]$CiTimeoutMin = 30,
    [string]$MainBranch = 'main',
    [string]$ClaudeModel = '',
    [string]$CodexModel = '',
    [switch]$CodexFullAccess,
    [switch]$NoMerge,
    [switch]$NoDeploy,
    [switch]$NoNotify,
    [switch]$DryRun,
    [switch]$Setup,
    [switch]$Force,
    [switch]$Status,
    [string]$Schedule = '',
    [switch]$Unschedule
)

$ErrorActionPreference = 'Continue'
$IsWin = ($env:OS -eq 'Windows_NT')
$Utf8 = New-Object System.Text.UTF8Encoding $false
$OutputEncoding = $Utf8
try { [Console]::OutputEncoding = $Utf8 } catch { }

function J {
    # Join-Path for any number of parts (Windows PowerShell 5.1 has no -AdditionalChildPath)
    $p = [string]$args[0]
    foreach ($x in ($args | Select-Object -Skip 1)) { $p = Join-Path $p ([string]$x) }
    return $p
}

$Root = Split-Path -Parent $PSScriptRoot
$DuoDir = J $PSScriptRoot 'duo'
$PromptDir = J $DuoDir 'prompts'
$DuoHome = J $Root '.duo'
$StateFile = J $DuoHome 'state.tsv'
$TaskName = 'OpsTrail Duo'
$script:CodexFull = [bool]$CodexFullAccess
$KeyVars = @('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'OPENAI_API_KEY', 'CODEX_API_KEY', 'AZURE_OPENAI_API_KEY',
             'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY')
$QuotaRx = '(?i)(usage limit|limit reached|rate.?limit(ed)?|quota (exceeded|reached)|out of (credits|usage)|try again (later|in \d|at \d))'
$LoginRx = '(?i)(not logged in|please (log|sign) ?in|run .?/?login|invalid api key|authentication (failed|required)|unauthori[sz]ed)'

if ($env:OPSTRAIL_DUO_PYTHON) { $Py = $env:OPSTRAIL_DUO_PYTHON }
elseif ($IsWin) { $Py = J $Root '.venv' 'Scripts' 'python.exe' }
else { $Py = J $Root '.venv' 'bin' 'python' }

# ------------------------------------------------------------------ helpers
function Say([string]$Text, [string]$Color = 'Gray') { Write-Host $Text -ForegroundColor $Color }
function Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }

function Find-Tool([string]$Name, [string]$EnvName) {
    $o = [Environment]::GetEnvironmentVariable($EnvName)
    if ($o) { return $o }
    $c = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return $c.Source }
    return $null
}

function GitIn {
    # GitIn <dir> <git args...>  -> output text; exit code in $script:GitCode
    $d = [string]$args[0]
    $rest = @($args | Select-Object -Skip 1)
    $o = & git -C $d @rest 2>&1 | ForEach-Object { "$_" }
    $script:GitCode = $LASTEXITCODE
    return (($o -join "`n").Trim())
}

function Join-Args([string[]]$List) {
    $parts = foreach ($a in $List) {
        if ($a -eq '') { '""' }
        elseif ($a -match '[\s"]') { '"' + (($a -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"' }
        else { $a }
    }
    return ($parts -join ' ')
}

function Stop-Tree([int]$ProcId) {
    if ($IsWin) { & taskkill /PID $ProcId /T /F 2>&1 | Out-Null }
    else { & pkill -9 -P $ProcId 2>&1 | Out-Null; Stop-Process -Id $ProcId -Force -ErrorAction SilentlyContinue }
}

function Invoke-Native {
    param([string]$Exe, [string[]]$ArgList, [string]$WorkDir, [string]$StdIn, [string]$StdOut, [string]$StdErr,
          [int]$TimeoutMin = 30)
    $sp = @{ FilePath = $Exe; WorkingDirectory = $WorkDir; RedirectStandardInput = $StdIn
             RedirectStandardOutput = $StdOut; RedirectStandardError = $StdErr; NoNewWindow = $true; PassThru = $true }
    if ($ArgList -and $ArgList.Count) { $sp.ArgumentList = (Join-Args $ArgList) }
    try { $p = Start-Process @sp -ErrorAction Stop } catch {
        [IO.File]::AppendAllText($StdErr, "duo: could not start $Exe : $_", $Utf8)
        return 127
    }
    $null = $p.Handle   # keeps ExitCode readable after exit
    if (-not $p.WaitForExit([int]($TimeoutMin * 60000))) {
        Stop-Tree $p.Id
        [IO.File]::AppendAllText($StdErr, "`nduo: TIMEOUT after $TimeoutMin min", $Utf8)
        return 124
    }
    $p.WaitForExit()
    return [int]$p.ExitCode
}

function Read-Text([string]$Path) {
    if ($Path -and (Test-Path -LiteralPath $Path)) { return [IO.File]::ReadAllText($Path, $Utf8) }
    return ''
}

function Write-Text([string]$Path, [string]$Text) { [IO.File]::WriteAllText($Path, $Text, $Utf8) }

function Tail-Text([string]$Text, [int]$Lines = 40, [int]$MaxChars = 6000) {
    $l = @($Text -split "`r?`n")
    if ($l.Count -gt $Lines) { $l = $l[($l.Count - $Lines)..($l.Count - 1)] }
    $t = ($l -join "`n").Trim()
    if ($t.Length -gt $MaxChars) { $t = '...' + $t.Substring($t.Length - $MaxChars) }
    return $t
}

function Notify([string]$Title, [string]$Text) {
    Say "$Title - $Text" 'Green'
    if ($NoNotify -or -not $IsWin) { return }
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        $n = New-Object System.Windows.Forms.NotifyIcon
        $n.Icon = ('System.Drawing.SystemIcons' -as [type])::Information
        $n.BalloonTipTitle = $Title
        if ($Text.Length -gt 250) { $Text = $Text.Substring(0, 250) }
        $n.BalloonTipText = $Text
        $n.Visible = $true
        $n.ShowBalloonTip(15000)
        Start-Sleep -Seconds 8
        $n.Dispose()
    } catch { }
}

# environment for AI / gate processes: no API keys, no OpsTrail capture, worktree python path and temp
$script:SavedEnv = @{}
function Push-AgentEnv([string]$Wt, [switch]$Gate) {
    $script:SavedEnv = @{}
    $tmp = J $Wt '.tmp'
    $null = New-Item -ItemType Directory -Force -Path (J $tmp 'opstrail-home')
    $set = @{ OPSTRAIL_NO_CAPTURE = '1'; PYTHONPATH = (J $Wt 'src'); TEMP = $tmp; TMP = $tmp; TMPDIR = $tmp
              OPSTRAIL_HOME = (J $tmp 'opstrail-home'); PYTHONUTF8 = '1'; PYTHONIOENCODING = 'utf-8' }
    if ($Gate) { $set.Remove('OPSTRAIL_NO_CAPTURE') }   # run the tests like CI does
    foreach ($k in ($KeyVars + @($set.Keys))) {
        $script:SavedEnv[$k] = [Environment]::GetEnvironmentVariable($k, 'Process')
    }
    foreach ($k in $KeyVars) { [Environment]::SetEnvironmentVariable($k, $null, 'Process') }
    foreach ($k in $set.Keys) { [Environment]::SetEnvironmentVariable($k, $set[$k], 'Process') }
}
function Pop-AgentEnv {
    foreach ($k in $script:SavedEnv.Keys) { [Environment]::SetEnvironmentVariable($k, $script:SavedEnv[$k], 'Process') }
    $script:SavedEnv = @{}
}

# ------------------------------------------------------------------ task cards and state
function Get-Cards([string]$Ref) {
    $names = @((GitIn $Root ls-tree --name-only $Ref 'docs/tasks/') -split "`n" | Where-Object { $_ -match 'T-\d+[^/]*\.md$' })
    $cards = @()
    foreach ($n in $names) {
        $text = GitIn $Root show "$($Ref):$n"
        if ($text -notmatch '(?m)^#\s+(T-\d+)\s+(.+)$') { continue }
        $id = $Matches[1]
        $title = ($Matches[2].Trim() -replace '"', "'")
        $ownerLine = ([regex]::Match($text, '(?m)^\*\*Suggested owner:\*\*(.*)$')).Groups[1].Value
        $ci = $ownerLine.IndexOf('Claude'); $gi = $ownerLine.IndexOf('GPT')
        if ($ci -ge 0 -and ($gi -lt 0 -or $ci -lt $gi)) { $owner = 'claude' } else { $owner = 'gpt' }
        $m = [regex]::Match($text, '(?m)^\*\*Status:\*\*\s*([A-Za-z-]+)')
        if ($m.Success) { $st = $m.Groups[1].Value.ToLower() } else { $st = 'todo' }
        $pm = [regex]::Match($text, '\*\*Priority:\*\*\s*(\d+)')
        if ($pm.Success) { $prio = [int]$pm.Groups[1].Value } else { $prio = 50 }
        $cards += [pscustomobject]@{ id = $id; title = $title; owner = $owner; status = $st; path = $n; priority = $prio }
    }
    return @($cards | Sort-Object priority, id)
}

function Get-State {
    if (-not (Test-Path -LiteralPath $StateFile)) { return @() }
    $rows = foreach ($line in [IO.File]::ReadAllLines($StateFile, $Utf8)) {
        $f = $line -split "`t"
        if ($f.Count -ge 3) {
            [pscustomobject]@{ id = $f[0]; when = $f[1]; outcome = $f[2]; builder = ($f + @('', '', ''))[3]
                               url = ($f + @('', '', '', ''))[4] }
        }
    }
    return @($rows)
}

function Add-State([string]$Id, [string]$Outcome, [string]$Who, [string]$Url) {
    $null = New-Item -ItemType Directory -Force -Path $DuoHome
    $line = "$Id`t$(Get-Date -Format 'yyyy-MM-dd HH:mm')`t$Outcome`t$Who`t$Url`n"
    [IO.File]::AppendAllText($StateFile, $line, $Utf8)
}

function Test-Skip([string]$Id) {
    $rows = @(Get-State | Where-Object { $_.id -eq $Id })
    if ($rows | Where-Object { $_.outcome -in @('merged', 'local-merged', 'pr-open', 'needs-bro') }) { return $true }
    return (@($rows | Where-Object { $_.outcome -eq 'failed' }).Count -ge 2)
}

function Set-CardStatus([string]$File, [string]$Value) {
    $t = Read-Text $File
    if ($t -match '(?m)^\*\*Status:\*\*') {
        $t = [regex]::Replace($t, '(?m)^\*\*Status:\*\*\s*[A-Za-z-]+', "**Status:** $Value")
    } else {
        $t = ([regex]'(?m)^(#\s+T-\d+.*)$').Replace($t, "`$1`n`n**Status:** $Value", 1)
    }
    Write-Text $File $t
}

# ------------------------------------------------------------------ AI calls
function Render-Prompt([string]$Name, [hashtable]$Vals) {
    $t = Read-Text (J $PromptDir "$Name.md")
    foreach ($k in $Vals.Keys) { $t = $t.Replace('{{' + $k + '}}', [string]$Vals[$k]) }
    return $t
}

function Invoke-Agent([string]$Agent, [string]$Role, [string]$PromptText, [string]$Wt, [string]$Tag) {
    $pf = J $script:RunDir "$Tag.prompt.md"
    $out = J $script:RunDir "$Tag.out.md"
    $log = J $script:RunDir "$Tag.log.txt"
    $err = J $script:RunDir "$Tag.err.txt"
    Write-Text $pf $PromptText
    if ($Role -eq 'review') { $timeout = $ReviewTimeoutMin } else { $timeout = $BuildTimeoutMin }
    Say "    $Agent ($Role) ... log: $Tag.*" 'DarkGray'
    Push-AgentEnv $Wt
    try {
        if ($Agent -eq 'claude') {
            if ($Role -eq 'review') { $settings = J $DuoDir 'claude-review.json' } else { $settings = J $DuoDir 'claude-build.json' }
            $a = @('-p', '--permission-mode', 'dontAsk', '--settings', $settings, '--output-format', 'text')
            if ($ClaudeModel) { $a += @('--model', $ClaudeModel) }
            if ($Role -eq 'review') { $a += @('--disallowedTools', 'Edit', 'Write', 'MultiEdit', 'NotebookEdit') }
            $code = Invoke-Native $script:ClaudeExe $a $Wt $pf $out $err $timeout
        } else {
            $attempt = 0
            do {
                $attempt++
                $a = @('exec')
                if ($Role -eq 'review') { $a += @('--sandbox', 'read-only') }
                elseif ($script:CodexFull) { $a += '--dangerously-bypass-approvals-and-sandbox' }
                else { $a += '--full-auto' }
                if ($CodexModel) { $a += @('-m', $CodexModel) }
                $a += @('-o', $out)
                $code = Invoke-Native $script:CodexExe $a $Wt $pf $log $err $timeout
                $retry = $false
                if ($code -ne 0 -and $code -ne 124 -and $Role -ne 'review' -and -not $script:CodexFull -and $attempt -eq 1 -and
                    ((Read-Text $err) + (Read-Text $log)) -match '(?i)sandbox') {
                    Say "    Codex sandbox is not available on this machine -> retrying with full access inside the worktree" 'Yellow'
                    $script:CodexFull = $true
                    $retry = $true
                }
            } while ($retry)
        }
    } finally { Pop-AgentEnv }
    $text = (Read-Text $out).Trim()
    $noise = (Read-Text $err) + "`n" + (Read-Text $log)
    if ($code -ne 0 -or -not $text) {
        if (($text + $noise) -match $QuotaRx) { throw 'DUO_QUOTA' }
        if (($text + $noise) -match $LoginRx) { throw "DUO_LOGIN:$Agent" }
    }
    return [pscustomobject]@{ code = $code; text = $text; timedOut = ($code -eq 124); err = (Tail-Text $noise 15 1500) }
}

function Invoke-Gate([string]$Wt, [string]$Tag) {
    $empty = J $script:RunDir 'empty.txt'
    Push-AgentEnv $Wt -Gate
    try {
        $o0 = J $script:RunDir "$Tag.import.txt"; $e0 = "$o0.err"
        $null = Invoke-Native $Py @('-c', 'import opstrail; print(opstrail.__file__)') $Wt $empty $o0 $e0 5
        $where = (Read-Text $o0).Trim()
        $o1 = J $script:RunDir "$Tag.pytest.txt"; $e1 = "$o1.err"
        $c1 = Invoke-Native $Py @('-m', 'pytest', '-p', 'no:cacheprovider') $Wt $empty $o1 $e1 $GateTimeoutMin
        $o2 = J $script:RunDir "$Tag.eval.txt"; $e2 = "$o2.err"
        $c2 = Invoke-Native $Py @('-m', 'opstrail', 'eval', '--out', $script:RunDir) $Wt $empty $o2 $e2 $GateTimeoutMin
    } finally { Pop-AgentEnv }
    $wtFull = (Resolve-Path -LiteralPath $Wt).Path
    $importOk = $where.ToLower().StartsWith($wtFull.ToLower())
    $pt = (Read-Text $o1) + "`n" + (Read-Text $e1)
    $ev = (Read-Text $o2) + "`n" + (Read-Text $e2)
    $ptLast = (@($pt -split "`r?`n" | Where-Object { $_ -match '(passed|failed|error|no tests ran)' }) | Select-Object -Last 1)
    $evScore = ([regex]::Match($ev, 'score \**(\d+/\d+)')).Groups[1].Value
    $ok = ($c1 -eq 0 -and $c2 -eq 0 -and $importOk)
    $summary = "pytest: $(if ($ptLast) { $ptLast.Trim() } else { "exit $c1" }) | eval: $(if ($evScore) { $evScore } else { "exit $c2" })"
    if (-not $importOk) { $summary += " | WRONG IMPORT PATH: opstrail loaded from '$where' instead of the worktree" }
    $detail = "$summary`n`n--- pytest (tail) ---`n$(Tail-Text $pt 40)`n`n--- eval (tail) ---`n$(Tail-Text $ev 25)"
    return [pscustomobject]@{ ok = $ok; summary = $summary; detail = $detail }
}

function Get-Verdict([string]$Text) {
    $m = [regex]::Matches($Text, '(?im)^[\s>*_`]*VERDICT:\s*[*_`]*\s*(APPROVE|CHANGES)')
    if ($m.Count -gt 0) { return $m[$m.Count - 1].Groups[1].Value.ToUpper() }
    if ($Text) { return 'CHANGES' }
    return 'NONE'
}

function Save-Round([string]$Wt, [string]$Agent, $Card, [int]$Round, [string]$Summary, [string]$HeadBefore) {
    $null = GitIn $Wt add -A -- . ':(exclude).tmp'
    $st = GitIn $Wt status --porcelain --untracked-files=no
    $head = GitIn $Wt rev-parse HEAD
    if (-not $st) { return ($head -ne $HeadBefore) }   # nothing staged; maybe the agent committed itself
    if ($Agent -eq 'claude') { $prefix = '[claude]'; $trailer = 'Co-Authored-By: Claude <noreply@anthropic.com>' }
    else { $prefix = '[gpt]'; $trailer = 'Co-Authored-By: Codex <noreply@openai.com>' }
    $subject = "$prefix $($Card.id): $($Card.title)"
    if ($Round -gt 1) { $subject += " (round $Round)" }
    $first = (@($Summary -split "`r?`n" | Where-Object { $_.Trim() }) | Select-Object -First 25) -join "`n"
    $msgFile = J $script:RunDir "commit-$Round.txt"
    Write-Text $msgFile "$subject`n`n$first`n`nDuo-Run: $($script:RunId)`n$trailer`n"
    $null = GitIn $Wt commit -q -F $msgFile
    return ($script:GitCode -eq 0)
}

# ------------------------------------------------------------------ GitHub
function Test-Gh {
    if (-not $script:GhExe) { return $false }
    & $script:GhExe auth status 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Gh([string]$Wt) {
    $rest = @($args)
    Push-Location -LiteralPath $Wt
    try { $o = & $script:GhExe @rest 2>&1 | ForEach-Object { "$_" } } finally { Pop-Location }
    $script:GhCode = $LASTEXITCODE
    return (($o -join "`n").Trim())
}

function Wait-Checks([string]$Wt, [string]$Branch) {
    $start = Get-Date
    $deadline = $start.AddMinutes($CiTimeoutMin)
    $poll = 30
    if ($env:OPSTRAIL_DUO_POLL) { $poll = [int]$env:OPSTRAIL_DUO_POLL }
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds $poll
        $json = Invoke-Gh $Wt pr checks $Branch --json 'name,bucket'
        $checks = $null
        try { if ($json.StartsWith('[')) { $checks = @($json | ConvertFrom-Json) } } catch { $checks = $null }
        if (-not $checks -or $checks.Count -eq 0) {
            if (((Get-Date) - $start).TotalMinutes -ge 3) { return 'none' }
            continue
        }
        if ($checks | Where-Object { $_.bucket -in @('fail', 'cancel') }) { return 'fail' }
        if (-not ($checks | Where-Object { $_.bucket -eq 'pending' })) { return 'pass' }
    }
    return 'timeout'
}

# ------------------------------------------------------------------ one task
function Invoke-Task($Card) {
    $id = $Card.id
    $b = $Card.owner
    if ($Builder -ne 'auto') { $b = $Builder }
    if ($b -eq 'claude') { $r = 'gpt' } else { $r = 'claude' }
    $exeName = @{ claude = 'Claude (Claude Code)'; gpt = 'GPT (Codex)' }
    $res = [pscustomobject]@{ id = $id; title = $Card.title; builder = $b; reviewer = $r; rounds = 0; verdict = '';
                              gate = ''; outcome = 'failed'; url = ''; note = '' }
    Step "$id $($Card.title)  [builder: $($exeName[$b]), reviewer: $($exeName[$r])]"

    # worktree + branch (fetch again: an earlier task of this run may have just been merged)
    if ($script:HasRemote) { $null = GitIn $Root fetch --prune origin }
    $wtRoot = J (Split-Path -Parent $Root) 'OpsTrail-duo'
    $null = New-Item -ItemType Directory -Force -Path $wtRoot
    $wt = J $wtRoot $id
    if (Test-Path -LiteralPath $wt) {
        $null = GitIn $Root worktree remove --force $wt
        if (Test-Path -LiteralPath $wt) { Remove-Item -LiteralPath $wt -Recurse -Force -ErrorAction SilentlyContinue }
    }
    $null = GitIn $Root worktree prune
    $branch = "duo/$id"; $n = 1
    while ($true) {
        $null = GitIn $Root rev-parse --verify --quiet "refs/heads/$branch"; $local = ($script:GitCode -eq 0)
        $null = GitIn $Root rev-parse --verify --quiet "refs/remotes/origin/$branch"; $remote = ($script:GitCode -eq 0)
        if (-not $local -and -not $remote) { break }
        $n++; $branch = "duo/$id-$n"
    }
    $o = GitIn $Root worktree add -b $branch $wt $script:Base
    if ($script:GitCode -ne 0) { $res.note = "git worktree add failed: $o"; return $res }
    $baseSha = GitIn $wt rev-parse HEAD
    $cardFile = J $wt ($Card.path -replace '/', [IO.Path]::DirectorySeparatorChar)

    $pyQ = '"' + $Py + '"'
    $vals = @{
        AGENT = $exeName[$b]; BUILDER = $exeName[$b]; REVIEWER = $exeName[$r]; TASK_ID = $id; TASK_TITLE = $Card.title
        CARD = $Card.path; BRANCH = $branch; BASE = $baseSha.Substring(0, 12)
        PYTEST = "$pyQ -m pytest"; EVAL = "$pyQ -m opstrail eval"
        ENVNOTE = ("Use the shared Python $pyQ (do not create a venv, do not pip install). The runner already set " +
                   "PYTHONPATH to this worktree's src, TEMP/TMP to .tmp in this worktree and OPSTRAIL_HOME to a " +
                   "throw-away folder. If your shell lost them, set PYTHONPATH=<this folder>/src yourself.")
    }

    $gate = $null; $review = ''; $verdict = ''; $buildText = ''
    for ($round = 1; $round -le $MaxRounds; $round++) {
        $res.rounds = $round
        if ($round -eq 1) { $p = Render-Prompt 'build' $vals }
        else {
            $v2 = $vals.Clone(); $v2.ROUND = $round; $v2.GATE = $gate.detail
            if ($review) { $v2.REVIEW = $review } else { $v2.REVIEW = '(no review this round - the gate failed; fix the gate first)' }
            $p = Render-Prompt 'fix' $v2
        }
        $headBefore = GitIn $wt rev-parse HEAD
        $tag = "$id-r$round-build"
        $ar = Invoke-Agent $b 'build' $p $wt $tag
        if ($ar.text) { $buildText = $ar.text }
        if ($ar.timedOut) { $res.note = "builder timed out in round $round" }
        elseif ($ar.code -ne 0) { $res.note = "builder exited with code $($ar.code) in round $round : $($ar.err)" }
        $changed = Save-Round $wt $b $Card $round $ar.text $headBefore
        if (-not $changed -and $round -eq 1) {
            if (-not $res.note) { $res.note = 'builder made no changes' }
            break
        }
        Say "    gate (pytest + eval) ..." 'DarkGray'
        $gate = Invoke-Gate $wt "$id-r$round-gate"
        $res.gate = $gate.summary
        Say "    $($gate.summary)" $(if ($gate.ok) { 'Green' } else { 'Yellow' })
        if (-not $gate.ok) {
            $review = ''
            if ($round -lt $MaxRounds) { continue }
            break
        }
        $vr = $vals.Clone(); $vr.AGENT = $exeName[$r]; $vr.GATE = $gate.detail
        $rv = Invoke-Agent $r 'review' (Render-Prompt 'review' $vr) $wt "$id-r$round-review"
        $review = $rv.text
        $verdict = Get-Verdict $review
        $res.verdict = $verdict
        Say "    review: $verdict" $(if ($verdict -eq 'APPROVE') { 'Green' } else { 'Yellow' })
        if ($verdict -eq 'APPROVE') { break }
        if ($verdict -eq 'NONE') { $res.note = "reviewer gave no answer: $($rv.err)"; break }
    }

    $approved = ($gate -and $gate.ok -and $verdict -eq 'APPROVE')
    if ($approved) {
        Set-CardStatus $cardFile 'done'
        $null = GitIn $wt add -A -- . ':(exclude).tmp'
        $msgFile = J $script:RunDir "commit-done.txt"
        Write-Text $msgFile "[duo] $($id): mark done (built by $($exeName[$b]), approved by $($exeName[$r]))`n`nDuo-Run: $($script:RunId)`n"
        $null = GitIn $wt commit -q -F $msgFile
    }
    $commits = GitIn $wt rev-list --count "$baseSha..HEAD"
    if ([int]$commits -eq 0) {
        $res.outcome = 'failed'
        Cleanup-Worktree $wt $branch $true
        return $res
    }

    # PR body
    $body = @(
        "Built by **$($exeName[$b])**, reviewed by **$($exeName[$r])** with ``scripts/duo.ps1`` (run $($script:RunId), $($res.rounds) round(s)).",
        "", "Task card: ``$($Card.path)``", "", "**Gate (pytest + eval on Bro's machine):** $($res.gate)",
        "", "**Review verdict:** $(if ($verdict) { $verdict } else { 'not reviewed (gate failed)' })",
        $(if ($res.note) { "`n**Note:** $($res.note)" } else { '' }),
        "", "## Builder summary", "", $buildText, "", "## Review", "", $(if ($review) { $review } else { '_none_' }),
        "", "<!-- duo -->"
    ) -join "`n"
    $bodyFile = J $script:RunDir "$id-pr.md"
    Write-Text $bodyFile $body
    if ($b -eq 'claude') { $pfx = '[claude]' } else { $pfx = '[gpt]' }
    $prTitle = "$pfx $id $($Card.title)"

    if ($script:HasRemote) {
        $o = GitIn $wt push -u origin $branch
        if ($script:GitCode -ne 0) { $res.note += " | push failed: $o"; $res.outcome = 'needs-bro'; return $res }
        if ($script:HasGh) {
            $url = Invoke-Gh $wt pr create --base $MainBranch --head $branch --title $prTitle --body-file $bodyFile --label duo
            $res.url = (@($url -split "`n" | Where-Object { $_ -match '^https?://' }) | Select-Object -Last 1)
            if (-not $res.url) { $res.note += " | gh pr create: $url" }
            if ($approved -and -not $NoMerge) {
                Say "    waiting for CI ..." 'DarkGray'
                $ci = Wait-Checks $wt $branch
                if ($ci -in @('pass', 'none')) {
                    $o = Invoke-Gh $wt pr merge $branch --squash --delete-branch
                    if ($script:GhCode -eq 0) { $res.outcome = 'merged' }
                    else { $res.outcome = 'needs-bro'; $res.note += " | merge failed: $o" }
                } else {
                    $res.outcome = 'needs-bro'; $res.note += " | CI: $ci"
                }
            } elseif ($approved) { $res.outcome = 'pr-open' }
            else { $res.outcome = 'needs-bro' }
            if ($res.outcome -eq 'needs-bro') { $null = Invoke-Gh $wt pr edit $branch --add-label needs-bro }
        } else {
            if ($approved) { $res.outcome = 'pr-open'; $res.note += ' | pushed; open the PR yourself (gh not logged in)' }
            else { $res.outcome = 'needs-bro' }
        }
    } else {
        if ($approved -and -not $NoMerge) {
            $cur = GitIn $Root rev-parse --abbrev-ref HEAD
            $dirty = GitIn $Root status --porcelain --untracked-files=no
            if ($cur -eq $MainBranch -and -not $dirty) {
                $o = GitIn $Root merge --ff-only $branch
                if ($script:GitCode -eq 0) { $res.outcome = 'local-merged' } else { $res.outcome = 'needs-bro'; $res.note += " | merge: $o" }
            } else { $res.outcome = 'pr-open'; $res.note += " | branch $branch kept (main has local changes or is not checked out)" }
        } elseif ($approved) { $res.outcome = 'pr-open' }
        else { $res.outcome = 'needs-bro' }
    }

    if ($res.outcome -eq 'merged' -or $res.outcome -eq 'local-merged') {
        $script:Changed += @((GitIn $wt diff --name-only "$baseSha..HEAD") -split "`n")
        Cleanup-Worktree $wt $branch $true
    } else {
        Cleanup-Worktree $wt $branch $false
    }
    return $res
}

function Cleanup-Worktree([string]$Wt, [string]$Branch, [bool]$DeleteBranch) {
    $null = GitIn $Root worktree remove --force $Wt
    if (Test-Path -LiteralPath $Wt) { Remove-Item -LiteralPath $Wt -Recurse -Force -ErrorAction SilentlyContinue }
    $null = GitIn $Root worktree prune
    if ($DeleteBranch) { $null = GitIn $Root branch -D $Branch }
}

function Update-LocalCopy {
    if ($NoDeploy) { return 'skipped (-NoDeploy)' }
    $cur = GitIn $Root rev-parse --abbrev-ref HEAD
    $dirty = GitIn $Root status --porcelain --untracked-files=no
    if ($cur -ne $MainBranch -or $dirty) { return "not updated: your copy is on '$cur' or has local changes - run git pull yourself" }
    if ($script:HasRemote) {
        $o = GitIn $Root pull --ff-only origin $MainBranch
        if ($script:GitCode -ne 0) { return "git pull failed: $o" }
    }
    $msg = 'updated'
    if ($script:Changed -contains 'pyproject.toml') {
        & $Py -m pip install -q -e "$($Root)[agent,dev]" 2>&1 | Out-Null
        $msg += ', dependencies reinstalled'
    }
    if ($IsWin) {
        & $Py -m opstrail restart 2>&1 | Out-Null
        $msg += ', agent restarted'
    }
    return $msg
}

# ------------------------------------------------------------------ commands
function Do-Setup {
    Step "Agent configs"
    $pairs = @(@((J $Root 'setup' 'claude' 'settings.json'), (J $Root '.claude' 'settings.json')),
               @((J $Root 'setup' 'codex' 'config.toml'), (J $Root '.codex' 'config.toml')))
    foreach ($pr in $pairs) {
        $dir = Split-Path -Parent $pr[1]
        $null = New-Item -ItemType Directory -Force -Path $dir
        if ((Test-Path -LiteralPath $pr[1]) -and -not $Force) { Say "    kept $($pr[1]) (use -Force to overwrite)" }
        else { Copy-Item -LiteralPath $pr[0] -Destination $pr[1] -Force; Say "    $($pr[1])" }
    }
    $null = New-Item -ItemType Directory -Force -Path $DuoHome
    $ok = $true
    Step "Tools and logins"
    if (-not (Test-Path -LiteralPath (J $Root '.git'))) { Say "    [!] not a git repo yet: run scripts\init-github.ps1 first" 'Yellow'; $ok = $false }
    elseif (-not (GitIn $Root config user.email)) { Say "    [!] git user.email not set (git config user.email you@example.com)" 'Yellow'; $ok = $false }
    else { Say "    [ok] git repo" 'Green' }
    if (Test-Path -LiteralPath $Py) { Say "    [ok] python $Py" 'Green' } else { Say "    [!] $Py missing: run scripts\install.ps1" 'Yellow'; $ok = $false }
    $c = Find-Tool 'claude' 'OPSTRAIL_DUO_CLAUDE'
    if ($c) { Say "    [ok] Claude Code: $c" 'Green'; Say "         login once with your Claude Pro/Max account: run 'claude', then /login (choose the subscription, not an API key)" }
    else { Say "    [!] Claude Code missing: irm https://claude.ai/install.ps1 | iex   (then: claude, /login)" 'Yellow'; $ok = $false }
    $x = Find-Tool 'codex' 'OPSTRAIL_DUO_CODEX'
    if ($x) {
        $null = New-Item -ItemType Directory -Force -Path $DuoHome
        $e0 = J $DuoHome 'empty.txt'; Write-Text $e0 ''
        $o0 = J $DuoHome 'codex-login.txt'
        $null = Invoke-Native $x @('login', 'status') $Root $e0 $o0 "$o0.err" 1
        $ls = ((Read-Text $o0) + ' ' + (Read-Text "$o0.err")).Trim() -replace '\s+', ' '
        Say "    [ok] Codex: $x  ($ls)" 'Green'
        if ($ls -notmatch '(?i)chatgpt') { Say "         run: codex login   (choose 'Sign in with ChatGPT', not an API key)" 'Yellow' }
    } else { Say "    [!] Codex missing: npm install -g @openai/codex   (then: codex login, Sign in with ChatGPT)" 'Yellow'; $ok = $false }
    $script:GhExe = Find-Tool 'gh' 'OPSTRAIL_DUO_GH'
    if (Test-Gh) {
        Say "    [ok] GitHub CLI logged in" 'Green'
        $null = Invoke-Gh $Root label create duo --color 5319e7 --description 'Built and reviewed by scripts/duo.ps1' --force
        $null = Invoke-Gh $Root label create needs-bro --color d93f0b --description 'Duo could not finish - Bro decides' --force
    } else { Say "    [i] GitHub CLI not logged in (optional, needed for PR + auto-merge): winget install GitHub.cli; gh auth login" 'Yellow' }
    foreach ($k in $KeyVars) {
        foreach ($scope in @('User', 'Machine')) {
            if ([Environment]::GetEnvironmentVariable($k, $scope)) {
                Say "    [i] $k is set ($scope). duo removes it for its runs; interactive claude/codex sessions would bill the API with it." 'Yellow'
            }
        }
    }
    if ($ok -and (Test-Path -LiteralPath (J $Root '.git'))) {
        Step "Sync this folder with GitHub (duo builds from origin/$MainBranch)"
        $null = GitIn $Root remote get-url origin
        $cur = GitIn $Root rev-parse --abbrev-ref HEAD
        if ($script:GitCode -ne 0 -or $cur -ne $MainBranch) { Say "    [i] skipped: not on '$MainBranch' or no remote" 'Yellow' }
        else {
            $pending = GitIn $Root status --porcelain
            if ($pending) {
                $null = GitIn $Root add -A
                $msgFile = J $DuoHome 'setup-commit.txt'
                Write-Text $msgFile "[bro] OpsTrail update (duo setup)`n"
                $null = GitIn $Root commit -q -F $msgFile
                Say "    committed local changes"
            }
            $o = GitIn $Root pull --rebase origin $MainBranch
            if ($script:GitCode -ne 0) { Say "    [!] git pull failed: $o" 'Yellow'; $ok = $false }
            else {
                $o = GitIn $Root push origin $MainBranch
                if ($script:GitCode -eq 0) { Say "    [ok] pushed to origin/$MainBranch" 'Green' } else { Say "    [!] git push failed: $o" 'Yellow'; $ok = $false }
            }
        }
    }
    if ($ok) { Say "`nReady. Try: .\scripts\duo.ps1 -DryRun   then   .\scripts\duo.ps1" 'Green' }
    return $ok
}

function Do-Status {
    Step "Task cards ($script:Base)"
    foreach ($c in (Get-Cards $script:Base)) {
        $last = @(Get-State | Where-Object { $_.id -eq $c.id }) | Select-Object -Last 1
        $extra = ''
        if ($last) { $extra = "  last run $($last.when): $($last.outcome) $($last.url)" }
        Say ("    {0,-6} {1,-10} {2,-7} {3}{4}" -f $c.id, $c.status, $c.owner, $c.title, $extra)
    }
    if ($IsWin) {
        $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($t) { Say "`n    schedule: $(($t.Triggers | Select-Object -First 1).StartBoundary)  ($($t.State))" }
        else { Say "`n    schedule: none (use -Schedule 22:30)" }
    }
    $lr = J $DuoHome 'last-run.md'
    if (Test-Path -LiteralPath $lr) { Say "    last run report: $lr" }
}

function Do-Schedule {
    if (-not $IsWin) { Say "Scheduling needs Windows Task Scheduler." 'Yellow'; return }
    if ($Unschedule) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Say "Removed scheduled task '$TaskName'." 'Green'
        return
    }
    $at = [datetime]::ParseExact($Schedule, 'HH:mm', [Globalization.CultureInfo]::InvariantCulture)
    $arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`" -MaxTasks $MaxTasks"
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -Daily -At $at
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 8) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description 'Claude Code + Codex build the next OpsTrail task cards (scripts/duo.ps1)' -Force | Out-Null
    Say "Scheduled '$TaskName' every day at $Schedule (up to $MaxTasks task(s) per night)." 'Green'
    Say "Leave the laptop on and plugged in (it may wake from sleep; it cannot run while shut down)."
}

# ------------------------------------------------------------------ main
if ($Setup) { if (Do-Setup) { exit 0 } else { exit 2 } }
if ($Schedule -or $Unschedule) { Do-Schedule; exit 0 }

$null = New-Item -ItemType Directory -Force -Path $DuoHome
if (-not (Test-Path -LiteralPath (J $Root '.git'))) { Say "Not a git repo: run scripts\init-github.ps1 first." 'Yellow'; exit 2 }
$null = GitIn $Root remote get-url origin
$script:HasRemote = ($script:GitCode -eq 0)
if ($script:HasRemote) { $null = GitIn $Root fetch --prune origin; $script:Base = "origin/$MainBranch" }
else { $script:Base = $MainBranch }
if ($Status) { Do-Status; exit 0 }

# pick tasks
$cards = Get-Cards $script:Base
if ($Task) {
    $todo = @($cards | Where-Object { $_.id -eq $Task.ToUpper() })
    if (-not $todo) { Say "Task card $Task not found in $script:Base." 'Yellow'; exit 2 }
} else {
    $todo = @($cards | Where-Object { $_.status -eq 'todo' -and -not (Test-Skip $_.id) } | Select-Object -First $MaxTasks)
}
if (-not $todo -or $todo.Count -eq 0) { Say "Nothing to do: no task card with '**Status:** todo' that duo has not tried yet." 'Green'; exit 0 }

if ($DryRun) {
    Step "Dry run ($script:Base)"
    foreach ($c in $todo) {
        $bb = $c.owner; if ($Builder -ne 'auto') { $bb = $Builder }
        Say "    $($c.id) $($c.title)  -> builder $bb, reviewer $(if ($bb -eq 'claude') { 'gpt' } else { 'claude' })"
    }
    exit 0
}

# lock
$lock = J $DuoHome 'run.lock'
if (Test-Path -LiteralPath $lock) {
    $old = (Read-Text $lock).Trim()
    if ($old -and (Get-Process -Id ([int]$old) -ErrorAction SilentlyContinue)) { Say "Another duo run is active (pid $old)." 'Yellow'; exit 0 }
}
Write-Text $lock "$PID"

$script:RunId = Get-Date -Format 'yyyyMMdd-HHmmss'
$script:RunDir = J $DuoHome 'logs' $script:RunId
$null = New-Item -ItemType Directory -Force -Path $script:RunDir
Write-Text (J $script:RunDir 'empty.txt') ''
$script:Changed = @()
try { Start-Transcript -Path (J $script:RunDir 'duo.log') -Force | Out-Null } catch { }

$results = @()
$stop = ''
try {
    $script:ClaudeExe = Find-Tool 'claude' 'OPSTRAIL_DUO_CLAUDE'
    $script:CodexExe = Find-Tool 'codex' 'OPSTRAIL_DUO_CODEX'
    $script:GhExe = Find-Tool 'gh' 'OPSTRAIL_DUO_GH'
    $script:HasGh = ($script:HasRemote -and (Test-Gh))
    $missing = @()
    if (-not $script:ClaudeExe) { $missing += 'claude' }
    if (-not $script:CodexExe) { $missing += 'codex' }
    if (-not (Test-Path -LiteralPath $Py)) { $missing += "python ($Py)" }
    if ($missing) { $stop = "missing: $($missing -join ', ') - run .\scripts\duo.ps1 -Setup" }
    else {
        foreach ($c in $todo) {
            try {
                $r = Invoke-Task $c
            } catch {
                $msg = "$_"
                if ($msg -eq 'DUO_QUOTA') { $stop = 'subscription usage limit reached - will continue next run' }
                elseif ($msg -like 'DUO_LOGIN:*') { $stop = "$($msg.Substring(10)) is not logged in - run .\scripts\duo.ps1 -Setup" }
                else { $stop = "error: $msg" }
                Add-State $c.id 'aborted' '' ''
                Cleanup-Worktree (J (Split-Path -Parent $Root) 'OpsTrail-duo' $c.id) '' $false
                break
            }
            $results += $r
            Add-State $r.id $r.outcome $r.builder $r.url
        }
    }
    $deploy = ''
    if ($results | Where-Object { $_.outcome -in @('merged', 'local-merged') }) { $deploy = Update-LocalCopy }
} finally {
    Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue
}

# report
$lines = @("# OpsTrail duo run $($script:RunId)", "")
foreach ($r in $results) {
    $lines += "- **$($r.id)** $($r.title): **$($r.outcome)** - builder $($r.builder), reviewer $($r.reviewer), rounds $($r.rounds), review $($r.verdict)"
    if ($r.gate) { $lines += "  - gate: $($r.gate)" }
    if ($r.url) { $lines += "  - PR: $($r.url)" }
    if ($r.note) { $lines += "  - note: $($r.note)" }
}
if ($deploy) { $lines += "", "Local copy: $deploy" }
if ($stop) { $lines += "", "Stopped: $stop" }
$lines += "", "Logs: $($script:RunDir)"
$report = $lines -join "`n"
Write-Text (J $DuoHome 'last-run.md') $report
Write-Text (J $script:RunDir 'report.md') $report
Say "`n$report"
try { Stop-Transcript | Out-Null } catch { }

$merged = @($results | Where-Object { $_.outcome -in @('merged', 'local-merged') }).Count
$bro = @($results | Where-Object { $_.outcome -in @('needs-bro', 'failed') }).Count
$short = (@($results | ForEach-Object { "$($_.id) $($_.outcome)" }) -join ', ')
if ($stop) { $short = "$short $stop".Trim() }
Notify 'OpsTrail duo' "merged $merged, needs you $bro. $short"
if ($stop -like 'subscription*') { exit 3 }
if ($stop -or $bro) { exit 1 }
exit 0
