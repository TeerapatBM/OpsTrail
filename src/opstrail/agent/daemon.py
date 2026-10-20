"""The capture agent main loop."""

from __future__ import annotations

import logging
import os
import re
import signal
import time
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from typing import Any, Callable

from opstrail.agent import osapi
from opstrail.config import Config
from opstrail.service import OpsTrail

log = logging.getLogger("opstrail.agent")

HEARTBEAT_EVERY_S = 15
REFRESH_EVERY_S = 10
MAX_SEGMENT_S = 300  # persist long-focused windows every 5 minutes


@dataclass
class Segment:
    app: str
    title: str
    pid: int
    hwnd: int
    start: float


class Agent:
    def __init__(
        self,
        svc: OpsTrail,
        *,
        foreground: Callable[[], dict[str, Any] | None] = osapi.foreground,
        idle_seconds: Callable[[], float] = osapi.idle_seconds,
        clock: Callable[[], float] = time.time,
    ):
        self.svc = svc
        self.cfg: Config = svc.cfg
        self._foreground = foreground
        self._idle_seconds = idle_seconds
        self._clock = clock
        self.current: Segment | None = None
        self.idle_since: float | None = None
        self.last_refresh = 0.0
        self.last_heartbeat = 0.0
        self.last_auto_shot: dict[str, float] = {}
        self.running = True
        cap = self.cfg.capture
        self.exclude_apps = {a.lower() for a in cap.get("exclude_apps", [])}
        self.exclude_titles = [re.compile(p) for p in cap.get("exclude_title_patterns", []) if _valid(p)]
        self.auto_shot_titles = [re.compile(p) for p in cap.get("auto_screenshot_title_patterns", []) if _valid(p)]

    # --------------------------------------------------------------- capture
    def _excluded(self, fg: dict[str, Any]) -> bool:
        if str(fg.get("app", "")).lower() in self.exclude_apps:
            return True
        title = str(fg.get("title", ""))
        return any(p.search(title) for p in self.exclude_titles)

    def flush(self, end: float) -> None:
        seg = self.current
        self.current = None
        if seg is None:
            return
        duration = end - seg.start
        if duration < float(self.cfg.capture.get("min_window_s", 3)):
            return
        self.svc.record(
            "window",
            {"app": seg.app, "title": seg.title[:300], "pid": seg.pid},
            source="agent",
            ts=datetime.fromtimestamp(seg.start, self.cfg.tz),
            duration_s=duration,
        )

    def _record_idle(self, start: float, end: float) -> None:
        if end - start >= float(self.cfg.capture.get("idle_threshold_s", 300)):
            self.svc.record(
                "idle", {}, source="agent", ts=datetime.fromtimestamp(start, self.cfg.tz), duration_s=end - start
            )

    def capture_tick(self, now: float) -> None:
        if self.cfg.is_paused():
            self.flush(now)
            self.idle_since = None
            return
        idle = self._idle_seconds()
        threshold = float(self.cfg.capture.get("idle_threshold_s", 300))
        if idle >= threshold:
            if self.idle_since is None:
                self.idle_since = now - idle
                self.flush(self.idle_since)
            return
        if self.idle_since is not None:
            self._record_idle(self.idle_since, now - idle)
            self.idle_since = None

        fg = self._foreground()
        if not fg or self._excluded(fg):
            self.flush(now)
            return
        key = (fg.get("app", ""), fg.get("title", ""))
        seg = self.current
        if seg and (seg.app, seg.title) == key:
            if now - seg.start >= MAX_SEGMENT_S:
                self.flush(now)
                self.current = Segment(seg.app, seg.title, seg.pid, seg.hwnd, now)
            return
        self.flush(now)
        self.current = Segment(str(key[0]), str(key[1]), int(fg.get("pid") or 0), int(fg.get("hwnd") or 0), now)
        self._maybe_auto_shot(fg, now)

    def _maybe_auto_shot(self, fg: dict[str, Any], now: float) -> None:
        if not self.auto_shot_titles:
            return
        title = str(fg.get("title", ""))
        if not any(p.search(title) for p in self.auto_shot_titles):
            return
        min_gap = float(self.cfg.capture.get("auto_screenshot_min_interval_s", 120))
        if now - self.last_auto_shot.get(title, 0) < min_gap:
            return
        self.last_auto_shot[title] = now
        try:
            from opstrail.agent.screenshot import capture

            path = capture(self.cfg, fg)
            self.svc.record(
                "screenshot",
                {"path": str(path), "app": fg.get("app"), "title": title, "caption": "auto"},
                source="agent",
            )
        except Exception:
            log.exception("auto screenshot failed")

    # ---------------------------------------------------------------- hotkeys
    def hotkey_screenshot(self) -> None:
        fg = self._foreground() or {}
        try:
            from opstrail.agent.screenshot import capture

            path = capture(self.cfg, fg)
        except Exception:
            log.exception("screenshot failed")
            osapi.spawn_popup(["toast", "ถ่ายรูปไม่สำเร็จ ดู log ที่ ~/.opstrail/logs"])
            return
        args = ["shot", "--path", str(path), "--app", str(fg.get("app", "")), "--title", str(fg.get("title", ""))]
        if not osapi.spawn_popup(args):
            self.svc.record(
                "screenshot", {"path": str(path), "app": fg.get("app"), "title": fg.get("title")}, source="hotkey"
            )

    def hotkey_pause(self) -> None:
        paused = not self.cfg.is_paused()
        self.cfg.set_paused(paused)
        osapi.spawn_popup(["toast", "OpsTrail: หยุดบันทึกชั่วคราว" if paused else "OpsTrail: บันทึกต่อแล้ว"])

    # ----------------------------------------------------------------- recap
    def recap_tick(self, now: float) -> None:
        rc = self.cfg.recap
        if not rc.get("auto", True):
            return
        local = datetime.fromtimestamp(now, self.cfg.tz)
        today = local.date().isoformat()
        try:
            hh, mm = [int(x) for x in str(rc.get("time", "18:00")).split(":")[:2]]
        except ValueError:
            hh, mm = 18, 0
        # yesterday's recap if the PC was off at recap time
        # (refreshed once more if work continued after the recap was made)
        yesterday = (date_cls.fromisoformat(today) - timedelta(days=1)).isoformat()
        self._recap_if_needed(yesterday, popup=False, refresh_if_changed=True)
        if (local.hour, local.minute) >= (hh, mm):
            self._recap_if_needed(today, popup=bool(rc.get("review_popup", True)))

    def _recap_if_needed(self, day: str, popup: bool, refresh_if_changed: bool = False) -> None:
        store = self.svc.store
        count = sum(store.count_events(day).values())
        if not count:
            return
        done = store.kv_get(f"recap_done:{day}")
        if done:
            if not refresh_if_changed or done.endswith(f":{count}"):
                return
        try:
            res = self.svc.daily_recap(day, save=True)
            # count again: daily_recap() refreshes the inbox first
            count = sum(store.count_events(day).values())
            store.kv_set(f"recap_done:{day}", f"{res.get('session_id', '')}:{count}")
            log.info("daily recap created for %s (session %s)", day, res.get("session_id"))
            if popup:
                self.open_review(day)
        except Exception:
            log.exception("daily recap failed for %s", day)

    # -------------------------------------------------------------- meetings
    def _in_meeting_now(self) -> bool:
        seg = self.current
        if seg is None:
            return False
        from opstrail.activity import classifier_for

        act, _ = classifier_for(self.cfg.home).classify("window", {"app": seg.app, "title": seg.title})
        return act == "meeting"

    def meeting_tick(self, now: float) -> None:
        """Ask for a short summary once a meeting has ended (no audio/transcript needed)."""
        mc = self.cfg.data.get("meetings", {})
        if not mc.get("summary_prompt", True) or self._in_meeting_now():
            return
        min_s = float(mc.get("min_minutes", 10)) * 60
        grace_s = float(mc.get("grace_minutes", 3)) * 60
        today = datetime.fromtimestamp(now, self.cfg.tz).date().isoformat()
        store = self.svc.store
        for ep in store.episodes_between(today):
            if ep.get("origin") != "meeting" or store.kv_get(f"meeting_prompted:{ep['id']}"):
                continue
            if ep["end_epoch"] - ep["start_epoch"] < min_s or now - ep["end_epoch"] < grace_s:
                continue
            store.kv_set(f"meeting_prompted:{ep['id']}", str(int(now)))
            if (ep.get("stats") or {}).get("notes"):
                continue  # the user already wrote something for this meeting
            osapi.spawn_popup(["meeting", "--episode", str(ep["id"])])

    def open_review(self, day: str) -> None:
        web = self.cfg.web
        if web.get("enabled", True) and web.get("open_on_recap", True):
            import webbrowser

            from opstrail.web.app import url

            try:
                webbrowser.open(url(self.cfg, f"#/day/{day}?review=1"))
                return
            except Exception:
                log.exception("could not open the browser")
        osapi.spawn_popup(["review", "--date", day])

    # ------------------------------------------------------------------ loop
    def tick(self) -> None:
        now = self._clock()
        try:
            self.capture_tick(now)
        except Exception:
            log.exception("capture failed")
        if now - self.last_refresh >= REFRESH_EVERY_S:
            self.last_refresh = now
            try:
                self.svc.refresh()
                self.meeting_tick(now)
                self.recap_tick(now)
            except Exception:
                log.exception("refresh failed")
        if now - self.last_heartbeat >= HEARTBEAT_EVERY_S:
            self.last_heartbeat = now
            self.svc.store.kv_set("agent:heartbeat", str(now))

    def stop(self, *_: Any) -> None:
        self.running = False

    def run(self) -> None:
        poll = max(1.0, float(self.cfg.capture.get("poll_interval_s", 5)))
        try:
            signal.signal(signal.SIGTERM, self.stop)
            signal.signal(signal.SIGINT, self.stop)
        except Exception:
            pass
        self.svc.record("system", {"message": "agent started"}, source="agent")
        log.info("agent started (poll %.0fs, home %s)", poll, self.cfg.home)
        try:
            while self.running:
                self.tick()
                slept = 0.0
                while self.running and slept < poll:
                    time.sleep(0.25)
                    slept += 0.25
        finally:
            self.flush(self._clock())
            self.svc.record("system", {"message": "agent stopped"}, source="agent")
            self.svc.store.kv_set("agent:heartbeat", "0")
            log.info("agent stopped")


