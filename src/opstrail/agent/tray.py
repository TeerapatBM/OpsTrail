"""Optional system tray. Desktop callbacks enqueue work for the agent thread."""
from __future__ import annotations

import logging
import sys
import threading
import webbrowser
from queue import Empty, Queue
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from opstrail.agent.daemon import Agent

from opstrail.agent import osapi

log = logging.getLogger("opstrail.agent.tray")


class Tray:
    def __init__(self, agent: Agent):
        self.agent = agent
        self.actions: Queue[str] = Queue()
        self.icon: Any = None
        self.thread: threading.Thread | None = None
        self._stopped = threading.Event()
        self._ready = threading.Event()
        self._paused = agent.cfg.is_paused()
        self._images: dict[bool, Any] = {}

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="opstrail-tray", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            if sys.platform == "darwin":
                # Cocoa requires a main-thread runloop; this agent owns that thread.
                log.info("system tray unavailable on macOS; agent continues without it")
                return
            # Imports may fail for a missing extra or a headless/unsupported desktop.
            import pystray
            from PIL import Image, ImageDraw

            if not getattr(pystray.Icon, "HAS_MENU", True):
                raise RuntimeError("tray menus unsupported")

            for paused, color in ((False, "#22c55e"), (True, "#808080")):
                image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                ImageDraw.Draw(image).ellipse((8, 8, 56, 56), fill=color)
                self._images[paused] = image

            def item(label: Any, action: str) -> Any:
                return pystray.MenuItem(label, lambda icon, item: self.actions.put(action))

            menu = pystray.Menu(
                item("เปิดหน้าเว็บ", "web"),
                item(lambda item: "บันทึกต่อ" if self._paused else "หยุดบันทึก", "pause"),
                item("โน้ต", "note"),
                item("ถ่ายรูป", "screenshot"),
                item("Daily worklog วันนี้", "recap"),
                item("ออก", "exit"),
            )
            self.icon = pystray.Icon("opstrail", self._images[self._paused], self._title(), menu)

            def setup(icon: Any) -> None:
                icon.visible = True
                self._ready.set()
                if self._stopped.is_set():
                    icon.stop()

            if not self._stopped.is_set():
                self.icon.run(setup=setup)
        except Exception:
            # Avoid backend error text (which can contain environment details).
            log.info("system tray unavailable; agent continues without it")
        finally:
            self._ready.clear()

    def _title(self) -> str:
        return "OpsTrail: หยุดบันทึกชั่วคราว" if self._paused else "OpsTrail: กำลังบันทึก"

    def _open(self, path: str = "") -> None:
        if not self.agent.cfg.web.get("enabled", True):
            osapi.spawn_popup(["toast", "หน้าเว็บปิดอยู่ เปิดใช้งาน [web] enabled ใน config แล้ว restart agent"])
            return
        from opstrail.web.app import url

        if not webbrowser.open(url(self.agent.cfg, path)):
            osapi.spawn_popup(["toast", "เปิดเบราว์เซอร์ไม่สำเร็จ กรุณาเปิดหน้าเว็บ OpsTrail ด้วยตนเอง"])

    def _action(self, action: str) -> None:
        agent = self.agent
        if action == "pause":
            agent.hotkey_pause()
        elif action == "note":
            osapi.spawn_popup(["note"])
        elif action == "screenshot":
            agent.hotkey_screenshot()
        elif action == "web":
            self._open()
        elif action == "recap":
            day = agent.cfg.today()
            if agent.cfg.web.get("enabled", True):
                # Opening an existing worklog must not replace the user's edits.
                sid = agent.svc.recap_session_id(day)
                if sid is None:
                    sid = agent.svc.daily_recap(day, save=True)["session_id"]
                self._open(f"#/docs/{sid}")
            else:
                osapi.spawn_popup(["review", "--date", day])
        elif action == "exit":
            agent.stop()

    def poll(self) -> None:
        """Called on the agent thread: no SQLite connections cross threads."""
        while self.agent.running:
            try:
                action = self.actions.get_nowait()
            except Empty:
                break
            try:
                self._action(action)
            except Exception:
                log.warning("tray action failed")
                osapi.spawn_popup(["toast", "ทำรายการไม่สำเร็จ กรุณาลองใหม่หรือดู logs/agent.log"])
        paused = self.agent.cfg.is_paused()
        if self._ready.is_set() and paused != self._paused:
            self._paused = paused
            try:
                self.icon.icon = self._images[paused]
                self.icon.title = self._title()
                self.icon.update_menu()
            except Exception:
                log.info("system tray state update unavailable")

    def stop(self) -> None:
        self._stopped.set()
        try:
            if self._ready.is_set():
                self.icon.stop()
        except Exception:
            log.info("system tray cleanup unavailable")
        if self.thread is not None:
            self.thread.join(timeout=2)
