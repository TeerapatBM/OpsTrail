"""Tests that only run on Windows (the CI windows-latest runner and Bro's laptop)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")

REPO = Path(__file__).resolve().parents[1]


def test_dpapi_roundtrip():
    from opstrail.secretstore import protect, unprotect

    token = protect("sk-ant-test-123")
    assert token.startswith("dpapi:") and "sk-ant" not in token
    assert unprotect(token) == "sk-ant-test-123"


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
