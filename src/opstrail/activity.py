"""Activity classification: what kind of work an event is (meeting, chat, terminal, console, …).

Rules live in src/opstrail/data/activity_rules.toml; users can add their own in
~/.opstrail/activity_rules.toml (checked first). See that file for the format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

DEFAULT_RULES = Path(__file__).parent / "data" / "activity_rules.toml"
BROWSERS = {"msedge.exe", "chrome.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "iexplore.exe", "arc.exe"}

ACTIVITIES = {
    "meeting": "ประชุม",
    "chat": "แชท",
    "email": "อีเมล",
    "terminal": "Terminal",
    "remote": "Remote",
    "console": "Console",
    "research": "ค้นข้อมูล",
    "docs": "เอกสาร",
    "code": "เขียนโค้ด",
    "ai": "AI assistant",
    "files": "ไฟล์",
    "other": "อื่นๆ",
}


@dataclass
class Rule:
    activity: str
    types: set[str] = field(default_factory=lambda: {"window", "screenshot"})
    apps: set[str] = field(default_factory=set)
    browser: bool = False
    title: re.Pattern[str] | None = None
    title_exclude: re.Pattern[str] | None = None
    cmd: re.Pattern[str] | None = None
    subject: str = ""

    def match(self, type_: str, app: str, title: str, cmd: str) -> tuple[str, str] | None:
        if type_ not in self.types:
            return None
        if self.apps or self.browser:
            if not (app in self.apps or (self.browser and app in BROWSERS)):
                return None
        found: re.Match[str] | None = None
        if self.title is not None:
            found = self.title.search(title)
            if not found:
                return None
        if self.title_exclude is not None and self.title_exclude.search(title):
            return None
        if self.cmd is not None:
            found = self.cmd.search(cmd)
            if not found:
                return None
        subject = self.subject
        if found is not None and "subject" in found.groupdict() and found.group("subject"):
            subject = found.group("subject").strip()
        return self.activity, subject


def _compile(raw: dict[str, Any]) -> Rule | None:
    activity = str(raw.get("activity") or "").strip()
    if activity not in ACTIVITIES:
        return None
    apps = {str(a).lower() for a in raw.get("apps", [])}
    browser = "@browser" in apps
    apps.discard("@browser")

    def rx(key: str) -> re.Pattern[str] | None:
        value = raw.get(key)
        if not value:
            return None
        try:
            return re.compile(str(value))
        except re.error:
            return None

    types = set(raw.get("types") or ["window", "screenshot"])
    return Rule(
        activity=activity,
        types=types,
        apps=apps,
        browser=browser,
        title=rx("title_regex"),
        title_exclude=rx("title_exclude"),
        cmd=rx("cmd_regex"),
        subject=str(raw.get("subject") or ""),
    )


def load_rules(user_file: Path | None = None) -> list[Rule]:
    rules: list[Rule] = []
    for path in [p for p in (user_file, DEFAULT_RULES) if p]:
        if not path.exists():
            continue
        try:
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        except Exception:
            continue
        for raw in data.get("rule", []):
            rule = _compile(raw)
            if rule:
                rules.append(rule)
    return rules


class Classifier:
    def __init__(self, user_file: Path | None = None):
        self.rules = load_rules(user_file)

    def classify(self, type_: str, data: dict[str, Any]) -> tuple[str, str]:
        if type_ in ("note", "task", "idle", "system"):
            return type_ if type_ in ("note", "task") else "other", ""
        app = str(data.get("app") or "").lower()
        title = str(data.get("title") or "")
        cmd = str(data.get("cmd") or data.get("file") or "")
        for rule in self.rules:
            hit = rule.match(type_, app, title, cmd)
            if hit:
                return hit[0], hit[1][:120]
        return "other", ""


def label(activity: str) -> str:
    return ACTIVITIES.get(activity, activity)


_CACHE: dict[str, tuple[float, Classifier]] = {}


def classifier_for(home: Path) -> Classifier:
    """Cached classifier; reloads when either rules file changes."""
    user_file = home / "activity_rules.toml"
    stamp = 0.0
    for p in (user_file, DEFAULT_RULES):
        try:
            stamp += p.stat().st_mtime
        except OSError:
            pass
    key = str(user_file)
    cached = _CACHE.get(key)
    if cached and cached[0] == stamp:
        return cached[1]
    clf = Classifier(user_file)
    _CACHE[key] = (stamp, clf)
    return clf


def classify_row(home: Path, row: dict[str, Any]) -> dict[str, Any]:
    activity, subject = classifier_for(home).classify(row["type"], row.get("data") or {})
    row["activity"] = activity
    row["subject"] = subject
    return row
