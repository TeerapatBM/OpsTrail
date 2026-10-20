from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import pytest

from opstrail.config import load_config
from opstrail.service import OpsTrail


def tiny_png(path: Path, w: int = 4, h: int = 3) -> Path:
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("OPSTRAIL_HOME", str(h))
    (h).mkdir()
    (h / "config.toml").write_text(
        """
[general]
timezone = "Asia/Bangkok"
export_dir = "%s"
author = "Tester"
[projects]
"Splunk" = ["splunk"]
"Sentinel" = ["sentinel", "kql"]
"""
        % (tmp_path / "exports").as_posix(),
        encoding="utf-8",
    )
    return h


@pytest.fixture()
def cfg(home):
    return load_config(home)


@pytest.fixture()
def svc(cfg):
    s = OpsTrail(cfg)
    yield s
    s.store.close()


DAY = "2026-10-19"


def at(hh: int, mm: int, ss: int = 0) -> str:
    return f"{DAY}T{hh:02d}:{mm:02d}:{ss:02d}+07:00"


def write_jsonl(cfg, name: str, events: list[dict]) -> Path:
    path = cfg.inbox_dir / f"{name}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return path


def shell(ts: str, cmd: str, ok: bool = True, cwd: str = "C:\\work") -> dict:
    return {"v": 1, "ts": ts, "type": "shell", "source": "powershell", "data": {"cmd": cmd, "cwd": cwd, "success": ok}}


def window(ts: str, app: str, title: str, dur: float) -> dict:
    return {"v": 1, "ts": ts, "type": "window", "source": "agent", "duration_s": dur, "data": {"app": app, "title": title}}


def note(ts: str, text: str) -> dict:
    return {"v": 1, "ts": ts, "type": "note", "source": "hotkey", "data": {"text": text}}


@pytest.fixture()
def sample_day(cfg, tmp_path):
    """A realistic day: Splunk work in the morning, a long lunch, Sentinel KQL in the afternoon."""
    shot = tiny_png(cfg.shots_dir / DAY / "094000.png")
    events = [
        window(at(9, 0), "msedge.exe", "Splunk Docs - Install a universal forwarder - Microsoft Edge", 600),
        shell(at(9, 10), "ssh admin@splunk-svr"),
        shell(at(9, 12), "sudo dpkg -i splunkforwarder-9.3.0-linux-amd64.deb"),
        shell(at(9, 14), "/opt/splunkforwarder/bin/splunk start --accept-license --answer-yes --password Sup3rS3cret"),
        shell(at(9, 15), "/opt/splunkforwarder/bin/splunk add forward-server 10.0.0.5:9997", ok=False),
        shell(at(9, 16), "/opt/splunkforwarder/bin/splunk add forward-server 10.0.0.5:9997"),
        note(at(9, 20), "ใช้ port 9997 ตาม design ของลูกค้า"),
        window(at(9, 20), "windowsterminal.exe", "admin@splunk-svr: ~", 1500),
        {"v": 1, "ts": at(9, 40), "type": "screenshot", "source": "hotkey",
         "data": {"path": str(shot), "app": "msedge.exe", "title": "Splunk Web - Forwarder Management", "caption": "UF connected"}},
        window(at(13, 0), "msedge.exe", "Microsoft Sentinel - Logs - KQL query", 1800),
        shell(at(13, 5), "az monitor log-analytics query -w ws1 --analytics-query 'SecurityEvent | take 10'"),
        note(at(13, 30), "สร้าง analytic rule สำหรับ brute force"),
    ]
    write_jsonl(cfg, "sample", events)
    return DAY
