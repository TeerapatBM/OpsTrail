"""Screenshots via mss (active window or the monitor that contains it)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opstrail.agent import osapi
from opstrail.config import Config
from opstrail.service import default_shot_path


def _monitor_for(sct: Any, rect: tuple[int, int, int, int] | None) -> dict[str, int]:
    monitors = sct.monitors[1:] or sct.monitors
    if rect:
        cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        for mon in monitors:
            if mon["left"] <= cx < mon["left"] + mon["width"] and mon["top"] <= cy < mon["top"] + mon["height"]:
                return mon
    return monitors[0]


def capture(cfg: Config, fg: dict[str, Any] | None = None, mode: str | None = None, path: Path | None = None) -> Path:
    import mss
    import mss.tools

    mode = (mode or cfg.capture.get("screenshot_mode") or "window").lower()
    target = path or default_shot_path(cfg)
    rect = osapi.window_rect(int(fg.get("hwnd") or 0)) if fg else None
    with mss.mss() as sct:
        region: dict[str, int] | None = None
        if mode == "window" and rect:
            virtual = sct.monitors[0]
            left = max(rect[0], virtual["left"])
            top = max(rect[1], virtual["top"])
            right = min(rect[2], virtual["left"] + virtual["width"])
            bottom = min(rect[3], virtual["top"] + virtual["height"])
            if right - left >= 80 and bottom - top >= 60:
                region = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        if region is None:
            region = dict(_monitor_for(sct, rect))
        shot = sct.grab(region)
        mss.tools.to_png(shot.rgb, shot.size, output=str(target))
    return target
