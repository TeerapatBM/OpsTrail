"""Configuration loading and well-known paths."""

from __future__ import annotations

import copy
import getpass
import os
import socket
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

# <repo>/src/opstrail/config.py -> <repo>
REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CONFIG_TOML = """\
# OpsTrail configuration
# แก้ไฟล์นี้แล้ว restart agent (opstrail agent) เพื่อให้มีผล

[general]
user = ""              # ว่าง = ใช้ชื่อ user ของ OS
timezone = ""          # ว่าง = ใช้ timezone ของเครื่อง เช่น "Asia/Bangkok"
doc_language = "th"    # th = ภาษาไทยปน technical term อังกฤษ, en = English
export_dir = ""        # ว่าง = ~/Documents/OpsTrail
templates_dir = ""     # ว่าง = <repo>/templates
author = ""            # ชื่อผู้จัดทำที่ใส่ในเอกสาร (ว่าง = user)

[capture]
browser_keep_query = false
exclude_domains = ["mail.google.com", "outlook.live.com", "mail.yahoo.com", "proton.me", "kasikornbank.com", "kbank.co.th", "scb.co.th", "krungthai.com", "bangkokbank.com", "krungsri.com"]
poll_interval_s = 5          # ตรวจหน้าต่างที่ใช้งานทุกกี่วินาที
idle_threshold_s = 300       # ไม่ขยับเมาส์/คีย์บอร์ดเกินนี้ = idle
min_window_s = 3             # หน้าต่างที่โฟกัสสั้นกว่านี้ไม่บันทึก
screenshot_mode = "window"   # window = เฉพาะหน้าต่างที่ใช้งาน, screen = ทั้งจอ
auto_screenshot_title_patterns = []   # regex ของ title ที่ให้ถ่ายรูปอัตโนมัติเมื่อสลับเข้า
auto_screenshot_min_interval_s = 120
shell_output = false         # true = เก็บผลลัพธ์ของคำสั่ง PowerShell (บรรทัดแรกๆ) ไว้เขียน "ผลลัพธ์ที่คาดหวัง" ใน SOP (เปิด PowerShell ใหม่ให้มีผล)
shell_output_lines = 15      # เก็บผลลัพธ์กี่บรรทัดต่อคำสั่ง
exclude_apps = [
  "line.exe", "whatsapp.exe", "telegram.exe", "messenger.exe",
  "keepass.exe", "keepassxc.exe", "1password.exe", "bitwarden.exe",
]
exclude_title_patterns = [
  "(?i)inprivate", "(?i)incognito", "(?i)private browsing",
  "(?i)internet banking", "(?i)k plus", "(?i)scb easy", "(?i)krungthai next",
]

[hotkeys]
note = "<ctrl>+<alt>+n"        # จดโน้ตสั้นๆ (ทำไม/ตัดสินใจอะไร)
screenshot = "<ctrl>+<alt>+s"  # ถ่ายรูปหน้าต่างปัจจุบันไว้ใช้ใน SOP
task = "<ctrl>+<alt>+t"        # เริ่ม/จบงาน (manual episode)
pause = "<ctrl>+<alt>+p"       # หยุด/เริ่มบันทึกชั่วคราว

[episodes]
idle_split_min = 25    # เว้นช่วงนานเกินนี้ = เริ่มงานใหม่
min_run_min = 5        # เปลี่ยน project ต่อเนื่องอย่างน้อยกี่นาทีถึงจะแยกงาน

[recap]
teams_webhook_url = "" # ตั้งค่าผ่าน Settings เท่านั้น; URL จริงเก็บแบบเข้ารหัสใน recap.json
auto = true            # สร้าง daily worklog อัตโนมัติ
time = "18:00"         # เวลาที่สร้าง
review_popup = true    # เปิดหน้าต่างให้ทบทวน/ใส่โน้ตแต่ละงานตอนสร้าง recap

[projects]
# ชื่องาน/ลูกค้า = keywords (ไม่สนตัวพิมพ์เล็กใหญ่) ใช้จัดกลุ่มงานอัตโนมัติ
# "Splunk" = ["splunk", "splunkd"]
# "Sentinel" = ["sentinel", "log analytics", "kql"]

[redaction]
extra_patterns = []    # regex เพิ่มเติมที่ต้องการปิดบัง

[export]
docx_font = "Leelawadee UI"   # ฟอนต์ไทยที่มีใน Windows ทุกเครื่อง (หรือ "TH Sarabun New")
docx_font_size = 10.5         # ถ้าใช้ TH Sarabun New แนะนำ 15-16
image_width_in = 6.0

[meetings]
summary_prompt = true  # หลังประชุมจบ ให้เด้งหน้าต่างให้สรุปประเด็น/การตัดสินใจ/action items
min_minutes = 10       # ประชุมสั้นกว่านี้ไม่ต้องถาม
grace_minutes = 3      # รอหลังหน้าต่างประชุมหายไปกี่นาทีถึงถือว่าจบ
merge_gap_min = 10     # ออกจากหน้าต่างประชุมไม่เกินกี่นาทียังนับเป็นประชุมเดิม
detect_background = true  # หน้าต่างประชุมยังเปิดอยู่ (เช่น share screen แล้วไปทำงานใน terminal) = ยังนับว่าอยู่ในประชุม

[web]
enabled = true         # agent เปิดหน้าเว็บที่ http://127.0.0.1:<port> (เปิดได้เฉพาะเครื่องนี้)
port = 8765
open_on_recap = true   # ตอนสร้าง daily recap ให้เปิดหน้าเว็บสำหรับทบทวนงาน (แทน popup)

[mcp]
http_host = "127.0.0.1"
http_port = 8766
"""

