"""Quality loop: learn from the user's edits, style lessons, and a deterministic fact-check of drafts."""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from opstrail.config import Config

AI_AUTHORS = ("anthropic:", "openai:", "azure:", "ai", "opstrail-auto")
MAX_DIFF = 4000

IPV4 = re.compile(r"\b(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?:/\d{1,2})?(?::\d{1,5})?\b")
VERSION = re.compile(r"\b\d+\.\d+\.\d+(?:\.\d+)?\b")
HOST = re.compile(r"\b(?=[\w-]*[a-zA-Z])(?=[\w-]*\d)[a-zA-Z][\w]*-[\w-]*\d[\w-]*(?:\.[\w-]+)*\b|\b[a-zA-Z][\w-]*(?:\.[\w-]+){2,}\b")
PORT = re.compile(r"(?i)\bport\s+(\d{2,5})\b")
IGNORE_HOSTS = re.compile(
    r"(?i)(microsoft\.com|azure\.com|windows\.net|splunk\.com|github\.com|google\.com|anthropic\.com|openai\.com|"
    r"python\.org|example\.(com|org)|\.md$|\.docx$|\.png$|\.ps1$|\.py$|\.exe$|\.deb$|\.rpm$|\.msi$|\.zip$|\.json$|\.toml$|\.conf$|\.log$|"
    r"^utf-8$|^x86-64$|^amd64$|^sha-?256$|^tls1|^mp4$|"
    r"^(sop|doc|req|cr|inc|chg|task|t|rfc|itsm|sr|ritm|kb|cve)-)"
)


def is_ai_author(author: str) -> bool:
    return any(str(author or "").startswith(a) for a in AI_AUTHORS)


def make_diff(before: str, after: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(), after.splitlines(), fromfile="ai-draft", tofile="user-final", n=1, lineterm=""
    )
    text = "\n".join(lines)
    return text[:MAX_DIFF] + ("\n…" if len(text) > MAX_DIFF else "")


# ------------------------------------------------------------------ style lessons
def style_path(cfg: Config, template: str) -> Path:
    safe = re.sub(r"[^\w-]", "_", template)
    return cfg.home / "style" / f"{safe}.md"


def read_style(cfg: Config, template: str) -> str:
    try:
        return style_path(cfg, template).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_style(cfg: Config, template: str, text: str) -> str:
    path = style_path(cfg, template)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return text.strip()


LEARN_SYSTEM = (
    "You maintain a short style guide for one document type. You receive the current guide and diffs between an "
    "AI draft and the version the user finally kept. Infer durable preferences (structure, wording, level of "
    "detail, what to remove/add, terminology, language mix). Ignore one-off factual corrections. Output ONLY the "
    "updated guide as 3–12 concise Thai bullet points (technical terms in English). No preface."
)


def learn_prompt(current: str, diffs: list[str]) -> str:
    parts = ["## Current style guide", current or "(empty)", "", "## Recent edits (unified diffs, '-' = AI, '+' = user)"]
    for i, d in enumerate(diffs, 1):
        parts += [f"### Edit {i}", "```diff", d, "```"]
    return "\n".join(parts)


# ---------------------------------------------------------------------- fact-check
def _facts(text: str) -> dict[str, set[str]]:
    hosts = {h for h in HOST.findall(text) if not IGNORE_HOSTS.search(h)}
    return {
        "ip": set(IPV4.findall(text)),
        "version": set(VERSION.findall(text)) - {m.split(":")[0] for m in IPV4.findall(text)},
        "host": hosts,
        "port": set(PORT.findall(text)),
    }


def fact_check(markdown: str, sources: str, skeleton: str = "") -> dict:
    """Values in the draft (IPs, versions, hostnames, ports) that appear nowhere in the captured sources."""
    doc = _facts(markdown)
    src_low = (sources + "\n" + skeleton).lower()
    unsupported: list[dict[str, str]] = []
    checked = 0
    for kind, values in doc.items():
        for value in sorted(values):
            checked += 1
            probe = value.lower()
            if kind == "ip":
                probe = value.split("/")[0].split(":")[0]
            if probe not in src_low:
                unsupported.append({"kind": kind, "value": value})
    todos = len(re.findall(r"\[TODO", markdown))
    return {"checked": checked, "unsupported": unsupported, "todos": todos, "ok": not unsupported}
