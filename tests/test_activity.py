"""Activity classifier, meeting episodes and the meeting-summary prompt."""

from __future__ import annotations

from datetime import datetime

import pytest
from conftest import DAY, at, shell, window, write_jsonl

from opstrail.activity import Classifier


@pytest.fixture(scope="module")
def clf():
    return Classifier()


@pytest.mark.parametrize(
    "type_, data, activity, subject",
    [
        ("window", {"app": "ms-teams.exe", "title": "สัมภาษณ์นักศึกษาฝึกสหกิจ | Microsoft Teams"}, "meeting", "สัมภาษณ์นักศึกษาฝึกสหกิจ"),
        ("window", {"app": "ms-teams.exe", "title": "Meeting compact view | Weekly SOC sync | Microsoft Teams"}, "meeting", "Weekly SOC sync"),
        ("window", {"app": "ms-teams.exe", "title": "Chat | สมชาย ใจดี | Microsoft Teams"}, "chat", "สมชาย ใจดี"),
        ("window", {"app": "ms-teams.exe", "title": "Calendar | Calendar | Microsoft Teams"}, "chat", "Microsoft Teams"),
        ("window", {"app": "ms-teams.exe", "title": "Activity | Microsoft Teams"}, "chat", "Microsoft Teams"),
        ("window", {"app": "msedge.exe", "title": "Incidents - Microsoft Sentinel - Microsoft Azure"}, "console", "Microsoft Sentinel"),
        ("window", {"app": "msedge.exe", "title": "Home - Microsoft Azure and 3 more pages"}, "console", "Azure portal"),
        ("window", {"app": "msedge.exe", "title": "Install a universal forwarder - Splunk Documentation"}, "research", ""),
        ("window", {"app": "chrome.exe", "title": "Search | Splunk 9.3"}, "console", "Splunk"),
        ("window", {"app": "WindowsTerminal.exe", "title": "admin@splunk-uf01: ~"}, "terminal", ""),
        ("window", {"app": "mstsc.exe", "title": "dc01.corp.local - Remote Desktop Connection"}, "remote", "dc01.corp.local"),
        ("window", {"app": "olk.exe", "title": "RE: ใบเสนอราคา Silverfort - Inbox - Bro - Outlook"}, "email", "RE: ใบเสนอราคา Silverfort"),
        ("window", {"app": "claude.exe", "title": "Claude"}, "ai", ""),
        ("window", {"app": "code.exe", "title": "app.py - OpsTrail - Visual Studio Code"}, "code", ""),
        ("window", {"app": "winword.exe", "title": "Delivery-TG.docx - Word"}, "docs", ""),
        ("window", {"app": "msedge.exe", "title": "abc-defg-hij - Google Meet"}, "meeting", "abc-defg-hij"),
        ("shell", {"cmd": "ssh admin@splunk-uf01"}, "remote", "splunk-uf01"),
        ("shell", {"cmd": "Get-Service splunkd"}, "terminal", ""),
        ("ai", {"tool": "Bash", "cmd": "pytest -q"}, "ai", ""),
        ("window", {"app": "unknown.exe", "title": "Something"}, "other", ""),
    ],
)
def test_classify(clf, type_, data, activity, subject):
    assert clf.classify(type_, data) == (activity, subject)


def test_user_rules_take_precedence(tmp_path):
    user = tmp_path / "activity_rules.toml"
    user.write_text('[[rule]]\nactivity = "console"\napps = ["@browser"]\ntitle_regex = "(?i)customer-x portal"\n'
                    'subject = "Customer X"\n', encoding="utf-8")
    c = Classifier(user)
    assert c.classify("window", {"app": "msedge.exe", "title": "Login | Customer-X Portal"}) == ("console", "Customer X")


def test_meeting_becomes_its_own_episode(cfg, svc):
    teams = "ms-teams.exe"
    subj = "สัมภาษณ์นักศึกษาฝึกสหกิจ | Microsoft Teams"
    write_jsonl(cfg, "day", [
        window(at(14, 0), "WindowsTerminal.exe", "PowerShell", 1200),
        shell(at(14, 5), "opstrail status"),
        window(at(14, 20), teams, subj, 1200),           # meeting 14:20–14:40
        window(at(14, 40), "olk.exe", "Inbox - Bro - Outlook", 120),  # quick glance during the call
        window(at(14, 42), teams, subj, 1800),           # back in the meeting until 15:12
        window(at(15, 12), "code.exe", "app.py - OpsTrail - Visual Studio Code", 1500),
        shell(at(15, 20), "pytest -q"),
    ])
    svc.refresh()
    eps = svc.list_episodes(DAY)
    meeting = [e for e in eps if e["origin"] == "meeting"]
    assert len(meeting) == 1, eps
    m = meeting[0]
    assert m["title"] == "ประชุม: สัมภาษณ์นักศึกษาฝึกสหกิจ" and m["time"] == "14:20–15:12"
    assert "meeting" in m["tags"]
    detail = svc.get_episode(m["id"])
    assert any("Outlook" in w["window"] for w in detail["windows"])  # the glance stayed inside the meeting
    others = [e for e in eps if e["origin"] != "meeting"]
    assert [e["time"] for e in others] == ["14:00–14:20", "15:12–15:37"]
    # the meeting shows up clearly in the source pack
    sid = svc.start_doc_session("meeting-minutes", "สัมภาษณ์", [m["id"]])["session_id"]
    pack = svc.source_pack(sid)
    assert "Type: MEETING" in pack and "สัมภาษณ์นักศึกษาฝึกสหกิจ" in pack


def test_meeting_prompt_after_it_ends(cfg, svc, monkeypatch):
    from opstrail.agent import daemon, osapi

    spawned = []
    monkeypatch.setattr(osapi, "spawn_popup", lambda args: spawned.append(args) or True)
    now = datetime.now(cfg.tz)
    start = now.replace(hour=max(now.hour - 2, 0), minute=0, second=0, microsecond=0)
    svc.record("window", {"app": "ms-teams.exe", "title": "Design review | Microsoft Teams"}, source="agent",
               ts=start, duration_s=1800)
    svc.refresh()
    agent = daemon.Agent(svc, foreground=lambda: None, idle_seconds=lambda: 0.0, clock=lambda: now.timestamp())
    agent.meeting_tick(now.timestamp())
    assert spawned and spawned[0][0] == "meeting"
    agent.meeting_tick(now.timestamp())
    assert len(spawned) == 1  # asked only once


def test_profile_author_overrides_windows_username(cfg):
    assert cfg.author == "Tester"  # from config.toml in the fixture
    cfg.save_profile(author="Teerapat S.")
    assert cfg.author == "Teerapat S."
