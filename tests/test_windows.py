"""Tests that only run on Windows (the CI windows-latest runner and Bro's laptop)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell 5.1 not found")
def test_ui_snapshot_launcher_is_ascii_and_parses():
    path = REPO / 'scripts/ui-snapshots.ps1'
    path.read_bytes().decode('ascii')
    # Parse without executing: no browser, Python launcher, real profile or display needed.
    quoted = str(path).replace("'", "''")
    script = ("$tokens=$null; $errors=$null; "
              f"[System.Management.Automation.Language.Parser]::ParseFile('{quoted}', "
              "[ref]$tokens, [ref]$errors) | Out-Null; "
              "if ($errors.Count) { $errors | Out-String | Write-Error; exit 1 }")
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                   check=True, timeout=15, capture_output=True)


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell 5.1 not found")
def test_ui_snapshot_launcher_matrix_and_environment(tmp_path):
    """Run the launcher with fake processes; no browser or real user home."""
    launcher = str(REPO / 'scripts/ui-snapshots.ps1').replace("'", "''")
    output = str(tmp_path / 'screens').replace("'", "''")
    python = sys.executable.replace("'", "''")
    script = r'''
$ErrorActionPreference = 'Stop'
$env:OPSTRAIL_HOME = 'sentinel-home'
$env:PYTHONPATH = 'sentinel-path'
$env:OPSTRAIL_NO_CAPTURE = 'sentinel-capture'
$global:shots = 0
$global:phones = 0
$global:stopped = $false
$global:originalNewObject = Get-Command New-Object -CommandType Cmdlet
# Fake only the browser transport; execute the real CDP sequencing and message framing.
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Net.WebSockets;
public class SnapshotSocket {
    public static List<string> Commands = new List<string>();
    public static int Disposed;
    string reply;
    int offset;
    bool eventPending;
    public Task ConnectAsync(Uri uri, CancellationToken token) { return Task.FromResult(0); }
    public Task SendAsync(ArraySegment<byte> bytes, WebSocketMessageType kind, bool end, CancellationToken token) {
        var command = Encoding.UTF8.GetString(bytes.Array, bytes.Offset, bytes.Count);
        Commands.Add(command);
        var id = System.Text.RegularExpressions.Regex.Match(command, "\"id\":(\\d+)").Groups[1].Value;
        string result = "{}";
        if (command.Contains("Runtime.evaluate")) result = "{\"result\":{\"value\":true}}";
        if (command.Contains("Page.captureScreenshot")) result = "{\"data\":\"" + Convert.ToBase64String(new byte[2048]) + "\"}";
        reply = "{\"id\":" + id + ",\"result\":" + result + "}";
        offset = 0;
        eventPending = true;
        return Task.FromResult(0);
    }
    public Task<WebSocketReceiveResult> ReceiveAsync(ArraySegment<byte> buffer, CancellationToken token) {
        if (eventPending) {
            var ev = Encoding.UTF8.GetBytes("{\"method\":\"Page.frameNavigated\"}");
            Array.Copy(ev, 0, buffer.Array, buffer.Offset, ev.Length);
            eventPending = false;
            return Task.FromResult(new WebSocketReceiveResult(ev.Length, WebSocketMessageType.Text, true));
        }
        var data = Encoding.UTF8.GetBytes(reply);
        int count = Math.Min(512, data.Length - offset);
        Array.Copy(data, offset, buffer.Array, buffer.Offset, count);
        offset += count;
        return Task.FromResult(new WebSocketReceiveResult(count, WebSocketMessageType.Text, offset == data.Length));
    }
    public void Dispose() { Disposed++; }
}
'@
function New-Object {
    param($TypeName, [Parameter(ValueFromRemainingArguments=$true)]$ArgumentList)
    if ($TypeName -eq 'Net.WebSockets.ClientWebSocket') { return [SnapshotSocket]::new() }
    & $global:originalNewObject $TypeName @ArgumentList
}
function Invoke-RestMethod {
    param($Uri, $TimeoutSec)
    if ($Uri -notlike 'http://127.0.0.1:*/json/list') { throw 'Non-loopback DevTools' }
    # Invoke-RestMethod returns a JSON array as a single pipeline object in PowerShell 5.1.
    return ,@([pscustomobject]@{ type = 'service_worker'; webSocketDebuggerUrl = 'ws://127.0.0.1:9222/devtools/worker/1' },
              [pscustomobject]@{ type = 'page'; webSocketDebuggerUrl = 'ws://127.0.0.1:9222/devtools/page/1' })
}
$global:originalTestPath = Get-Command Test-Path -CommandType Cmdlet
function Test-Path {
    param([string]$LiteralPath)
    if ($LiteralPath -like '*\msedge.exe') { return $true }
    & $global:originalTestPath -LiteralPath $LiteralPath
}
function Invoke-WebRequest { return @{ StatusCode = 200 } }
function Stop-Process { $global:stopped = $true }
function Start-Process {
    param($FilePath, $ArgumentList, $WindowStyle, [switch]$PassThru,
          $RedirectStandardOutput, $RedirectStandardError)
    if ($WindowStyle -ne 'Hidden') { throw 'Visible helper' }
    if ($ArgumentList -contains '--home') {
        if ($env:OPSTRAIL_HOME -notlike '*ui-snapshots-*\home') { throw 'Home isolation lost' }
        $index = [Array]::IndexOf($ArgumentList, '--ready')
        $ready = $ArgumentList[$index + 1].Trim('"')
        '{"date":"2026-10-19","session_id":7}' | Set-Content -LiteralPath $ready -Encoding ASCII
        return [pscustomobject]@{ HasExited = $false; Id = 1234567 }
    }
    if (-not ($ArgumentList -contains '--headless')) { throw 'Missing headless' }
    if ($ArgumentList -contains '--window-size=390,844') { throw 'Phone needs device emulation, not window cropping' }
    if ($ArgumentList -contains '--remote-debugging-port=0') {
        if (-not ($ArgumentList -contains '--remote-debugging-address=127.0.0.1')) { throw 'DevTools not loopback' }
        if (-not ($ArgumentList -contains 'about:blank')) { throw 'Navigation before emulation' }
        if (@($ArgumentList | Where-Object { $_ -like '--screenshot=*' }).Count) { throw 'Phone uses window screenshot' }
        $profileArg = @($ArgumentList | Where-Object { $_ -like '--user-data-dir=*' })[0]
        $isolatedProfile = $profileArg.Substring(16).Trim('"')
        New-Item -ItemType Directory -Path $isolatedProfile | Out-Null
        '9222' | Set-Content -LiteralPath (Join-Path $isolatedProfile 'DevToolsActivePort') -Encoding ASCII
        $global:phones++
        $proc = [pscustomobject]@{ HasExited = $false }
        $proc | Add-Member ScriptMethod Kill { $this.HasExited = $true }
        $proc | Add-Member ScriptMethod WaitForExit { param($ms) return $true }
        return $proc
    }
    $shot = @($ArgumentList | Where-Object { $_ -like '--screenshot=*' })[0].Substring(13).Trim('"')
    if ($shot -like '*-dark-*' -and -not ($ArgumentList -contains '--force-dark-mode')) { throw 'Missing dark flag' }
    if (-not @($ArgumentList | Where-Object { $_ -like '--user-data-dir=*ui-snapshots-*' }).Count) { throw 'Real browser profile' }
    [IO.File]::WriteAllBytes($shot, (New-Object byte[] 2048))
    $global:shots++
    $proc = [pscustomobject]@{}
    $proc | Add-Member ScriptMethod WaitForExit { param($ms) return $true }
    return $proc
}
'''
    script += f"\n& '{launcher}' -Python '{python}' -OutputDirectory '{output}'\n"
    script += r'''
if ($global:shots -ne 12 -or $global:phones -ne 4) { throw "Wrong matrix: $global:shots desktop, $global:phones phone" }
if ([SnapshotSocket]::Disposed -ne 4) { throw 'Phone sockets not disposed' }
$commands = @([SnapshotSocket]::Commands | ForEach-Object { $_ | ConvertFrom-Json })
for ($i = 0; $i -lt 4; $i++) {
    $metrics, $navigate, $ready, $capture = $commands[($i * 4)..($i * 4 + 3)]
    if ($metrics.method -ne 'Emulation.setDeviceMetricsOverride' -or $metrics.params.width -ne 390 -or
        $metrics.params.height -ne 844 -or $metrics.params.deviceScaleFactor -ne 1 -or
        $metrics.params.mobile -ne $true) { throw 'Wrong phone metrics' }
    if ($navigate.method -ne 'Page.navigate' -or $navigate.params.url -notlike 'http://127.0.0.1:*/?snapshot_theme=*') { throw 'Wrong phone navigation' }
    if ($ready.method -ne 'Runtime.evaluate' -or $ready.params.expression -notlike '*innerWidth === 390*' -or
        $ready.params.expression -notlike '*scrollWidth <= 390*') { throw 'Missing render/width wait' }
    if ($capture.method -ne 'Page.captureScreenshot' -or $capture.params.captureBeyondViewport -ne $false) { throw 'Wrong screenshot method' }
}
if (-not $global:stopped) { throw 'Server not stopped' }
if ($env:OPSTRAIL_HOME -ne 'sentinel-home' -or $env:PYTHONPATH -ne 'sentinel-path' -or
    $env:OPSTRAIL_NO_CAPTURE -ne 'sentinel-capture') { throw 'Environment not restored' }
'''
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(list((tmp_path / 'screens').glob('*.png'))) == 16
    manifest = json.loads((tmp_path / 'screens/manifest.json').read_text(encoding='ascii'))
    assert manifest['source'] == 'evals/days (synthetic only)'
    assert set(manifest['files']) == {p.name for p in (tmp_path / 'screens').glob('*.png')}
    for phone in (tmp_path / 'screens').glob('*390x844.png'):
        assert phone.read_bytes() == bytes(2048)  # Decoded CDP payload, not a CLI screenshot.


def test_voice_windows_hotkey_uses_popup(svc, monkeypatch):
    from opstrail.agent import daemon, hotkeys
    from opstrail.agent.hotkeys import win_combo
    cfg = svc.cfg
    cfg.data["web"]["enabled"] = False
    seen = []
    monkeypatch.setattr(daemon, "setup_logging", lambda cfg: None)
    monkeypatch.setattr(daemon, "acquire_lock", lambda cfg: True)
    monkeypatch.setattr(daemon, "release_lock", lambda cfg: None)
    monkeypatch.setattr(daemon, "OpsTrail", lambda cfg: svc)
    monkeypatch.setattr(daemon.osapi, "set_dpi_aware", lambda: None)
    monkeypatch.setattr(daemon.osapi, "spawn_popup", lambda args: seen.append(args))
    monkeypatch.setattr(daemon.Agent, "run", lambda self: None)

    def register(bindings):
        assert win_combo(cfg.hotkeys["voice"]) == (3, ord("V"))
        bindings[cfg.hotkeys["voice"]]()

    monkeypatch.setattr(hotkeys, "start", register)
    assert daemon.run_agent(cfg) == 0
    assert seen == [["voice"]]


def test_tray_windows_thread_and_status_images(svc, monkeypatch):
    """Exercise Windows thread lifecycle + real Pillow images without a desktop."""
    import threading
    from types import SimpleNamespace
    pytest.importorskip("PIL.Image")
    from opstrail.agent.daemon import Agent
    from opstrail.agent.tray import Tray

    ready, stopped = threading.Event(), threading.Event()

    class Icon:
        def __init__(self, name, image, title, menu):
            self.icon = image

        def run(self, setup):
            setup(self)
            ready.set()
            stopped.wait(3)

        def stop(self):
            stopped.set()

        def update_menu(self):
            pass

    monkeypatch.setitem(sys.modules, "pystray", SimpleNamespace(
        Icon=Icon, Menu=lambda *items: items, MenuItem=lambda *args: args,
    ))
    tray = Tray(Agent(svc))
    tray.start()
    try:
        assert ready.wait(2)
        assert tray.icon.icon.getpixel((32, 32)) == (34, 197, 94, 255)
        svc.cfg.set_paused(True)
        tray.poll()
        assert tray.icon.icon.getpixel((32, 32)) == (128, 128, 128, 255)
    finally:
        tray.stop()
    assert not tray.thread.is_alive()


def test_dpapi_roundtrip():
    from opstrail.secretstore import protect, unprotect

    token = protect("sk-ant-test-123")
    assert token.startswith("dpapi:") and "sk-ant" not in token
    assert unprotect(token) == "sk-ant-test-123"


def test_teams_webhook_dpapi_storage(cfg, svc):
    import json
    from opstrail import teams

    url = "https://example.com/workflows/test?sig=synthetic-secret"
    assert svc.save_recap_settings(url) == {"has_webhook": True}
    data = json.loads((cfg.home / "recap.json").read_text(encoding="utf-8"))
    assert data["teams_webhook_url"].startswith("dpapi:")
    assert url not in json.dumps(data)
    assert teams.webhook_url(cfg) == url


def test_winapi_calls_do_not_crash():
    from opstrail.agent import winapi

    winapi.set_dpi_aware()
    assert winapi.idle_seconds() >= 0
    fg = winapi.foreground()
    assert fg is None or {"app", "title", "pid", "hwnd"} <= set(fg)
    assert winapi.window_rect(0) is None


def test_top_level_windows_finds_a_visible_window():
    from opstrail.agent import winapi

    wins = winapi.top_level_windows()
    assert isinstance(wins, list)
    assert all(isinstance(app, str) and app and isinstance(title, str) and title for app, title in wins)
    try:
        import tkinter

        root = tkinter.Tk()
    except Exception as exc:  # runner without an interactive desktop / Tk
        pytest.skip(f"no desktop: {exc}")
    title = f"OpsTrail test window {os.getpid()}"
    try:
        root.title(title)
        root.geometry("120x60")
        root.update()
        found = [app for app, t in winapi.top_level_windows() if t == title]
    finally:
        root.destroy()
    assert found and found[0].lower().startswith("python"), found


def test_register_hotkey_thread_starts_and_stops():
    from opstrail.agent.hotkeys import WinHotkeys

    worker = WinHotkeys({"<ctrl>+<alt>+<shift>+f24": lambda: None})
    worker.start()
    assert worker.ready.wait(5)
    worker.stop()
    worker.join(5)
    assert not worker.is_alive()


def test_screenshot_of_primary_monitor(cfg, tmp_path):
    from opstrail.agent.screenshot import capture

    try:
        path = capture(cfg, None, mode="screen", path=tmp_path / "s.png")
    except Exception as exc:  # runner without an interactive desktop
        pytest.skip(f"no desktop: {exc}")
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell 5.1 not found")
def test_powershell_51_hook_end_to_end(cfg, svc):
    """Dot-source the real hook in Windows PowerShell 5.1, simulate two commands, ingest, check."""
    hook = REPO / "hooks" / "powershell" / "OpsTrail.ps1"
    script = f"""
