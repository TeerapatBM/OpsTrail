"""Cross-platform foreground-window / idle detection (Windows first, best effort elsewhere)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Any

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


def set_dpi_aware() -> None:
    if IS_WINDOWS:
        from opstrail.agent import winapi

        winapi.set_dpi_aware()


def idle_seconds() -> float:
    if IS_WINDOWS:
        from opstrail.agent import winapi

        return winapi.idle_seconds()
    if IS_MAC:
        try:
            out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, timeout=3).stdout
            for line in out.splitlines():
                if "HIDIdleTime" in line:
                    return int(line.split("=")[-1].strip()) / 1e9
        except Exception:
            return 0.0
        return 0.0
    if shutil.which("xprintidle"):
        try:
            out = subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=3).stdout.strip()
            return int(out) / 1000.0
        except Exception:
            return 0.0
    return 0.0


def _process_name(pid: int) -> str:
    try:
        import psutil

        return psutil.Process(pid).name()
    except Exception:
        return ""


def foreground() -> dict[str, Any] | None:
    if IS_WINDOWS:
        from opstrail.agent import winapi

        return winapi.foreground()
    if IS_MAC:
        script = (
            'tell application "System Events" to set p to first application process whose frontmost is true\n'
            "set n to name of p\n"
            'set t to ""\n'
            "try\n set t to name of front window of p\nend try\n"
            'return n & "\\n" & t'
        )
        try:
            out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=3).stdout
            app, _, title = out.strip().partition("\n")
            return {"app": app or "unknown", "title": title, "pid": 0, "hwnd": 0}
        except Exception:
            return None
    if shutil.which("xdotool"):
        try:
            title = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"], capture_output=True, text=True, timeout=3
            ).stdout.strip()
            pid_text = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowpid"], capture_output=True, text=True, timeout=3
            ).stdout.strip()
            pid = int(pid_text) if pid_text.isdigit() else 0
            return {"app": _process_name(pid) or "unknown", "title": title, "pid": pid, "hwnd": 0}
        except Exception:
            return None
    return None


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if IS_WINDOWS and hwnd:
        from opstrail.agent import winapi

        return winapi.window_rect(hwnd)
    return None


def pythonw() -> str:
    """Interpreter for GUI popups (pythonw.exe on Windows avoids a console flash)."""
    from pathlib import Path

    exe = Path(sys.executable)
    if IS_WINDOWS:
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return str(exe)


def spawn_popup(args: list[str]) -> bool:
    """Run `python -m opstrail popup …` detached. Returns False if it could not start."""
    cmd = [pythonw(), "-m", "opstrail", "popup", *args]
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if IS_WINDOWS:
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            import ctypes

            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY: let the popup take focus
        except Exception:
            pass
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(cmd, **kwargs)
        return True
    except Exception:
        return False


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        pass
    if IS_WINDOWS:
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    import os

    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def agent_alive(pid: int) -> bool:
    """True if `pid` is a running OpsTrail agent (guards against PID reuse after a crash)."""
    if not pid_alive(pid):
        return False
    try:
        import psutil

        cmdline = " ".join(psutil.Process(pid).cmdline()).lower()
        return "opstrail" in cmdline
    except ImportError:
        return True
    except Exception:  # AccessDenied / process vanished
        return pid_alive(pid)
