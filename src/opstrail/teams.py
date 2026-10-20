"""Opt-in Teams Workflows digest; secrets never enter TOML or public settings."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import urllib.request
from urllib.parse import urlsplit
from typing import Any

from opstrail.config import Config
from opstrail.recap import DELIVERY_MIN_ACTIVE_S, SOP_MIN_COMMANDS
from opstrail.redact import compile_extra, redact_text
from opstrail.render import hhmm
from opstrail.secretstore import protect, unprotect

log = logging.getLogger("opstrail.teams")
TIMEOUT_S = 10
MAX_ITEMS = 15


def validate_url(value: str) -> None:
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" or (
            parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
        )) and parsed.hostname and parsed.username is None and parsed.password is None and not parsed.fragment
        valid = valid and not any(c.isspace() or ord(c) < 32 for c in value)
        parsed.port  # reject malformed ports without exposing the URL
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Webhook URL ต้องเป็น HTTPS (HTTP ใช้ได้เฉพาะ loopback สำหรับทดสอบ)")


def webhook_url(cfg: Config) -> str:
    path = cfg.home / "recap.json"
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = unprotect(data.get("teams_webhook_url", ""))
        if value:
            validate_url(value)
        return value
    except Exception:
        # Exceptions can contain secret URLs or DPAPI input. Never include them.
        log.warning("Teams: อ่าน Webhook ไม่สำเร็จ; ปิดการส่งชั่วคราว")
        return ""


def public_settings(cfg: Config) -> dict[str, bool]:
    return {"has_webhook": bool(webhook_url(cfg))}


def save_settings(cfg: Config, value: str | None = None, clear: bool = False) -> dict[str, bool]:
    if not clear and (value is None or not value.strip()):
        return public_settings(cfg)
    if clear:
        token = ""
    else:
        value = value.strip()
        validate_url(value)
        token = protect(value)
    # Atomic replacement prevents the agent reading a partially written secret.
    fd, name = tempfile.mkstemp(prefix="recap-", suffix=".tmp", dir=cfg.home)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump({"teams_webhook_url": token}, out)
        os.chmod(name, 0o600)
        os.replace(name, cfg.home / "recap.json")
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return public_settings(cfg)


def build_card(cfg: Config, day: str, episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Project only titles and time ranges; generated titles are capture-derived.

    Meeting subjects originate in window titles too. Use generic labels until
    the user/AI renames them. Never render event text, stats or notes.
    """
    extra = compile_extra(cfg.redaction.get("extra_patterns", []))
    sections: dict[str, list[str]] = {"งานวันนี้": [], "ประชุม": [], "งานที่ควรทำเป็นเอกสาร": []}
    for ep in episodes:
        meeting = ep.get("origin") == "meeting"
        title = f"{'ประชุม' if meeting else 'งาน'} #{ep['id']}"
        if ep.get("title_locked"):
            title = str(ep["title"])
        title = redact_text(title, extra)
        # Remove Markdown links/mentions so a title cannot add outbound actions.
        title = re.sub(r"[\[\]()<>!*_`#\\]", "", " ".join(title.split()))[:100]
        times = f"{hhmm(ep['start_epoch'], cfg.tz)}–{hhmm(ep['end_epoch'], cfg.tz)}"
        line = f"{times} · {title}"
        sections["ประชุม" if meeting else "งานวันนี้"].append(line)
        stats = ep.get("stats") or {}
        candidate = ""
        if stats.get("commands", 0) >= SOP_MIN_COMMANDS:
            candidate = "SOP"
        elif stats.get("active_s", 0) >= DELIVERY_MIN_ACTIVE_S and (stats.get("project") or ep.get("tags")):
            candidate = "Delivery doc"
        if candidate:
            sections["งานที่ควรทำเป็นเอกสาร"].append(f"{line} · {candidate}")
    body = [{"type": "TextBlock", "text": f"สรุปงานประจำวัน {day}", "weight": "Bolder", "wrap": True}]
    for heading, lines in sections.items():
        body.append({"type": "TextBlock", "text": heading, "weight": "Bolder", "wrap": True})
        text = "\n\n".join(lines[:MAX_ITEMS]) or "ไม่มีรายการ"
        if len(lines) > MAX_ITEMS:
            text += f"\n\n… อีก {len(lines) - MAX_ITEMS} รายการ (ดูใน OpsTrail)"
        body.append({"type": "TextBlock", "text": text, "wrap": True})
    return {"type": "message", "attachments": [{
        "contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
        "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard", "version": "1.4", "body": body},
    }]}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def deliver(url: str, payload: dict[str, Any]) -> bool:
    """Two bounded attempts. Logs intentionally exclude URLs, bodies and exceptions."""
    try:
        validate_url(url)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        opener = urllib.request.build_opener(_NoRedirect)
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
                with opener.open(req, timeout=TIMEOUT_S) as response:
                    if 200 <= response.status < 300:
                        return True
            except Exception:
                pass
            log.warning("Teams: ส่ง digest ไม่สำเร็จ (ครั้งที่ %s/2)", attempt + 1)
    except Exception:
        log.warning("Teams: เตรียมการส่ง digest ไม่สำเร็จ")
    return False
