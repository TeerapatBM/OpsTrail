"""Agent loop with fake OS functions (no display needed)."""

from __future__ import annotations

from datetime import datetime

import pytest

from opstrail.agent.daemon import Agent
from opstrail.agent.hotkeys import HotkeyMatcher, parse_combo, win_combo


class FakeOS:
    def __init__(self, t0: float):
        self.now = t0
        self.fg = {"app": "pwsh.exe", "title": "PowerShell", "pid": 1, "hwnd": 1}
        self.idle = 0.0
        self.wins: list[tuple[str, str]] = []

    def clock(self):
        return self.now

    def foreground(self):
        return self.fg

    def idle_seconds(self):
        return self.idle

    def windows(self):
        return list(self.wins)


@pytest.fixture()
def fake(cfg):
    t0 = datetime(2026, 10, 19, 9, 0, tzinfo=cfg.tz).timestamp()
    return FakeOS(t0)


def make_agent(svc, fake):
    return Agent(
        svc, foreground=fake.foreground, idle_seconds=fake.idle_seconds, clock=fake.clock, windows=fake.windows
    )


def windows(svc):
    return [e for e in svc.store.events_for_date("2026-10-19") if e["type"] == "window"]


def test_window_segments_idle_and_exclusions(svc, fake):
    agent = make_agent(svc, fake)
    agent.tick()                      # 09:00 start PowerShell
    fake.now += 120
    fake.fg = {"app": "msedge.exe", "title": "Splunk docs", "pid": 2, "hwnd": 2}
    agent.tick()                      # 09:02 switch -> PowerShell 120s flushed
    fake.now += 1
    fake.fg = {"app": "pwsh.exe", "title": "PowerShell", "pid": 1, "hwnd": 1}
    agent.tick()                      # 1s Edge flicker is dropped (min_window_s=3)
    fake.now += 60
    fake.fg = {"app": "LINE.exe", "title": "Chat", "pid": 3, "hwnd": 3}
    agent.tick()                      # excluded app -> flush, nothing recorded for LINE
    fake.now += 60
    fake.fg = {"app": "msedge.exe", "title": "Bank - InPrivate", "pid": 2, "hwnd": 2}
    agent.tick()                      # excluded title
    fake.now += 30
    fake.fg = {"app": "pwsh.exe", "title": "PowerShell", "pid": 1, "hwnd": 1}
    agent.tick()
    fake.now += 400
    fake.idle = 400                   # user went away 400s ago (threshold 300)
    agent.tick()
    fake.now += 30
    fake.idle = 1
    agent.tick()                      # back -> idle event recorded
    agent.flush(fake.now + 10)

    ws = windows(svc)
    # 09:00-09:02 pwsh, 09:02:01-09:03:01 pwsh, (pwsh focus at 09:05:01 went idle immediately -> 0s, dropped),
    # pwsh again after returning from idle
    assert [w["data"]["app"] for w in ws] == ["pwsh.exe", "pwsh.exe", "pwsh.exe"]
    assert round(ws[0]["duration_s"]) == 120
    assert not any(w["data"]["app"] == "LINE.exe" for w in ws)
    idle = [e for e in svc.store.events_for_date("2026-10-19") if e["type"] == "idle"]
    assert len(idle) == 1 and idle[0]["duration_s"] >= 300


def test_pause_flag_stops_capture(svc, fake, cfg):
    agent = make_agent(svc, fake)
    cfg.set_paused(True)
    agent.tick()
    fake.now += 100
    agent.tick()
    cfg.set_paused(False)
    agent.flush(fake.now)
    assert windows(svc) == []


def test_long_focus_is_persisted_in_segments(svc, fake):
    agent = make_agent(svc, fake)
    for _ in range(14):
        agent.tick()
        fake.now += 60
    assert len(windows(svc)) == 2  # 13 minutes -> two 5-minute segments flushed so far


MEETING_WIN = ("ms-teams.exe", "Weekly SOC sync | Microsoft Teams")
PWSH = {"app": "pwsh.exe", "title": "PowerShell", "pid": 1, "hwnd": 1}
EDGE = {"app": "msedge.exe", "title": "Splunk docs - Microsoft Edge", "pid": 2, "hwnd": 2}
TEAMS = {"app": MEETING_WIN[0], "title": MEETING_WIN[1], "pid": 3, "hwnd": 3}


def run_minutes(agent, fake, minutes: int, fg=None, wins=None) -> None:
    if fg is not None:
        fake.fg = fg
    if wins is not None:
        fake.wins = wins
    for _ in range(minutes):
        agent.tick()  # refresh + meeting_tick run on every tick (60s > REFRESH_EVERY_S)
        fake.now += 60


