"""scripts/duo.ps1 (Claude Code + Codex autopilot): static checks + an end-to-end run with fake AI CLIs.

The end-to-end test runs the real PowerShell script (Windows PowerShell 5.1 on Windows, pwsh elsewhere if
installed) against a throw-away git repo whose path contains spaces. The fake `claude` / `codex` are a small
Python script: the builder edits a file, the reviewer first asks for changes, then approves.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CARDS = sorted((REPO / "docs" / "tasks").glob("T-*.md"))


def test_task_cards_have_status_priority_and_owner():
    assert CARDS
    for card in CARDS:
        text = card.read_text(encoding="utf-8")
        assert re.search(r"(?m)^#\s+T-\d+\s+\S", text), card.name
        assert re.search(r"(?m)^\*\*Suggested owner:\*\*.*(Claude|GPT)", text), card.name
        assert re.search(r"\*\*Status:\*\*\s*(todo|done|blocked|needs-bro)\b", text), card.name
        assert re.search(r"\*\*Priority:\*\*\s*\d+", text), card.name


def test_prompts_and_permission_files():
    prompts = REPO / "scripts" / "duo" / "prompts"
    review = (prompts / "review.md").read_text(encoding="utf-8")
    assert "VERDICT: APPROVE" in review and "VERDICT: CHANGES" in review and "READ-ONLY" in review
    for name in ("build.md", "fix.md"):
        text = (prompts / name).read_text(encoding="utf-8")
        assert "git commit" in text and "{{TASK_ID}}" in text and "{{ENVNOTE}}" in text
    build = json.loads((REPO / "scripts" / "duo" / "claude-build.json").read_text(encoding="utf-8"))
    rev = json.loads((REPO / "scripts" / "duo" / "claude-review.json").read_text(encoding="utf-8"))
    inter = json.loads((REPO / "setup" / "claude" / "settings.json").read_text(encoding="utf-8"))
    for s in (build, rev, inter):
        deny = s["permissions"]["deny"]
        assert "Read(~/.opstrail/**)" in deny and s["env"]["OPSTRAIL_NO_CAPTURE"] == "1"
    for s in (build, rev):
        assert "Bash(git push *)" in s["permissions"]["deny"] and "Bash(gh *)" in s["permissions"]["deny"]
    assert "Edit" in rev["permissions"]["deny"] and "Edit" not in rev["permissions"]["allow"]
    assert "Bash(git commit *)" not in inter["permissions"]["deny"]  # interactive sessions may commit
    codex = (REPO / "setup" / "codex" / "config.toml").read_text(encoding="utf-8")
    assert 'approval_policy = "never"' in codex and 'sandbox_mode = "workspace-write"' in codex


def test_duo_script_is_ascii():
    for p in (REPO / "scripts").rglob("*.ps1"):
        assert all(ord(c) < 128 for c in p.read_text(encoding="utf-8")), p


FAKE_AGENT = r'''
import os, sys, pathlib
who = sys.argv[1]
args = sys.argv[2:]
prompt = sys.stdin.read()
log = pathlib.Path(os.environ["FAKE_LOG"])
with open(log / (who + ".calls"), "a", encoding="utf-8") as f:
    f.write(" ".join(args) + " | key=" + str(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"))
            + " | nocap=" + str(os.environ.get("OPSTRAIL_NO_CAPTURE")) + "\n")
out = None
if "-o" in args:
    out = args[args.index("-o") + 1]
if "the REVIEWER" in prompt:
    counter = log / (who + ".reviews")
    n = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(n))
    msg = "- major: please also handle X\n\nVERDICT: CHANGES" if n == 1 else "No findings.\n\nVERDICT: APPROVE"
else:
    with open("docs/demo.md", "a", encoding="utf-8") as f:
        f.write(who + " was here (" + ("fix" if "This is round" in prompt else "build") + ")\n")
    msg = 'SUMMARY: demo done\nCHANGES:\n- docs/demo.md: "quoted" line\nTESTS: ok\nOPEN: none'
if out:
    pathlib.Path(out).write_text(msg + "\n", encoding="utf-8")
    print("codex progress noise")
else:
    print(msg)
'''

CARD = """# T-001 Demo card for the duo test

