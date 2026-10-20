"""Global hotkeys.

Windows: RegisterHotKey (no keyboard hook – EDR friendly, sees only our combos).
Linux/macOS: pynput listener with a vk-based matcher.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Any, Callable

log = logging.getLogger("opstrail.hotkeys")

MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
    "cmd": "cmd",
    "win": "cmd",
    "super": "cmd",
}


def parse_combo(combo: str) -> tuple[frozenset[str], str]:
    """'<ctrl>+<alt>+n' -> ({'ctrl','alt'}, 'n')"""
    mods: set[str] = set()
    key = ""
    for part in combo.lower().replace(" ", "").split("+"):
        name = part.strip("<>")
        if name in MODIFIER_ALIASES:
            mods.add(MODIFIER_ALIASES[name])
        elif name:
            key = name
    if not key:
        raise ValueError(f"hotkey {combo!r} has no key")
    return frozenset(mods), key


def _modifier_of(key: Any) -> str | None:
    name = getattr(key, "name", None)
    if not name:
        return None
    for prefix in ("ctrl", "alt", "shift", "cmd"):
        if name == prefix or name.startswith(prefix + "_"):
            return prefix
    return None


def key_name(key: Any) -> str | None:
    vk = getattr(key, "vk", None)
    if isinstance(vk, int) and (0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39):
        return chr(vk).lower()
    char = getattr(key, "char", None)
    if char and char.isprintable():
        return char.lower()
    name = getattr(key, "name", None)
    return name.lower() if name else None


class HotkeyMatcher:
    def __init__(self, bindings: dict[str, Callable[[], None]]):
        self.bindings: dict[tuple[frozenset[str], str], Callable[[], None]] = {}
        for combo, fn in bindings.items():
            try:
                self.bindings[parse_combo(combo)] = fn
            except ValueError as exc:
                log.warning("%s", exc)
        self.pressed: set[str] = set()
        self._last_fire: dict[tuple[frozenset[str], str], float] = {}

    def on_press(self, key: Any) -> None:
        mod = _modifier_of(key)
        if mod:
            self.pressed.add(mod)
            return
        name = key_name(key)
        if not name:
            return
        combo = (self._current_mods(), name)
        fn = self.bindings.get(combo)
        if fn is None:
            return
        now = time.monotonic()
        if now - self._last_fire.get(combo, 0) < 1.0:  # debounce key repeat
            return
        self._last_fire[combo] = now
        threading.Thread(target=self._safe, args=(fn,), daemon=True).start()

    def _current_mods(self) -> frozenset[str]:
        """On Windows ask the OS (release events can be lost, e.g. after UAC prompts)."""
        if sys.platform == "win32":
            try:
                import ctypes

                state = ctypes.windll.user32.GetAsyncKeyState
                mods = set()
                if state(0x11) & 0x8000:
                    mods.add("ctrl")
                if state(0x12) & 0x8000:
                    mods.add("alt")
                if state(0x10) & 0x8000:
                    mods.add("shift")
                if (state(0x5B) & 0x8000) or (state(0x5C) & 0x8000):
                    mods.add("cmd")
                self.pressed = set(mods)
                return frozenset(mods)
            except Exception:
                pass
        return frozenset(self.pressed)

    def on_release(self, key: Any) -> None:
        mod = _modifier_of(key)
        if mod:
            self.pressed.discard(mod)

    @staticmethod
    def _safe(fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:
            log.exception("hotkey action failed")


# ----------------------------------------------------------------- Windows
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
_MOD_FLAGS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "shift": MOD_SHIFT, "cmd": MOD_WIN}


def win_combo(combo: str) -> tuple[int, int]:
    """'<ctrl>+<alt>+n' -> (MOD_CONTROL|MOD_ALT, VK_N)"""
    mods, key = parse_combo(combo)
    flags = 0
    for m in mods:
        flags |= _MOD_FLAGS[m]
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    elif key == "space":
        vk = 0x20
    else:
        raise ValueError(f"unsupported hotkey key {key!r} in {combo!r}")
    return flags, vk


class WinHotkeys(threading.Thread):
    """Uses RegisterHotKey: Windows only tells us about *our* key combos – no keyboard hook, no keylogging."""

    def __init__(self, bindings: dict[str, Callable[[], None]]):
        super().__init__(daemon=True, name="opstrail-hotkeys")
        self.bindings = bindings
        self.thread_id = 0
        self.registered: dict[int, tuple[str, Callable[[], None]]] = {}
        self.ready = threading.Event()

    def run(self) -> None:  # pragma: no cover - Windows only
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        self.thread_id = kernel32.GetCurrentThreadId()
        for idx, (combo, fn) in enumerate(self.bindings.items(), start=1):
            try:
                flags, vk = win_combo(combo)
            except ValueError as exc:
                log.warning("%s", exc)
                continue
            if user32.RegisterHotKey(None, idx, flags | MOD_NOREPEAT, vk):
                self.registered[idx] = (combo, fn)
            else:
                log.warning(
                    "hotkey %s could not be registered (used by another app?) – change it in config.toml, error %s",
                    combo,
                    ctypes.get_last_error(),
                )
        self.ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    item = self.registered.get(int(msg.wParam))
                    if item:
                        _allow_foreground()
                        threading.Thread(target=HotkeyMatcher._safe, args=(item[1],), daemon=True).start()
        finally:
            for idx in self.registered:
                user32.UnregisterHotKey(None, idx)

    def stop(self) -> None:  # pragma: no cover - Windows only
        if self.thread_id:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


def _allow_foreground() -> None:
    """Let the popup process we are about to start take keyboard focus."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
        except Exception:
            pass


def start(bindings: dict[str, Callable[[], None]]) -> Any | None:
    """Start global hotkeys. Windows: RegisterHotKey. Elsewhere: pynput listener (if installed)."""
    if sys.platform == "win32":
        worker = WinHotkeys(bindings)
        worker.start()
        worker.ready.wait(5)
        return worker
    try:
        from pynput import keyboard
    except Exception as exc:  # ImportError or no display
        log.warning("hotkeys disabled: %s", exc)
        return None
    matcher = HotkeyMatcher(bindings)
    listener = keyboard.Listener(on_press=matcher.on_press, on_release=matcher.on_release)
    listener.daemon = True
    listener.start()
    return listener