def test_meeting_presence_while_screen_sharing(svc, fake, cfg, monkeypatch):
    popups = []
    monkeypatch.setattr("opstrail.agent.daemon.osapi.spawn_popup", lambda args: popups.append((fake.now, args)) or True)
    agent = make_agent(svc, fake)
    t0 = fake.now  # 09:00
    other = [("pwsh.exe", "PowerShell"), ("explorer.exe", "Downloads")]

    run_minutes(agent, fake, 10, PWSH, other)                     # 09:00 work before the call
    run_minutes(agent, fake, 5, TEAMS, [MEETING_WIN, *other])     # 09:10 meeting has focus
    run_minutes(agent, fake, 6, PWSH)                             # 09:15 share screen, work in the terminal
    svc.record("shell", {"cmd": "Get-Service splunkd"}, source="powershell",
               ts=datetime.fromtimestamp(t0 + 21 * 60, cfg.tz))  # 09:21 – before the presence covering it is flushed
    run_minutes(agent, fake, 4, PWSH)
    run_minutes(agent, fake, 3, EDGE)                             # 09:25
    run_minutes(agent, fake, 12, PWSH)                            # 09:28
    assert not popups, "no summary popup while the meeting window is still open"
    run_minutes(agent, fake, 5, TEAMS)                            # 09:40 back to the meeting
    run_minutes(agent, fake, 15, PWSH, other)                     # 09:45 call ended, window closed
    agent.flush(fake.now)
    agent.flush_presence(fake.now)
    svc.refresh()

    events = svc.store.events_for_date("2026-10-19")
    presence = [e for e in events if e["type"] == "window" and e["data"].get("presence")]
    assert presence and all(e["data"]["app"] == "ms-teams.exe" and e["activity"] == "meeting" for e in presence)
    assert min(e["epoch"] for e in presence) == t0 + 15 * 60
    assert max(e["epoch"] + e["duration_s"] for e in presence) == t0 + 40 * 60

    eps = svc.store.episodes_between("2026-10-19")
    meetings = [e for e in eps if e["origin"] == "meeting"]
    assert len(meetings) == 1
    m = meetings[0]
    assert (m["start_epoch"], m["end_epoch"]) == (t0 + 10 * 60, t0 + 45 * 60)  # the whole call
    assert m["stats"]["meeting_subject"] == "Weekly SOC sync"
    # foreground work during the call stays in the meeting episode
    during = [e for e in events if t0 + 10 * 60 <= e["epoch"] < t0 + 45 * 60]
    assert during and all(e["episode_id"] == m["id"] for e in during)
    shell_ev = next(e for e in events if e["type"] == "shell")
    assert shell_ev["episode_id"] == m["id"]
    # no work episode overlaps the call; presence does not double-count active time
    for ep in eps:
        if ep["origin"] != "meeting":
            assert ep["end_epoch"] <= m["start_epoch"] or ep["start_epoch"] >= m["end_epoch"], ep
    assert m["stats"]["active_s"] == 35 * 60
    # the summary popup comes only after the call really ended (+ grace)
    assert [args[0] for _, args in popups] == ["meeting"]
    assert popups[0][0] >= t0 + 48 * 60


def test_meeting_presence_can_be_disabled(svc, fake, home):
    (home / "config.toml").write_text(
        (home / "config.toml").read_text(encoding="utf-8") + "\n[meetings]\ndetect_background = false\n",
        encoding="utf-8",
    )
    from opstrail.config import load_config
    from opstrail.service import OpsTrail

    svc2 = OpsTrail(load_config(home))
    try:
        agent = make_agent(svc2, fake)
        run_minutes(agent, fake, 6, PWSH, [MEETING_WIN])
        agent.flush_presence(fake.now)
        assert agent.presence is None
        assert not [e for e in windows(svc2) if e["data"].get("presence")]
    finally:
        svc2.store.close()


def test_recap_tick_creates_recap_once(svc, fake, cfg):
    agent = make_agent(svc, fake)
    agent.tick()
    fake.now += 120
    agent.flush(fake.now)
    late = datetime(2026, 10, 19, 18, 30, tzinfo=cfg.tz).timestamp()
    agent._recap_if_needed("2026-10-19", popup=False)
    first = svc.store.kv_get("recap_done:2026-10-19")
    assert first and svc.recap_session_id("2026-10-19")
    agent._recap_if_needed("2026-10-19", popup=False)
    assert svc.store.kv_get("recap_done:2026-10-19") == first
    assert late  # sanity


def test_hotkey_parse_and_match():
    assert parse_combo("<ctrl>+<alt>+n") == (frozenset({"ctrl", "alt"}), "n")
    fired = []
    m = HotkeyMatcher({"<ctrl>+<alt>+n": lambda: fired.append("n")})
    m._current_mods = lambda: frozenset(m.pressed)  # on Windows it asks the real keyboard (GetAsyncKeyState)

    class K:  # pynput-like key objects
        def __init__(self, name=None, vk=None, char=None):
            self.name, self.vk, self.char = name, vk, char

    m.on_press(K(name="ctrl_l"))
    m.on_press(K(name="alt_l"))
    m.on_press(K(vk=0x4E, char="\x0e"))  # Ctrl changes the char on Windows; vk still says 'N'
    import time

    time.sleep(0.2)
    assert fired == ["n"]
    m.on_release(K(name="alt_l"))
    m.on_press(K(vk=0x4E, char="n"))
    time.sleep(0.1)
    assert fired == ["n"]


def test_win_combo_flags():
    assert win_combo("<ctrl>+<alt>+n") == (0x2 | 0x1, ord("N"))
    assert win_combo("<ctrl>+<shift>+f9") == (0x2 | 0x4, 0x78)
    with pytest.raises(ValueError):
        win_combo("<ctrl>+<alt>+pageup")


def test_claude_code_hook_logs_and_respects_no_capture(cfg, monkeypatch):
    import io
    import json

    from opstrail.cli import main

    monkeypatch.delenv("OPSTRAIL_NO_CAPTURE", raising=False)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": "/repo"})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert main(["hook", "claude-code"]) == 0
    assert len(list(cfg.inbox_dir.glob("*.jsonl"))) == 1
    # AI developers started by scripts/duo.ps1 must not end up in Bro's worklog
    for f in cfg.inbox_dir.glob("*.jsonl"):
        f.unlink()
    monkeypatch.setenv("OPSTRAIL_NO_CAPTURE", "1")
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert main(["hook", "claude-code"]) == 0
    assert not list(cfg.inbox_dir.glob("*.jsonl"))