DEFAULTS: dict[str, Any] = tomllib.loads(DEFAULT_CONFIG_TOML)


def opstrail_home() -> Path:
    env = os.environ.get("OPSTRAIL_HOME")
    return Path(env).expanduser() if env else Path.home() / ".opstrail"


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


@dataclass
class Config:
    home: Path
    data: dict[str, Any]

    # ---- sections -------------------------------------------------------
    @property
    def general(self) -> dict[str, Any]:
        return self.data["general"]

    @property
    def capture(self) -> dict[str, Any]:
        return self.data["capture"]

    @property
    def hotkeys(self) -> dict[str, Any]:
        return self.data["hotkeys"]

    @property
    def episodes(self) -> dict[str, Any]:
        return self.data["episodes"]

    @property
    def recap(self) -> dict[str, Any]:
        return self.data["recap"]

    @property
    def projects(self) -> dict[str, list[str]]:
        return self.data.get("projects") or {}

    @property
    def redaction(self) -> dict[str, Any]:
        return self.data["redaction"]

    @property
    def mcp(self) -> dict[str, Any]:
        return self.data["mcp"]

    @property
    def export(self) -> dict[str, Any]:
        return self.data["export"]

    @property
    def web(self) -> dict[str, Any]:
        return self.data["web"]

    # ---- paths ----------------------------------------------------------
    @property
    def config_path(self) -> Path:
        return self.home / "config.toml"

    @property
    def db_path(self) -> Path:
        return self.home / "opstrail.db"

    @property
    def inbox_dir(self) -> Path:
        return self.home / "inbox"

    @property
    def shots_dir(self) -> Path:
        return self.home / "shots"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def paused_flag(self) -> Path:
        return self.home / "paused"

    @property
    def export_dir(self) -> Path:
        value = (self.general.get("export_dir") or "").strip()
        return Path(value).expanduser() if value else Path.home() / "Documents" / "OpsTrail"

    @property
    def templates_dir(self) -> Path:
        value = (self.general.get("templates_dir") or "").strip() or os.environ.get("OPSTRAIL_TEMPLATES", "")
        return Path(value).expanduser() if value else REPO_ROOT / "templates"

    # ---- identity -------------------------------------------------------
    @property
    def user(self) -> str:
        value = (self.general.get("user") or "").strip()
        if value:
            return value
        try:
            return getpass.getuser()
        except Exception:  # pragma: no cover
            return "unknown"

    @property
    def profile(self) -> dict[str, Any]:
        """Per-user profile edited from the web Settings page (~/.opstrail/profile.json)."""
        import json

        try:
            data = json.loads((self.home / "profile.json").read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_profile(self, **values: Any) -> dict[str, Any]:
        import json

        data = self.profile
        for key, value in values.items():
            data[key] = str(value or "").strip()
        self.ensure_dirs()
        (self.home / "profile.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    @property
    def author(self) -> str:
        return (
            (self.profile.get("author") or "").strip()
            or (self.general.get("author") or "").strip()
            or self.user
        )

    @property
    def host(self) -> str:
        return socket.gethostname()

    @property
    def tz(self) -> tzinfo:
        name = (self.general.get("timezone") or "").strip()
        if name:
            try:
                from zoneinfo import ZoneInfo

                return ZoneInfo(name)
            except Exception:
                pass
        return datetime.now().astimezone().tzinfo  # type: ignore[return-value]

    @property
    def doc_language(self) -> str:
        return (self.general.get("doc_language") or "th").strip().lower()

    # ---- state ----------------------------------------------------------
    def is_paused(self) -> bool:
        return self.paused_flag.exists()

    def set_paused(self, paused: bool) -> None:
        self.ensure_dirs()
        if paused:
            self.paused_flag.write_text(datetime.now(self.tz).isoformat(timespec="seconds"), encoding="utf-8")
        elif self.paused_flag.exists():
            self.paused_flag.unlink()

    def ensure_dirs(self) -> None:
        for path in (self.home, self.inbox_dir, self.shots_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)

    def today(self) -> str:
        return datetime.now(self.tz).date().isoformat()


def load_config(home: Path | str | None = None, *, create: bool = True) -> Config:
    """Load config.toml (creating it with defaults when missing)."""
    home_path = Path(home).expanduser() if home else opstrail_home()
    cfg_file = home_path / "config.toml"
    user_data: dict[str, Any] = {}
    if cfg_file.exists():
        with cfg_file.open("rb") as fh:
            user_data = tomllib.load(fh)
    elif create:
        home_path.mkdir(parents=True, exist_ok=True)
        cfg_file.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    cfg = Config(home=home_path, data=_deep_merge(DEFAULTS, user_data))
    if create:
        cfg.ensure_dirs()
    return cfg
