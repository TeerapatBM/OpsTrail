"""Small tkinter popups launched by hotkeys (run in their own process: `opstrail popup <kind>`)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from opstrail.config import Config
from opstrail.events import make_event, write_inbox

FONT = ("Leelawadee UI", 10) if sys.platform == "win32" else ("TkDefaultFont", 10)


def _root(title: str) -> Any:
    import tkinter as tk

    root = tk.Tk()
    root.title(title)
    root.attributes("-topmost", True)
    root.resizable(False, False)
    try:
        root.option_add("*Font", FONT)
    except Exception:
        pass
    return root


def _center(root: Any, width: int, height: int) -> None:
    root.update_idletasks()
    x = (root.winfo_screenwidth() - width) // 2
    y = (root.winfo_screenheight() - height) // 3
    root.geometry(f"{width}x{height}+{x}+{y}")


def _force_foreground(root: Any) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.GetParent.argtypes = [ctypes.c_void_p]
        user32.GetParent.restype = ctypes.c_void_p
        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _focus(root: Any, widget: Any) -> None:
    root.lift()

    def grab() -> None:
        _force_foreground(root)
        root.focus_force()
        widget.focus_set()

    root.after(60, grab)


def toast(message: str, ms: int = 1800) -> None:
    import tkinter as tk

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    tk.Label(root, text=message, font=FONT, bg="#1f2937", fg="white", padx=16, pady=10).pack()
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    root.geometry(f"+{root.winfo_screenwidth() - w - 24}+{root.winfo_screenheight() - h - 72}")
    root.after(ms, root.destroy)
    root.mainloop()


def note(cfg: Config) -> None:
    import tkinter as tk

    root = _root("OpsTrail — Note")
    tk.Label(root, text="จดโน้ต: ทำอะไร / ทำไม / ผลเป็นยังไง   (Enter = บันทึก, Esc = ยกเลิก)", anchor="w").pack(
        fill="x", padx=10, pady=(10, 4)
    )
    entry = tk.Entry(root, width=70)
    entry.pack(padx=10, pady=(0, 10), fill="x")

    def save(_: Any = None) -> None:
        text = entry.get().strip()
        if text:
            write_inbox(cfg, make_event(cfg, "note", {"text": text}, source="hotkey"), "note")
        root.destroy()

    entry.bind("<Return>", save)
    root.bind("<Escape>", lambda _: root.destroy())
    _center(root, 560, 90)
    _focus(root, entry)
    root.mainloop()


def task(cfg: Config) -> None:
    import tkinter as tk

    from opstrail.service import OpsTrail

    svc = OpsTrail(cfg)
    svc.refresh()
    rows = svc.store.query("SELECT id, title FROM episodes WHERE open_task = 1 ORDER BY start_epoch DESC LIMIT 1")
    active = dict(rows[0]) if rows else None

    root = _root("OpsTrail — Task")
    if active:
        tk.Label(root, text=f"กำลังทำ: {active['title']}", anchor="w").pack(fill="x", padx=10, pady=(10, 2))
    tk.Label(root, text="ชื่องานใหม่ (Enter = เริ่มงาน, Esc = ยกเลิก)", anchor="w").pack(fill="x", padx=10, pady=(6, 2))
    entry = tk.Entry(root, width=70)
    entry.pack(padx=10, fill="x")
    buttons = tk.Frame(root)
    buttons.pack(fill="x", padx=10, pady=8)

    def start(_: Any = None) -> None:
        title = entry.get().strip()
        if title:
            write_inbox(cfg, make_event(cfg, "task", {"action": "start", "title": title}, source="hotkey"), "task")
        root.destroy()

    def stop() -> None:
        title = active["title"] if active else ""
        write_inbox(cfg, make_event(cfg, "task", {"action": "stop", "title": title}, source="hotkey"), "task")
        root.destroy()

    tk.Button(buttons, text="เริ่มงาน", command=start).pack(side="left")
    if active:
        tk.Button(buttons, text="จบงานปัจจุบัน", command=stop).pack(side="left", padx=6)
    entry.bind("<Return>", start)
    root.bind("<Escape>", lambda _: root.destroy())
    _center(root, 560, 150 if active else 120)
    _focus(root, entry)
    root.mainloop()


def shot(cfg: Config, path: str, app: str = "", title: str = "") -> None:
    """Ask for a caption, then record the screenshot event (also on Esc/close)."""
    import tkinter as tk

    saved = {"done": False}

    def record(caption: str = "") -> None:
        if saved["done"]:
            return
        saved["done"] = True
        data = {"path": path, "app": app, "title": title}
        if caption:
            data["caption"] = caption
        write_inbox(cfg, make_event(cfg, "screenshot", data, source="hotkey"), "shot")

    try:
        root = _root("OpsTrail — Screenshot")
    except Exception:
        record()
        return
    tk.Label(root, text=f"บันทึกรูปแล้ว:{Path(path).name} — ใส่คำอธิบาย (Enter) หรือ Esc เพื่อข้าม", anchor="w").pack(
        fill="x", padx=10, pady=(10, 4)
    )
    entry = tk.Entry(root, width=70)
    entry.pack(padx=10, pady=(0, 10), fill="x")

    def finish(_: Any = None, with_caption: bool = True) -> None:
        record(entry.get().strip() if with_caption else "")
        root.destroy()

    entry.bind("<Return>", finish)
    root.bind("<Escape>", lambda _: finish(with_caption=False))
    root.protocol("WM_DELETE_WINDOW", lambda: finish(with_caption=False))
    _center(root, 600, 90)
    _focus(root, entry)
    try:
        root.mainloop()
    finally:
        record()


def review(cfg: Config, date: str | None = None) -> None:
    """End-of-day review: rename work items and add the 'why' before the recap is finalised."""
    import tkinter as tk

    from opstrail.service import OpsTrail

    svc = OpsTrail(cfg)
    svc.refresh()
    day = date or cfg.today()
    episodes = svc.list_episodes(day)
    root = _root(f"OpsTrail — ทบทวนงานวันที่ {day}")
    if not episodes:
        tk.Label(root, text="วันนี้ยังไม่มีงานที่บันทึกไว้").pack(padx=20, pady=20)
        root.after(2500, root.destroy)
        root.mainloop()
        return
    tk.Label(
        root,
        text="แก้ชื่องานให้อ่านเข้าใจ และเติมโน้ตสั้นๆ (ผลลัพธ์/เหตุผล) — ช่วยให้เอกสารออกมาดีขึ้นมาก",
        anchor="w",
    ).grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(10, 6))
    tk.Label(root, text="เวลา").grid(row=1, column=0, sticky="w", padx=10)
    tk.Label(root, text="ชื่องาน").grid(row=1, column=1, sticky="w")
    tk.Label(root, text="โน้ต (ไม่บังคับ)").grid(row=1, column=2, sticky="w", padx=(0, 10))
    fields: list[tuple[dict, Any, Any]] = []
    for n, ep in enumerate(episodes[:15], start=2):
        tk.Label(root, text=f"{ep['time']} ({ep['active']})").grid(row=n, column=0, sticky="w", padx=10, pady=2)
        title_entry = tk.Entry(root, width=48)
        title_entry.insert(0, ep["title"])
        title_entry.grid(row=n, column=1, pady=2)
        note_entry = tk.Entry(root, width=48)
        note_entry.grid(row=n, column=2, padx=(6, 10), pady=2)
        fields.append((ep, title_entry, note_entry))
    if len(episodes) > 15:
        tk.Label(root, text=f"… และอีก {len(episodes) - 15} งาน (แก้ได้ผ่าน Claude/GPT)").grid(
            row=len(fields) + 2, column=0, columnspan=3, sticky="w", padx=10
        )

    def save() -> None:
        for ep, title_entry, note_entry in fields:
            new_title = title_entry.get().strip()
            new_note = note_entry.get().strip()
            svc.update_episode(
                ep["id"], title=new_title if new_title and new_title != ep["title"] else "", note=new_note
            )
        svc.daily_recap(day, save=True)
        root.destroy()

    bar = tk.Frame(root)
    bar.grid(row=len(fields) + 3, column=0, columnspan=3, sticky="e", padx=10, pady=10)
    tk.Button(bar, text="บันทึก", command=save).pack(side="right")
    tk.Button(bar, text="ข้าม", command=root.destroy).pack(side="right", padx=6)
    root.bind("<Escape>", lambda _: root.destroy())
    root.mainloop()


MEETING_SCAFFOLD = "ประเด็นที่คุย:\n- \n\nข้อสรุป / การตัดสินใจ:\n- \n\nAction items (ใคร / ทำอะไร / เมื่อไร):\n- "


def meeting(cfg: Config, episode_id: int) -> None:
    """After a meeting: capture what was discussed, decided and who does what."""
    import tkinter as tk

    from opstrail.service import OpsTrail

    svc = OpsTrail(cfg)
    ep = svc.store.get_episode(int(episode_id))
    if not ep:
        return
    root = _root("OpsTrail — สรุปประชุม")
    tk.Label(root, text=f"{ep['title']} ({svc.episode_header(ep)})", anchor="w").pack(fill="x", padx=10, pady=(10, 2))
    tk.Label(root, text="สรุปสั้นๆ ไว้ก่อนลืม — ใช้ทำบันทึกการประชุม/Delivery doc ได้ (Ctrl+Enter = บันทึก, Esc = ข้าม)",
             anchor="w").pack(fill="x", padx=10, pady=(0, 6))
    box = tk.Text(root, width=80, height=14, wrap="word")
    box.insert("1.0", MEETING_SCAFFOLD)
    box.pack(padx=10, fill="both", expand=True)

    def save(_: Any = None) -> str:
        text = box.get("1.0", "end").strip()
        if text and text.replace(" ", "") != MEETING_SCAFFOLD.replace(" ", "").strip():
            svc.add_note("สรุปประชุม:\n" + text, ep["id"], source="meeting-prompt")
        root.destroy()
        return "break"

    bar = tk.Frame(root)
    bar.pack(fill="x", padx=10, pady=8)
    tk.Button(bar, text="บันทึก", command=save).pack(side="right")
    tk.Button(bar, text="ข้าม", command=root.destroy).pack(side="right", padx=6)

    def speak() -> None:
        from opstrail.agent.osapi import spawn_popup

        if not spawn_popup(["voice", "--episode", str(ep["id"])]):
            toast("เปิด voice ไม่สำเร็จ กรุณาพิมพ์สรุปแทน")

    tk.Button(bar, text="พูดสรุป (Voice)", command=speak).pack(side="left")
    box.bind("<Control-Return>", save)
    root.bind("<Escape>", lambda _: root.destroy())
    _center(root, 680, 380)
    _focus(root, box)
    root.mainloop()


def voice(cfg: Config, episode_id: int | None = None) -> None:
    """Keep Tk on the main thread and SQLite/audio/model work on one worker."""
    import queue
    import threading
    import time

    from opstrail.service import OpsTrail
    from opstrail.voice import VoiceError, check_available, record_audio, transcribe_audio

    try:
        check_available(cfg)
    except VoiceError as exc:
        toast(str(exc), ms=8000)
        return
    import tkinter as tk

    root = _root("OpsTrail — Voice note")
    stop, cancel = threading.Event(), threading.Event()
    updates: queue.Queue = queue.Queue()
    started = time.monotonic()
    backend = cfg.data.get("voice", {}).get("backend", "local")
    label = tk.Label(root, text="กำลังเตรียมไมโครโฟน…", padx=12, pady=10)
    label.pack()
    tk.Label(root, text="เสียงอยู่ในเครื่อง" if backend == "local" else f"ส่งเสียงไป {backend} เพื่อถอดเสียง").pack()
    stop_button = tk.Button(root, text="หยุดและถอดเสียง", command=stop.set)
    stop_button.pack(pady=8)

    def cancel_capture(_: Any = None) -> None:
        cancel.set()
        stop.set()
        root.withdraw()  # worker still cleans WAV, including an in-flight API call

    tk.Button(root, text="ยกเลิก", command=cancel_capture).pack(pady=(0, 8))
    root.protocol("WM_DELETE_WINDOW", cancel_capture)
    root.bind("<Escape>", cancel_capture)

    def record(path, stopped, cancelled):
        updates.put(("recording", None))
        record_audio(path, stopped, cancelled)

    def transcribe(config, path):
        updates.put(("transcribing", None))
        return transcribe_audio(config, path)

    def work() -> None:
        svc = None
        try:
            svc = OpsTrail(cfg)
            result = svc.record_voice(episode_id, stop=stop, cancel=cancel,
                                      recorder=record, transcriber=transcribe)
            updates.put(("done", "บันทึก voice note แล้ว" if result and result.get("event_id") else "ยกเลิก voice note แล้ว"))
        except VoiceError as exc:
            updates.put(("done", str(exc)))
        except Exception:
            updates.put(("done", "บันทึก voice note ไม่สำเร็จ กรุณาลองใหม่"))
        finally:
            if svc is not None:
                svc.store.close()

    state = "preparing"

    def poll() -> None:
        nonlocal state, started
        if cfg.is_paused():
            cancel_capture()
        while True:
            try:
                state, message = updates.get_nowait()
            except queue.Empty:
                break
            if state == "recording":
                started = time.monotonic()
            elif state == "done":
                root.destroy()
                if not cancel.is_set():
                    toast(message, ms=5000)
                return
        if state == "recording":
            elapsed = min(60, int(time.monotonic() - started))
            label.config(text=f"กำลังบันทึกเสียง {elapsed:02d} / 60 วินาที")
            if elapsed >= 60:
                stop.set()
        elif state == "transcribing":
            label.config(text="กำลังถอดเสียง… (ครั้งแรกอาจดาวน์โหลด model)")
            stop_button.config(state="disabled")
        root.after(100, poll)

    _center(root, 420, 200)
    threading.Thread(target=work, name="opstrail-voice", daemon=False).start()
    root.after(100, poll)
    root.mainloop()