$ErrorActionPreference = 'Stop'
. '{hook}'
$t = Get-Date
Add-History -InputObject ([pscustomobject]@{{CommandLine='Get-Service splunkd'; ExecutionStatus='Completed'; StartExecutionTime=$t; EndExecutionTime=$t.AddSeconds(2)}})
prompt | Out-Null
Add-History -InputObject ([pscustomobject]@{{CommandLine='ConvertTo-SecureString "P@ssw0rd!" -AsPlainText -Force'; ExecutionStatus='Completed'; StartExecutionTime=$t.AddSeconds(5); EndExecutionTime=$t.AddSeconds(6)}})
prompt | Out-Null
prompt | Out-Null
"""
    env = {**os.environ, "OPSTRAIL_HOME": str(cfg.home)}
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    time.sleep(0.2)
    svc.refresh()
    shells = [e for e in svc.store.events_for_date(cfg.today()) if e["type"] == "shell"]
    cmds = [e["data"]["cmd"] for e in shells]
    assert cmds[0] == "Get-Service splunkd" and len(cmds) == 2, cmds  # no duplicate from the 3rd prompt
    assert "P@ssw0rd!" not in cmds[1] and "[REDACTED]" in cmds[1]
    assert shells[0]["duration_s"] == pytest.approx(2, abs=0.1)
    assert shells[0]["data"]["shell"].startswith("powershell 5.1")
    assert "output" not in shells[0]["data"]  # output capture is opt-in
    assert not (cfg.home / "transcripts").exists()


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell 5.1 not found")
def test_powershell_51_hook_captures_output(home):
    """T-106: with [capture] shell_output = true the hook transcribes the session and attaches each command's output."""
    from opstrail.config import load_config
    from opstrail.service import OpsTrail

    with (home / "config.toml").open("a", encoding="utf-8") as fh:
        fh.write("\n[capture]\nshell_output = true   # opt-in\nshell_output_lines = 15\n")
    cfg = load_config(home)
    hook = REPO / "hooks" / "powershell" / "OpsTrail.ps1"
    # Output is written to the host (and so to the transcript) before each command's history entry + prompt,
    # like an interactive session; the console host also echoes "PS C:\work> <command>" first.
    script = f"""
$ErrorActionPreference = 'Stop'
. '{hook}'
if (-not $global:OpsTrailTranscript) {{ throw 'transcript not started' }}
$t = Get-Date
$host.UI.WriteLine('PS C:\\work> Get-Service splunkd')
'Status   Name               DisplayName'
'------   ----               -----------'
'Running  splunkd            Splunkd Service'
Add-History -InputObject ([pscustomobject]@{{CommandLine='Get-Service splunkd'; ExecutionStatus='Completed'; StartExecutionTime=$t; EndExecutionTime=$t.AddSeconds(1)}})
prompt | Out-Null
1..40 | ForEach-Object {{ "log line $_" }}
Add-History -InputObject ([pscustomobject]@{{CommandLine='Get-Content splunkd.log -Tail 40'; ExecutionStatus='Completed'; StartExecutionTime=$t.AddSeconds(5); EndExecutionTime=$t.AddSeconds(6)}})
prompt | Out-Null
'SPLUNK_HOST=10.10.20.5'
'SPLUNK_PASSWORD=Pa55w0rd!Uf'
'admin password: Pa55w0rd!Uf'
Add-History -InputObject ([pscustomobject]@{{CommandLine='Get-Content .\\uf.env'; ExecutionStatus='Completed'; StartExecutionTime=$t.AddSeconds(10); EndExecutionTime=$t.AddSeconds(11)}})
prompt | Out-Null
Add-History -InputObject ([pscustomobject]@{{CommandLine='Set-Location C:\\work'; ExecutionStatus='Completed'; StartExecutionTime=$t.AddSeconds(15); EndExecutionTime=$t.AddSeconds(15)}})
prompt | Out-Null
prompt | Out-Null
"""
    env = {**os.environ, "OPSTRAIL_HOME": str(cfg.home)}
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    svc = OpsTrail(cfg)
    try:
        svc.refresh()
        shells = [e for e in svc.store.events_for_date(cfg.today()) if e["type"] == "shell"]
        by_cmd = {e["data"]["cmd"]: e["data"] for e in shells}
        assert len(shells) == 4, list(by_cmd)

        svc_out = by_cmd["Get-Service splunkd"]["output"]
        assert svc_out.splitlines()[0].startswith("Status") and "PS C:\\work>" not in svc_out
        assert "Running  splunkd" in svc_out and "output_truncated" not in by_cmd["Get-Service splunkd"]

        log = by_cmd["Get-Content splunkd.log -Tail 40"]
        assert log["output"].splitlines() == [f"log line {i}" for i in range(1, 16)]  # first 15 lines only
        assert log["output_truncated"] is True

        env_out = by_cmd["Get-Content .\\uf.env"]["output"]
        assert "Pa55w0rd!Uf" not in env_out and env_out.count("[REDACTED]") == 2
        assert "SPLUNK_HOST=10.10.20.5" in env_out and "log line" not in env_out

        assert "output" not in by_cmd["Set-Location C:\\work"]  # no output -> no field
    finally:
        svc.store.close()
    # the transcript holds raw (unredacted) output: removed when the shell exits
    assert list((cfg.home / "transcripts").glob("*.txt")) == []


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell 5.1 not found")
def test_powershell_51_hook_does_not_transcribe_while_paused(home):
    """T-106 review: a shell started paused never transcribes; pausing later stops and deletes the transcript."""
    from opstrail.config import load_config
    from opstrail.service import OpsTrail

    with (home / "config.toml").open("a", encoding="utf-8") as fh:
        fh.write("\n[capture]\nshell_output = true\n")
    cfg = load_config(home)
    paused = cfg.home / "paused"
    paused.write_text("", encoding="utf-8")
    hook = REPO / "hooks" / "powershell" / "OpsTrail.ps1"
    script = f"""
$ErrorActionPreference = 'Stop'
$flag = '{paused}'
$tdir = '{cfg.home / "transcripts"}'
function Assert-NoTranscript($where) {{
    if ($global:OpsTrailTranscript) {{ throw "transcript running $where" }}
    if (@(Get-ChildItem -LiteralPath $tdir -Filter *.txt -ErrorAction SilentlyContinue).Count) {{ throw "transcript file $where" }}
}}
function Run($cmd, $sec) {{
    Add-History -InputObject ([pscustomobject]@{{CommandLine=$cmd; ExecutionStatus='Completed'; StartExecutionTime=$t.AddSeconds($sec); EndExecutionTime=$t.AddSeconds($sec)}})
    prompt | Out-Null
}}
. '{hook}'
$t = Get-Date
Assert-NoTranscript 'at start-up while paused'
'STARTUP-PAUSED-SECRET'
Run 'cmd-a-paused' 1
Assert-NoTranscript 'after a paused command'
Remove-Item -LiteralPath $flag
Run 'cmd-b-resume' 2
if (-not $global:OpsTrailTranscript) {{ throw 'transcript not started after resume' }}
'visible output c'
Run 'cmd-c' 3
New-Item -ItemType File -Path $flag | Out-Null
'PAUSED-LATER-SECRET'
Run 'cmd-d-paused' 4
Assert-NoTranscript 'after pausing'
'MORE-PAUSED-SECRET'
Run 'cmd-e-paused' 5
Assert-NoTranscript 'while paused'
Remove-Item -LiteralPath $flag
Run 'cmd-f-resume' 6
'visible output g'
Run 'cmd-g' 7
"""
    env = {**os.environ, "OPSTRAIL_HOME": str(cfg.home)}
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    svc = OpsTrail(cfg)
    try:
        svc.refresh()
        shells = [e for e in svc.store.events_for_date(cfg.today()) if e["type"] == "shell"]
        by_cmd = {e["data"]["cmd"]: e["data"] for e in shells}
        assert list(by_cmd) == ["cmd-b-resume", "cmd-c", "cmd-f-resume", "cmd-g"]
        assert by_cmd["cmd-c"]["output"] == "visible output c"
        assert by_cmd["cmd-g"]["output"] == "visible output g"
        assert "output" not in by_cmd["cmd-b-resume"] and "output" not in by_cmd["cmd-f-resume"]
        assert "SECRET" not in repr(shells)
    finally:
        svc.store.close()
    assert list((cfg.home / "transcripts").glob("*.txt")) == []


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell 5.1 not found")
def test_powershell_51_lazy_transcript_header(cfg):
    """A lazily created transcript may begin with a UTF-8 BOM, including after resume."""
    hook = REPO / "hooks" / "powershell" / "OpsTrail.ps1"
    script = f"""
$ErrorActionPreference = 'Stop'
. '{hook}'
$file = Join-Path $global:OpsTrailHome 'lazy-transcript.txt'
try {{
    foreach ($bom in @($false, $true)) {{
        $text = "**********************`r`nWindows PowerShell transcript start`r`n**********************`r`nvisible output`r`n"
        [IO.File]::WriteAllText($file, $text, (New-Object Text.UTF8Encoding($bom)))
        $global:OpsTrailTranscript = $file
        $global:OpsTrailTranscriptPos = -1
        $output = Read-OpsTrailTranscript
        if ($output -ne "visible output`r`n") {{ throw "lost lazy transcript output (BOM=$bom)" }}
        if (Read-OpsTrailTranscript) {{ throw 'output read twice' }}
    }}
}} finally {{
    $global:OpsTrailTranscript = $null
    Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue
}}
"""
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, env={**os.environ, "OPSTRAIL_HOME": str(cfg.home)}, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
