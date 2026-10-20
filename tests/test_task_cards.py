"""Task cards in docs/tasks must stay parseable by scripts/duo.ps1 (same regexes as Get-Cards).

A card without a Status line is treated as `todo` by the runner, so a new card that is not meant to be
built yet (e.g. the T-2xx team-mode cards before Bro approves docs/team-mode.md) must say so explicitly.
"""
from __future__ import annotations

import re
from pathlib import Path

TASKS = Path(__file__).resolve().parents[1] / "docs" / "tasks"
STATUSES = {"todo", "done", "blocked", "needs-bro"}


def _cards() -> list[Path]:
    return sorted(p for p in TASKS.glob("T-*.md") if re.search(r"T-\d+[^/]*\.md$", p.name))


def test_every_card_has_heading_status_priority_and_owner():
    cards = _cards()
    assert cards
    ids = []
    for path in cards:
        text = path.read_text(encoding="utf-8")
        head = re.search(r"(?m)^#\s+(T-\d+)\s+(.+)$", text)
        assert head, path.name
        assert path.name.startswith(head.group(1) + "-"), path.name
        ids.append(head.group(1))
        status = re.search(r"(?m)^\*\*Status:\*\*\s*([A-Za-z-]+)", text)
        assert status and status.group(1).lower() in STATUSES, path.name
        assert re.search(r"\*\*Priority:\*\*\s*(\d+)", text), path.name
        owner = re.search(r"(?m)^\*\*Suggested owner:\*\*(.*)$", text)
        assert owner and ("Claude" in owner.group(1) or "GPT" in owner.group(1)), path.name
    assert len(ids) == len(set(ids))


def test_team_mode_cards_and_design_reference_each_other():
    design = (TASKS.parent / "team-mode.md").read_text(encoding="utf-8")
    team_cards = [p for p in _cards() if p.name.startswith("T-2")]
    assert team_cards
    for path in team_cards:
        card_id = path.name[:5]
        assert card_id in design, f"{card_id} missing from docs/team-mode.md §13"
        text = path.read_text(encoding="utf-8")
        assert "docs/team-mode.md" in text, path.name
