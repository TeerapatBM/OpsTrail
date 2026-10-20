# Synthetic-only UI screenshots. Windows PowerShell 5.1; no browser downloads.
[CmdletBinding()]
param(
    [string]$Python = '',
    [string]$OutputDirectory = ''
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $Python) {
    $Python = Join-Path $repo '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $Python)) {
        $Python = Join-Path $PSScriptRoot '..\..\..\OpsTrail\.venv\Scripts\python.exe'
    }
}
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $PSScriptRoot '..\docs\design\screens' }
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

function Invoke-SnapshotCommand($Socket, [int]$Id, [string]$Method, $Params) {
    $json = @{ id = $Id; method = $Method; params = $Params } | ConvertTo-Json -Depth 10 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($json)
    $cancel = New-Object Threading.CancellationTokenSource(15000)
    try {
        $Socket.SendAsync([ArraySegment[byte]]::new($bytes), [Net.WebSockets.WebSocketMessageType]::Text,
            $true, $cancel.Token).GetAwaiter().GetResult() | Out-Null
        do {
            $stream = New-Object IO.MemoryStream
            try {
                do {
                    $buffer = New-Object byte[] 65536
                    $part = $Socket.ReceiveAsync([ArraySegment[byte]]::new($buffer), $cancel.Token).GetAwaiter().GetResult()
                    if ($part.MessageType -eq [Net.WebSockets.WebSocketMessageType]::Close) { throw 'DevTools socket closed.' }
                    $stream.Write($buffer, 0, $part.Count)
                } until ($part.EndOfMessage)
                $message = [Text.Encoding]::UTF8.GetString($stream.ToArray()) | ConvertFrom-Json
            } finally { $stream.Dispose() }
        } until ($message.id -eq $Id)
        if ($message.error) { throw ($message.error | ConvertTo-Json -Compress) }
        return $message.result
    } finally { $cancel.Dispose() }
}

function Save-PhoneSnapshot($BrowserProfile, $Url, $Target) {
    # Port 0 avoids collisions; Chromium writes its chosen loopback port into this isolated profile.
    $activePort = Join-Path $BrowserProfile 'DevToolsActivePort'
    for ($attempt = 0; $attempt -lt 100; $attempt++) {
        if (Test-Path -LiteralPath $activePort) { break }
        Start-Sleep -Milliseconds 100
    }
    if (-not (Test-Path -LiteralPath $activePort)) { throw 'DevTools did not become ready.' }
    $debugPort = [int](Get-Content -LiteralPath $activePort -TotalCount 1)
    $tabs = Invoke-RestMethod "http://127.0.0.1:$debugPort/json/list" -TimeoutSec 5
    $pageTab = @($tabs | Where-Object { $_.type -eq 'page' })[0]
    $socket = New-Object Net.WebSockets.ClientWebSocket
    $cancel = New-Object Threading.CancellationTokenSource(15000)
    try {
        $socket.ConnectAsync([Uri]$pageTab.webSocketDebuggerUrl, $cancel.Token).GetAwaiter().GetResult() | Out-Null
        Invoke-SnapshotCommand $socket 1 'Emulation.setDeviceMetricsOverride' @{
            width = 390; height = 844; deviceScaleFactor = 1; mobile = $true
        } | Out-Null
        Invoke-SnapshotCommand $socket 2 'Page.navigate' @{ url = $Url } | Out-Null
        # Wait for the SPA's asynchronous data/render work, not just document load.
        $readyExpression = "document.readyState === 'complete' && innerWidth === 390 && document.documentElement.scrollWidth <= 390 && (location.hash.startsWith('#/docs/') ? !!document.querySelector('#md')?.value : !!document.querySelector('#eps')?.children.length)"
        $loaded = $false
        for ($attempt = 0; $attempt -lt 80; $attempt++) {
            $state = Invoke-SnapshotCommand $socket (10 + $attempt) 'Runtime.evaluate' @{ expression = $readyExpression; returnByValue = $true }
            if ($state.result.value) { $loaded = $true; break }
            Start-Sleep -Milliseconds 100
        }
        if (-not $loaded) { throw 'Phone page did not render.' }
        Start-Sleep -Milliseconds 1000
        $result = Invoke-SnapshotCommand $socket 100 'Page.captureScreenshot' @{
            format = 'png'; captureBeyondViewport = $false
        }
        [IO.File]::WriteAllBytes($Target, [Convert]::FromBase64String($result.data))
    } finally {
        $socket.Dispose()
        $cancel.Dispose()
    }
}

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
                    $browserProfile = Join-Path $runRoot ([Guid]::NewGuid().ToString('N'))
                    $browserArgs = @('--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                        '--disable-background-networking', '--disable-component-update', '--hide-scrollbars',
                        '--force-device-scale-factor=1', "--user-data-dir=`"$browserProfile`"")
                    $phone = $size -eq '390,844'
                    if ($phone) { $browserArgs += @('--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1', 'about:blank') }
                    else { $browserArgs += @('--virtual-time-budget=4000', "--window-size=$size", "--screenshot=`"$target`"") }
                    if ($mode -eq 'dark') { $browserArgs += '--force-dark-mode' }
                    else { $browserArgs += '--force-color-profile=srgb' }
                    $url = "$base/?snapshot_theme=$mode$($pages[$page])"
                    if (-not $phone) { $browserArgs += "`"$url`"" }
                    $proc = Start-Process -FilePath $browser -ArgumentList $browserArgs -WindowStyle Hidden -PassThru `
                        -RedirectStandardOutput (Join-Path $runRoot 'browser.out') -RedirectStandardError (Join-Path $runRoot 'browser.err')
                    if ($phone) {
                        try { Save-PhoneSnapshot $browserProfile $url $target }
                        catch { Write-Warning "Phone capture failed: $_" }
                        finally { if (-not $proc.HasExited) { $proc.Kill(); $proc.WaitForExit(5000) | Out-Null } }
                    } elseif (-not $proc.WaitForExit(45000)) { $proc.Kill() }
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
