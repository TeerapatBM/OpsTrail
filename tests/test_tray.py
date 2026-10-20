"""Tray callbacks use a fake desktop backend; no display or optional deps needed."""
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from opstrail.agent.daemon import Agent


@pytest.fixture
def backend(monkeypatch):
    class Icon:
        def __init__(self, name, image, title, menu):
            self.icon, self.title, self.menu = image, title, menu
            self.ready = threading.Event()
            self.finished = threading.Event()
            self.visible = False

        def run(self, setup):
            setup(self)
            self.ready.set()
            self.finished.wait(3)

        def stop(self):
            self.finished.set()

        def update_menu(self):
            pass

    monkeypatch.setitem(sys.modules, "pystray", SimpleNamespace(
        Icon=Icon, Menu=lambda *items: items,
        MenuItem=lambda text, action, **kw: SimpleNamespace(text=text, action=action),
    ))
    monkeypatch.setitem(sys.modules, "PIL", SimpleNamespace(
        Image=SimpleNamespace(new=lambda *args: SimpleNamespace(color=args[-1])),
        ImageDraw=SimpleNamespace(Draw=lambda image: SimpleNamespace(
            ellipse=lambda bounds, fill: setattr(image, "color", fill))),
    ))


def start_tray(svc):
    from opstrail.agent.tray import Tray
    agent = Agent(svc, foreground=lambda: None, idle_seconds=lambda: 0)
    tray = Tray(agent)
    tray.start()
    assert tray.thread is not None
    # Join readiness without requiring a real window/message loop.
    for _ in range(100):
        if tray.icon is not None and tray.icon.ready.wait(0.02):
            break
        time.sleep(0.01)
    assert tray.icon is not None and tray.icon.ready.is_set()
    return agent, tray


def test_menu_actions_are_queued_and_use_existing_agent_paths(svc, cfg, monkeypatch, backend):
    from opstrail.agent import osapi
    import webbrowser
    popups, urls = [], []
    monkeypatch.setattr(osapi, "spawn_popup", lambda args: popups.append(args) or True)
    monkeypatch.setattr(webbrowser, "open", lambda url: urls.append(url) or True)
    monkeypatch.setattr(Agent, "hotkey_screenshot", lambda self: popups.append(["screenshot"]))
    cfg.data["web"]["port"] = 18765
    agent, tray = start_tray(svc)
    try:
        items = tray.icon.menu
        items[1].action(tray.icon, items[1])
        assert not cfg.is_paused()  # callback thread must not perform agent work
        tray.poll()
        assert cfg.is_paused() and tray.icon.icon.color == "#808080"
        assert items[1].text(items[1]) == "บันทึกต่อ"
        items[1].action(tray.icon, items[1])
        tray.poll()
        assert not cfg.is_paused() and tray.icon.icon.color == "#22c55e"
        for index in (0, 2, 3, 4):
            items[index].action(tray.icon, items[index])
        tray.poll()
        assert urls[0] == "http://127.0.0.1:18765/"
        assert urls[1].startswith("http://127.0.0.1:18765/#/docs/")
        assert ["note"] in popups and ["screenshot"] in popups
        assert svc.list_doc_sessions(template="daily-worklog")
        items[5].action(tray.icon, items[5])
        tray.poll()
        assert not agent.running
    finally:
        tray.stop()
    assert not tray.thread.is_alive()


def test_external_pause_and_disabled_web(svc, cfg, monkeypatch, backend):
    from opstrail.agent import osapi
    popups = []
    monkeypatch.setattr(osapi, "spawn_popup", lambda args: popups.append(args) or True)
    cfg.data["web"]["enabled"] = False
    agent, tray = start_tray(svc)
    try:
        cfg.set_paused(True)
        tray.poll()
        assert tray.icon.icon.color == "#808080"
        item = tray.icon.menu[4]
        item.action(tray.icon, item)
        tray.poll()
        assert popups == [["review", "--date", cfg.today()]]
    finally:
        tray.stop()


@pytest.mark.parametrize("failure", ["missing", "backend"])
def test_agent_runs_without_tray_backend(svc, monkeypatch, failure):
    from opstrail.agent.tray import Tray
    if failure == "missing":
        monkeypatch.setitem(sys.modules, "pystray", None)
    else:
        def fail(*args, **kwargs):
            raise RuntimeError("no desktop")
        monkeypatch.setitem(sys.modules, "pystray", SimpleNamespace(Icon=fail))
        monkeypatch.setitem(sys.modules, "PIL", SimpleNamespace(Image=None, ImageDraw=None))
    agent = Agent(svc, foreground=lambda: None, idle_seconds=lambda: 0)
    monkeypatch.setattr(agent, "tick", lambda: agent.stop())
    agent.run()
    assert svc.store.kv_get("agent:heartbeat") == "0"


def test_recap_reopens_saved_worklog_without_overwriting_edits(svc, monkeypatch, backend):
    import webbrowser
    result = svc.daily_recap(svc.cfg.today(), save=True)
    sid = result["session_id"]
    svc.save_draft(sid, "Edited worklog", author="user")
    before = svc.doc_detail(sid)["markdown"]
    urls = []
    monkeypatch.setattr(webbrowser, "open", lambda url: urls.append(url) or True)
    agent, tray = start_tray(svc)
    try:
        item = tray.icon.menu[4]
        item.action(tray.icon, item)
        tray.poll()
        assert urls == [f"http://127.0.0.1:8765/#/docs/{sid}"]
        assert svc.doc_detail(sid)["markdown"] == before == "Edited worklog"
    finally:
        tray.stop()


def test_failed_action_does_not_prevent_exit(svc, monkeypatch, backend):
    from opstrail.agent import osapi
    import webbrowser
    def fail(url):
        raise OSError("browser unavailable")
    monkeypatch.setattr(webbrowser, "open", fail)
    popups = []
    monkeypatch.setattr(osapi, "spawn_popup", lambda args: popups.append(args) or True)
    agent, tray = start_tray(svc)
    try:
        for index in (0, 5):
            item = tray.icon.menu[index]
            item.action(tray.icon, item)
        tray.poll()
        assert not agent.running
        assert popups and popups[0][0] == "toast"
    finally:
        tray.stop()


def test_shutdown_before_backend_ready_does_not_leave_icon_running(svc, monkeypatch, backend):
    from opstrail.agent.tray import Tray
    entered, release = threading.Event(), threading.Event()
    icon_type = sys.modules["pystray"].Icon
    original_run = icon_type.run

    def delayed_run(self, setup):
        entered.set()
        assert release.wait(3)
        original_run(self, setup)

    monkeypatch.setattr(icon_type, "run", delayed_run)
    tray = Tray(Agent(svc))
    tray.start()
    stopper = threading.Thread(target=tray.stop)
    try:
        assert entered.wait(2)
        stopper.start()
        assert tray._stopped.wait(2)
    finally:
        release.set()
        if stopper.ident is not None:
            stopper.join(3)
        tray.stop()
    assert not tray.thread.is_alive()
    assert tray.icon.finished.is_set()
