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

    def clock(self):
        return self.now

    def foreground(self):
        return self.fg

    def idle_seconds(self):
        return self.idle


@pytest.fixture()
def fake(cfg):
    t0 = datetime(2026, 10, 19, 9, 0, tzinfo=cfg.tz).timestamp()
    return FakeOS(t0)


def make_agent(svc, fake):
    return Agent(svc, foreground=fake.foreground, idle_seconds=fake.idle_seconds, clock=fake.clock)


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