**Suggested owner:** Claude · **Phase:** test · **Size:** S

**Status:** todo · **Priority:** 1

## Goal
Write a line into docs/demo.md.
"""


def _shell():
    if sys.platform == "win32":
        exe = shutil.which("powershell")
        return [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"] if exe else None
    exe = shutil.which("pwsh")
    return [exe, "-NoProfile", "-File"] if exe else None


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.mark.skipif(_shell() is None or shutil.which("git") is None, reason="PowerShell or git not available")
def test_duo_end_to_end_with_fake_agents(tmp_path):
    root = tmp_path / "My Repo" / "OpsTrail"
    (root / "docs" / "tasks").mkdir(parents=True)
    shutil.copytree(REPO / "scripts", root / "scripts")
    shutil.copytree(REPO / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO / "evals", root / "evals")
    shutil.copytree(REPO / "templates", root / "templates")
    shutil.copy(REPO / "pyproject.toml", root / "pyproject.toml")
    shutil.copy(REPO / ".gitignore", root / ".gitignore")
    (root / "tests").mkdir()
    (root / "tests" / "test_demo.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (root / "docs" / "tasks" / "T-001-demo.md").write_text(CARD, encoding="utf-8")
    (root / "docs" / "demo.md").write_text("# demo\n", encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "bro@example.com")
    _git(root, "config", "user.name", "Bro")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")

    fakes = tmp_path / "fake bin"
    log = tmp_path / "log"
    fakes.mkdir()
    log.mkdir()
    (fakes / "fake_agent.py").write_text(FAKE_AGENT, encoding="utf-8")
    env = dict(os.environ, FAKE_LOG=str(log), OPSTRAIL_DUO_PYTHON=sys.executable,
               ANTHROPIC_API_KEY="sk-must-not-leak", OPENAI_API_KEY="sk-must-not-leak")
    env.pop("OPSTRAIL_NO_CAPTURE", None)
    for who in ("claude", "codex"):
        if sys.platform == "win32":
            f = fakes / f"{who}.cmd"
            f.write_text(f'@"{sys.executable}" "{fakes / "fake_agent.py"}" {who} %*\r\n', encoding="ascii")
        else:
            f = fakes / who
            f.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fakes / "fake_agent.py"}" {who} "$@"\n', encoding="utf-8")
            f.chmod(0o755)
        env[f"OPSTRAIL_DUO_{who.upper()}"] = str(f)

    cmd = _shell() + [str(root / "scripts" / "duo.ps1"), "-NoNotify", "-NoDeploy", "-GateTimeoutMin", "5"]
    p = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=600)
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    assert "local-merged" in out, out
    # builder claude -> reviewer codex asked for changes once -> claude fixed -> codex approved
    assert (root / "docs" / "demo.md").read_text(encoding="utf-8").count("claude was here") == 2
    assert "**Status:** done" in (root / "docs" / "tasks" / "T-001-demo.md").read_text(encoding="utf-8")
    subjects = _git(root, "log", "--format=%s")
    assert "[duo] T-001: mark done" in subjects and "[claude] T-001: Demo card for the duo test (round 2)" in subjects
    calls = (log / "claude.calls").read_text(encoding="utf-8") + (log / "codex.calls").read_text(encoding="utf-8")
    assert "sk-must-not-leak" not in calls and "nocap=1" in calls
    assert "--permission-mode dontAsk" in calls and "--sandbox read-only" in calls
    assert not (root.parent / "OpsTrail-duo" / "T-001").exists()          # worktree cleaned up
    state = (root / ".duo" / "state.tsv").read_text(encoding="utf-8")
    assert "T-001\t" in state and "\tlocal-merged\t" in state
    # nothing left to do now
    p2 = subprocess.run(cmd + ["-DryRun"], cwd=root, env=env, capture_output=True, text=True, timeout=120)
    assert p2.returncode == 0 and "Nothing to do" in p2.stdout, p2.stdout + p2.stderr
