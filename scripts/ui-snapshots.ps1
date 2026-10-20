# Synthetic-only UI screenshots. Windows PowerShell 5.1; no browser downloads.
[CmdletBinding()]
param(
    [string]$Python = '',
    [string]$OutputDirectory = ''
)
$ErrorActionPreference = 'Stop'
if (-not $Python) { $Python = Join-Path $PSScriptRoot '..\..\..\OpsTrail\.venv\Scripts\python.exe' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $PSScriptRoot '..\docs\design\screens' }
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$output = [IO.Path]::GetFullPath($OutputDirectory)
$candidates = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
)
$browsers = @($candidates | Where-Object { Test-Path -LiteralPath $_ })
if (-not $browsers.Count) { throw 'Install Microsoft Edge or Google Chrome to capture UI screenshots.' }
if (-not (Test-Path -LiteralPath $Python)) { throw 'Shared Python not found. Pass -Python with the existing OpsTrail venv interpreter.' }
New-Item -ItemType Directory -Force -Path $output | Out-Null
$scratch = Join-Path $repo '.tmp'
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
$runRoot = Join-Path $scratch ('ui-snapshots-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $runRoot | Out-Null
$ready = Join-Path $runRoot 'ready.json'
$oldHome = $env:OPSTRAIL_HOME
$oldPath = $env:PYTHONPATH
$oldCapture = $env:OPSTRAIL_NO_CAPTURE
$server = $null
# Ask the OS for a free loopback port; the server still validates Host and write headers.
$listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0)
$listener.Start()
$port = $listener.LocalEndpoint.Port
$listener.Stop()
try {
    $env:OPSTRAIL_HOME = Join-Path $runRoot 'home'
    $env:OPSTRAIL_NO_CAPTURE = '1'
    $env:PYTHONPATH = Join-Path $repo 'src'
    $serverArgs = @(('"' + (Join-Path $PSScriptRoot 'ui_snapshot_server.py') + '"'),
        '--home', ('"' + $env:OPSTRAIL_HOME + '"'), '--ready', ('"' + $ready + '"'), '--port', "$port")
    $server = Start-Process -FilePath $Python -ArgumentList $serverArgs -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runRoot 'server.out') -RedirectStandardError (Join-Path $runRoot 'server.err')
    $base = "http://127.0.0.1:$port"
    $healthy = $false
    for ($i = 0; $i -lt 100; $i++) {
        if ($server.HasExited) { throw "Snapshot server exited. See $runRoot\server.err" }
        try {
            $response = Invoke-WebRequest "$base/api/status" -UseBasicParsing -TimeoutSec 1
            if ($response.StatusCode -eq 200 -and (Test-Path -LiteralPath $ready)) { $healthy = $true; break }
        } catch { Start-Sleep -Milliseconds 200 }
    }
    if (-not $healthy) { throw "Snapshot server did not become ready. See $runRoot\server.err" }
    $data = Get-Content -LiteralPath $ready -Raw | ConvertFrom-Json
    $pages = [ordered]@{
        day = "#/day/$($data.date)"
        worklogs = '#/worklogs'
        docs = '#/docs'
        editor = "#/docs/$($data.session_id)"
        search = '#/search?q=Splunk'
        settings = '#/settings'
    }
    $written = @()
    foreach ($mode in @('light', 'dark')) {
        foreach ($page in $pages.Keys) {
            $sizes = @('1440,900')
            if ($page -in @('day', 'editor')) { $sizes += '390,844' }
            foreach ($size in $sizes) {
                $name = "$page-$mode-$($size.Replace(',', 'x')).png"
                $target = Join-Path $output $name
                if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target }
                $captured = $false
                foreach ($browser in $browsers) {
                    # Each invocation gets a new profile, so a saved preference cannot defeat OS emulation.
                    $profile = Join-Path $runRoot ([Guid]::NewGuid().ToString('N'))
                    $browserArgs = @('--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                        '--disable-background-networking', '--disable-component-update', '--hide-scrollbars',
                        '--force-device-scale-factor=1', '--virtual-time-budget=4000',
                        "--window-size=$size", "--user-data-dir=`"$profile`"", "--screenshot=`"$target`"")
                    if ($mode -eq 'dark') { $browserArgs += '--force-dark-mode' }
                    else { $browserArgs += '--force-color-profile=srgb' }
                    $browserArgs += "`"$base/?snapshot_theme=$mode$($pages[$page])`""
                    $proc = Start-Process -FilePath $browser -ArgumentList $browserArgs -WindowStyle Hidden -PassThru `
                        -RedirectStandardOutput (Join-Path $runRoot 'browser.out') -RedirectStandardError (Join-Path $runRoot 'browser.err')
                    if (-not $proc.WaitForExit(45000)) { $proc.Kill() }
                    if ((Test-Path -LiteralPath $target) -and (Get-Item -LiteralPath $target).Length -gt 1000) {
                        $captured = $true; break
                    }
                }
                if (-not $captured) { throw "No screenshot produced for $name. See $runRoot\browser.err" }
                $written += $name
                Write-Host "Captured $name"
            }
        }
    }
    @{ source = 'evals/days (synthetic only)'; files = $written } | ConvertTo-Json | Set-Content -Encoding ASCII (Join-Path $output 'manifest.json')
} finally {
    if ($null -ne $server -and -not $server.HasExited) { Stop-Process -Id $server.Id -ErrorAction SilentlyContinue }
    $env:OPSTRAIL_HOME = $oldHome
    $env:PYTHONPATH = $oldPath
    $env:OPSTRAIL_NO_CAPTURE = $oldCapture
    # Keep the synthetic home, isolated profiles and logs for reproducibility; no recursive deletion.
    Write-Host "Synthetic run files: $runRoot"
}
