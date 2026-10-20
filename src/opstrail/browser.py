"""Local browser pairing and privacy policy; no raw capture is written here."""
from __future__ import annotations

import re
import secrets
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from opstrail.config import Config
from opstrail.locks import file_lock


def pairing_token(cfg: Config) -> str:
    """Create once under a cross-process lock; never include it in status/logs."""
    path = cfg.home / "browser_token"
    with file_lock(cfg.home / "browser_token.lock") as locked:
        if not locked:
            raise ValueError("ไม่สามารถเปิด browser token ได้ กรุณาลองใหม่")
        if not path.exists():
            with path.open("x", encoding="ascii") as f:
                path.chmod(0o600)
                f.write(secrets.token_urlsafe(32))
        value = path.read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
            raise ValueError("browser token ไม่ถูกต้อง กรุณาลบไฟล์ browser_token แล้วลองใหม่")
        return value


def valid_token(cfg: Config, supplied: str) -> bool:
    try:
        expected = (cfg.home / "browser_token").read_text(encoding="ascii").strip()
        return bool(re.fullmatch(r"[A-Za-z0-9_-]{43}", expected)) and secrets.compare_digest(
            expected.encode("ascii"), supplied.encode("utf-8"))
    except (OSError, UnicodeError):
        return False


def capture_data(cfg: Config, payload: dict[str, Any]) -> dict[str, str] | None:
    """Validate before redaction; strip credentials and query parts (including SPA fragments)."""
    if payload.get("incognito", False) is not False:
        raise ValueError("ไม่รับข้อมูลจาก Incognito / InPrivate")
    url, title = payload.get("url"), payload.get("title")
    if not isinstance(url, str) or not url or len(url) > 16000 or not isinstance(title, str) or len(title) > 4000:
        raise ValueError("URL หรือ title ไม่ถูกต้อง")
    if type(payload.get("tab_id")) is not int or payload["tab_id"] < 0:
        raise ValueError("tab_id ไม่ถูกต้อง")
    try:
        parts = urlsplit(url)
        domain = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
        if parts.scheme not in ("http", "https") or not domain or any(c.isspace() for c in url):
            raise ValueError
    except ValueError:
        raise ValueError("รองรับเฉพาะ HTTP/HTTPS URL ที่ถูกต้อง") from None
    if cfg.is_paused():
        return None
    for pattern in cfg.capture.get("exclude_title_patterns", []):
        try:
            if re.search(pattern, title):
                return None
        except re.error:
            return None  # fail closed on a broken privacy rule
    for excluded in cfg.capture.get("exclude_domains", []):
        name = str(excluded).lower().strip().lstrip("*.").rstrip(".")
        if name and (domain == name or domain.endswith("." + name)):
            return None
    host = f"[{domain}]" if ":" in domain else domain
    if port is not None:
        host += f":{port}"
    keep = cfg.capture.get("browser_keep_query", False)
    fragment = parts.fragment if keep else parts.fragment.split("?", 1)[0]
    return {"url": urlunsplit((parts.scheme, host, parts.path, parts.query if keep else "", fragment)),
            "title": title, "domain": domain}
