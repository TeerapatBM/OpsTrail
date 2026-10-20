"""Evaluation harness ("golden days"): the shared referee for Claude/GPT changes.

Deterministic checks (always): episode grouping, meetings, titles, redaction, source-pack facts.
LLM checks (--llm): generate a document with the configured provider, then check required facts,
forbidden strings (secrets), fact-check (invented values), skeleton coverage and TODO count.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from opstrail.config import REPO_ROOT, Config, load_config

EVALS_DIR = REPO_ROOT / "evals"


@dataclass
class CaseResult:
    name: str
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    doc: str = ""
    seconds: float = 0.0

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, bool(ok), detail))

    @property
    def passed(self) -> int:
        return sum(1 for _, ok, _ in self.checks if ok)

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.checks)


def load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or EVALS_DIR / "cases.toml"
    with path.open("rb") as fh:
        return tomllib.load(fh).get("case", [])


def _config_for(home: Path, case: dict[str, Any], llm_from: Config | None) -> Config:
    home.mkdir(parents=True, exist_ok=True)
    projects = case.get("projects") or {}
    lines = ['[general]', 'timezone = "Asia/Bangkok"', 'author = "Eval"', f'export_dir = "{(home / "exports").as_posix()}"',
             '[capture]']
    for key, value in (case.get("capture") or {}).items():
        lines.append(f"{key} = {json.dumps(value)}")
    lines.append('[projects]')
    for name, kws in projects.items():
        lines.append(f'"{name}" = {json.dumps(list(kws), ensure_ascii=False)}')
    (home / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if llm_from is not None:
        for name in ("llm.json",):
            src = llm_from.home / name
            if src.exists():
                shutil.copy2(src, home / name)
        style = llm_from.home / "style"
        if style.is_dir():
            shutil.copytree(style, home / "style", dirs_exist_ok=True)
    return load_config(home)


def run_case(case: dict[str, Any], *, use_llm: bool = False, llm_from: Config | None = None) -> CaseResult:
    from opstrail.service import OpsTrail

    res = CaseResult(case.get("name", "case"))
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="opstrail-eval-") as tmp:
        cfg = _config_for(Path(tmp) / "home", case, llm_from if use_llm else None)
        day_file = EVALS_DIR / case["day"]
        shutil.copy2(day_file, cfg.inbox_dir / "fixture.jsonl")
        svc = OpsTrail(cfg)
        try:
            svc.refresh()
            date = case["date"]
            eps = svc.list_episodes(date)
            exp = case.get("episodes", {})
            n = len(eps)
            res.check("episode count", exp.get("count_min", 0) <= n <= exp.get("count_max", 99),
                      f"{n} (expected {exp.get('count_min', 0)}–{exp.get('count_max', 99)}): "
                      + " | ".join(f"{e['time']} {e['title']}" for e in eps))
            meetings = [e for e in eps if e["origin"] == "meeting"]
            if "meetings" in exp:
                res.check("meetings detected", len(meetings) == exp["meetings"], f"{len(meetings)}")
            for needle in exp.get("titles_contain", []):
                res.check(f"title contains “{needle}”", any(needle in e["title"] for e in eps))
            if exp.get("meeting_time"):
                res.check("meeting time exact", any(m["time"] == exp["meeting_time"] for m in meetings),
                          ", ".join(m["time"] for m in meetings))
            secrets = [s for s in case.get("doc", {}).get("must_not_contain", []) if s]
            stored = json.dumps([[e["text"], e["data"]] for e in svc.store.events_for_date(date)], ensure_ascii=False)
            for secret in secrets:
                res.check(f"secret “{secret[:4]}…” redacted in store", secret not in stored)

            doc = case.get("doc")
            pack_needles = (case.get("pack") or {}).get("must_contain", [])
            if doc and pack_needles:
                pick = [e["id"] for e in eps if doc.get("episodes_with_title", "") in e["title"]]
                pack = ""
                if pick:
                    sid = svc.start_doc_session(doc["template"], f"pack {res.name}", pick)["session_id"]
                    pack = svc.source_pack(sid, mode="api")
                for needle in pack_needles:
                    res.check(f"source pack has “{needle}”", needle in pack)

            if use_llm and doc:
                pick = [e["id"] for e in eps if doc.get("episodes_with_title", "") in e["title"]]
                if not pick:
                    res.check("doc episodes found", False, doc.get("episodes_with_title", ""))
                else:
                    sid = svc.start_doc_session(doc["template"], f"eval {res.name}", pick)["session_id"]
                    out = svc.generate_draft(sid)
                    md = out["markdown"]
                    res.doc = md
                    for needle in doc.get("must_mention", []):
                        res.check(f"doc mentions “{needle}”", needle.lower() in md.lower())
                    for bad in doc.get("must_not_contain", []):
                        res.check(f"doc has no “{bad[:4]}…”", bad not in md)
                    fc = out["fact_check"]
                    res.check("fact-check", len(fc["unsupported"]) <= doc.get("max_unsupported", 0),
                              ", ".join(u["value"] for u in fc["unsupported"]) or "clean")
                    tpl = svc.template(doc["template"])
                    heads = [h.strip() for h in re.findall(r"^##\s+(.+)$", tpl.skeleton, re.M)]
                    heads = [re.sub(r"^\d+\.\s*", "", h).split("(")[0].strip() for h in heads]
                    covered = [h for h in heads if h and h.lower() in md.lower()]
                    ratio = len(covered) / len(heads) if heads else 1.0
                    res.check("skeleton sections covered ≥ 70%", ratio >= 0.7, f"{len(covered)}/{len(heads)}")
                    res.check("TODOs reported", True, str(fc["todos"]))
        finally:
            svc.store.close()
    res.seconds = round(time.time() - t0, 1)
    return res


def run(*, use_llm: bool = False, only: str = "", cases_file: Path | None = None) -> list[CaseResult]:
    llm_from = load_config() if use_llm else None
    out = []
    for case in load_cases(cases_file):
        if only and case.get("name") != only:
            continue
        out.append(run_case(case, use_llm=use_llm, llm_from=llm_from))
    return out


def report(results: list[CaseResult], use_llm: bool) -> str:
    total = sum(len(r.checks) for r in results)
    passed = sum(r.passed for r in results)
    lines = [f"# OpsTrail eval — {time.strftime('%Y-%m-%d %H:%M')}",
             f"mode: {'deterministic + LLM' if use_llm else 'deterministic'} · score **{passed}/{total}**", ""]
    for r in results:
        lines.append(f"## {'✅' if r.ok else '❌'} {r.name} ({r.passed}/{len(r.checks)}, {r.seconds}s)")
        for name, ok, detail in r.checks:
            lines.append(f"- {'✓' if ok else '✗'} {name}" + (f" — {detail}" if detail else ""))
        if r.doc:
            lines += ["", "<details><summary>generated document</summary>", "", r.doc, "", "</details>"]
        lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------ export a real day
IPV4 = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")


def export_day(svc: Any, date: str, out: Path, anonymize: bool = True) -> int:
    """Write a day's (already redacted) events as a fixture. IPs/users/hosts are replaced consistently."""
    ip_map: dict[str, str] = {}

    def anon_ip(m: re.Match[str]) -> str:
        ip = m.group(0)
        if ip not in ip_map:
            ip_map[ip] = f"10.99.{len(ip_map) // 250}.{len(ip_map) % 250 + 1}"
        return ip_map[ip]

    events = svc.store.events_for_date(date)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for e in events:
            if e["type"] in ("idle", "system"):
                continue
            data = e["data"]
            if anonymize:
                data = json.loads(IPV4.sub(anon_ip, json.dumps(data, ensure_ascii=False)))
                if e["type"] == "screenshot":
                    data["path"] = "shots/redacted.png"
            item = {"v": 1, "ts": e["ts"], "type": e["type"], "source": e.get("source") or "export",
                    "host": "PC-01" if anonymize else e.get("host"), "user": "engineer" if anonymize else e.get("user"),
                    "data": data}
            if e.get("duration_s"):
                item["duration_s"] = e["duration_s"]
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    return len(events)