def _valid(pattern: str) -> bool:
    try:
        re.compile(pattern)
        return True
    except re.error:
        log.warning("invalid regex in config: %s", pattern)
        return False


def setup_logging(cfg: Config) -> None:
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(cfg.logs_dir / "agent.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def acquire_lock(cfg: Config) -> bool:
    pid_file = cfg.home / "agent.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip() or 0)
        except ValueError:
            pid = 0
        if pid and pid != os.getpid() and osapi.agent_alive(pid):
            return False
    pid_file.write_text(str(os.getpid()))
    return True


def release_lock(cfg: Config) -> None:
    pid_file = cfg.home / "agent.pid"
    try:
        if pid_file.exists() and pid_file.read_text().strip() == str(os.getpid()):
            pid_file.unlink()
    except OSError:
        pass


def run_agent(cfg: Config, *, with_hotkeys: bool = True) -> int:
    setup_logging(cfg)
    if not acquire_lock(cfg):
        print("OpsTrail agent is already running.")
        return 1
    try:
        osapi.set_dpi_aware()
        svc = OpsTrail(cfg)
        agent = Agent(svc)
        if cfg.web.get("enabled", True):
            try:
                from opstrail.web.app import serve

                serve(svc, in_thread=True)
                log.info("web UI on http://127.0.0.1:%s", cfg.web.get("port", 8765))
            except Exception:
                log.exception("web UI could not start (port in use?)")
        if with_hotkeys:
            from opstrail.agent import hotkeys

            hk = cfg.hotkeys
            bindings: dict[str, Callable[[], None]] = {}
            if hk.get("note"):
                bindings[hk["note"]] = lambda: osapi.spawn_popup(["note"])
            if hk.get("task"):
                bindings[hk["task"]] = lambda: osapi.spawn_popup(["task"])
            if hk.get("screenshot"):
                bindings[hk["screenshot"]] = agent.hotkey_screenshot
            if hk.get("pause"):
                bindings[hk["pause"]] = agent.hotkey_pause
            hotkeys.start(bindings)
        agent.run()
        return 0
    finally:
        release_lock(cfg)
