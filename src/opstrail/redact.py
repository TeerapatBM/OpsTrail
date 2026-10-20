"""Secret redaction applied to every captured string before it is stored."""

from __future__ import annotations

import re
from typing import Any, Iterable

MASK = "[REDACTED]"

_QUOTED_OR_WORD = r"(?:\"[^\"]*\"|'[^']*'|[^\s\"';&|]+)"

# (pattern, replacement). Replacements keep the "label" part so the document
# still says *that* a secret was used, without the value.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # PEM private keys (multi-line; a block cut off by output truncation is masked to the end)
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S), MASK),
    # Authorization headers / bearer tokens
    (re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic|token)\s+)[A-Za-z0-9._~+/=-]+"), r"\1" + MASK),
    (re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]{16,}"), r"\1" + MASK),
    # JWT
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), MASK),
    # Well-known token formats
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), MASK),
    (re.compile(r"\bASIA[0-9A-Z]{16}\b"), MASK),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), MASK),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"), MASK),
    (re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}\b"), MASK),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), MASK),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), MASK),
    (re.compile(r"\bLTAI[0-9A-Za-z]{12,24}\b"), MASK),  # Alibaba Cloud AccessKey ID
    # Azure connection strings / SAS
    (re.compile(r"(?i)((?:AccountKey|SharedAccessKey|SharedSecretValue)\s*=\s*)[^;\s\"']+"), r"\1" + MASK),
    (re.compile(r"(?i)([?&]sig=)[^&\s\"']+"), r"\1" + MASK),
    # Credentials inside URLs: scheme://user:pass@host
    (re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.-]*://[^:/\s@]+:)[^@\s/]+(@)"), r"\1" + MASK + r"\2"),
    # PowerShell secure strings
    (re.compile(r"(?i)(ConvertTo-SecureString\s+(?:-String\s+)?)" + _QUOTED_OR_WORD), r"\1" + MASK),
    # CLI flags carrying secrets: --password x, --password=x, -Password x, /p:x
    (
        re.compile(
            r"(?i)((?:^|\s)(?:--?|/)(?:password|passwd|pwd|pass|secret|token|api[-_]?key|apikey|"
            r"client[-_]?secret|access[-_]?key|secret[-_]?key|sas[-_]?token|passphrase|"
            r"account[-_]?key|storage[-_]?key)(?:\s+|[=:]))" + _QUOTED_OR_WORD
        ),
        r"\1" + MASK,
    ),
    # key=value / key: value pairs (also env-style SPLUNK_PASSWORD=…, e.g. a printed .env file)
    (
        re.compile(
            r"(?i)(\b(?:[a-z0-9]+_)*(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|client[_-]?secret|"
            r"access[_-]?key|secret[_-]?key|private[_-]?key|aws_secret_access_key|passphrase)"
            r"\s*[:=]\s*)" + _QUOTED_OR_WORD
        ),
        r"\1" + MASK,
    ),
    # user:password pairs passed as CLI credentials: splunk -auth admin:pw, curl -u user:pw, --user user:pw
    (re.compile(r"(?i)((?:^|\s)(?:-auth|--auth|-u|--user|-U)\s+['\"]?[^:\s'\"]+:)[^\s'\"]+"), r"\1" + MASK),
    # sshpass -p secret
    (re.compile(r"(?i)(\bsshpass\s+-p\s*)" + _QUOTED_OR_WORD), r"\1" + MASK),
    # net user <name> <password> [/add]
    (re.compile(r"(?i)(\bnet\s+user\s+\S+\s+)(?!/)" + _QUOTED_OR_WORD), r"\1" + MASK),
]

# mysql/mysqldump -pSECRET (no space) — only for those tools, -p is "port" elsewhere.
_MYSQL = re.compile(r"(?i)(\b(?:mysql|mysqldump|mysqladmin|mariadb)\b[^\n]*?\s-p)(?!\s)(\S+)")


def compile_extra(patterns: Iterable[str] | None) -> list[re.Pattern[str]]:
    compiled = []
    for pat in patterns or []:
        try:
            compiled.append(re.compile(pat))
        except re.error:
            continue
    return compiled


def redact_text(text: str, extra: list[re.Pattern[str]] | None = None) -> str:
    if not text or not isinstance(text, str):
        return text
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    out = _MYSQL.sub(lambda m: m.group(1) + MASK, out)
    for pattern in extra or []:
        out = pattern.sub(MASK, out)
    return out


def redact_obj(value: Any, extra: list[re.Pattern[str]] | None = None) -> Any:
    """Recursively redact every string in dicts/lists."""
    if isinstance(value, str):
        return redact_text(value, extra)
    if isinstance(value, dict):
        return {k: redact_obj(v, extra) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_obj(v, extra) for v in value]
    return value
