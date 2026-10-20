"""Deterministic daily worklog (no LLM needed). An AI can polish it later."""

from __future__ import annotations

from typing import Any

from opstrail.config import Config
from opstrail.render import command_lines, fmt_duration, hhmm
from opstrail.store import Store

SOP_MIN_COMMANDS = 8
DELIVERY_MIN_ACTIVE_S = 60 * 60


def build_recap(store: Store, cfg: Config, date: str) -> str:
    tz = cfg.tz
    episodes = store.episodes_between(date)
    all_events = store.events_for_date(date)
    notes = [e for e in all_events if e["type"] == "note"]
    active = sum(float(e.get("duration_s") or 0) for e in all_events if e["type"] == "window")
    if not active:
        active = sum((ep.get("stats") or {}).get("active_s", 0) for ep in episodes)
    commands = sum(1 for e in all_events if e["type"] in ("shell", "ai"))
    projects: dict[str, float] = {}
    for ep in episodes:
        key = (ep.get("stats") or {}).get("project") or (ep["tags"][0] if ep["tags"] else None)
        if key:
            projects[key] = projects.get(key, 0) + (ep.get("stats") or {}).get("active_s", 0)

    L: list[str] = []
    L.append(f"# Daily Worklog — {date}")
    L.append("")
    L.append("| รายการ | รายละเอียด |")
    L.append("|---|---|")
    L.append(f"| ผู้จัดทำ | {cfg.author} |")
    L.append(f"| วันที่ | {date} |")
    L.append(f"| เวลาทำงาน (active) | {fmt_duration(active)} |")
    L.append(f"| จำนวนงาน (work items) | {len(episodes)} |")
    L.append(f"| คำสั่งที่รัน | {commands} |")
    L.append("| สร้างโดย | OpsTrail auto-recap (ยังไม่ได้ขัดเกลาโดย AI) |")
    L.append("")
    L.append("## 1. สรุปภาพรวม (Summary)")
    L.append("")
    if not episodes:
        L.append("- ไม่มีกิจกรรมที่บันทึกไว้ในวันนี้")
    else:
        L.append(f"- ทำงานทั้งหมด {len(episodes)} งาน รวมเวลา active ประมาณ {fmt_duration(active)}")
        if projects:
            top = sorted(projects.items(), key=lambda kv: kv[1], reverse=True)[:3]
            L.append("- โฟกัสหลัก: " + ", ".join(f"{name} ({fmt_duration(sec)})" for name, sec in top))
        longest = max(episodes, key=lambda e: (e.get("stats") or {}).get("active_s", 0))
        L.append(f"- งานที่ใช้เวลามากที่สุด: {longest['title']}")
    L.append("")
    L.append("## 2. งานที่ทำ (Work items)")
    L.append("")
    if episodes:
        L.append("| # | เวลา | งาน | ระยะเวลา | คำสั่ง |")
        L.append("|---|---|---|---|---|")
        for n, ep in enumerate(episodes, 1):
            st = ep.get("stats") or {}
            L.append(
                f"| {n} | {hhmm(ep['start_epoch'], tz)}–{hhmm(ep['end_epoch'], tz)} | {ep['title']} (#{ep['id']}) "
                f"| {fmt_duration(st.get('active_s'))} | {st.get('commands', 0)} |"
            )
        L.append("")
    issues: list[str] = []
    for n, ep in enumerate(episodes, 1):
        st = ep.get("stats") or {}
        events = store.events_for_episode(ep["id"])
        L.append(f"### 2.{n} {ep['title']}")
        L.append("")
        L.append(f"- เวลา: {hhmm(ep['start_epoch'], tz)}–{hhmm(ep['end_epoch'], tz)} ({fmt_duration(st.get('active_s'))})")
        if st.get("top_apps"):
            L.append(f"- เครื่องมือที่ใช้: {', '.join(st['top_apps'])}")
        if st.get("targets"):
            L.append(f"- ระบบ/เครื่องปลายทาง: {', '.join(st['targets'])}")
        ep_notes = [e for e in events if e["type"] == "note"]
        for ev in ep_notes:
            L.append(f"- โน้ต {hhmm(ev['epoch'], tz)}: {ev.get('text')}")
        L.append("- ผลลัพธ์: [TODO: ระบุผลลัพธ์/สถานะของงานนี้]")
        cmds = command_lines(events, tz, limit=8)
        if cmds:
            L.append("")
            L.append("```text")
            L.extend(cmds)
            L.append("```")
        shots = [e for e in events if e["type"] == "screenshot"]
        if shots:
            L.append("")
            L.append(f"- Screenshots: {', '.join('shot://' + str(e['id']) for e in shots)}")
        if st.get("failed_commands"):
            issues.append(f"- {ep['title']}: มีคำสั่งที่ fail {st['failed_commands']} ครั้ง [TODO: สาเหตุ/วิธีแก้]")
        L.append("")
    L.append("## 3. ปัญหา / Blockers")
    L.append("")
    L.extend(issues or ["- ไม่พบปัญหาจากข้อมูลที่บันทึก [TODO: เพิ่มถ้ามี]"])
    L.append("")
    L.append("## 4. โน้ตและการตัดสินใจ (Notes & decisions)")
    L.append("")
    if notes:
        for ev in notes:
            L.append(f"- {hhmm(ev['epoch'], tz)} {ev.get('text')}")
    else:
        L.append("- ไม่มีโน้ต — ครั้งหน้ากด Ctrl+Alt+N เพื่อจดเหตุผล/การตัดสินใจระหว่างทำงาน")
    L.append("")
    L.append("## 5. แผนวันถัดไป (Next)")
    L.append("")
    L.append("- [TODO]")
    L.append("")
    L.append("## 6. งานที่ควรทำเป็นเอกสาร (Doc candidates)")
    L.append("")
    candidates = doc_candidates(episodes)
    if candidates:
        for item in candidates:
            L.append(f"- {item}")
    else:
        L.append("- ยังไม่มีงานที่เข้าเกณฑ์")
    L.append("")
    return "\n".join(L)


def doc_candidates(episodes: list[dict[str, Any]]) -> list[str]:
    out = []
    for ep in episodes:
        st = ep.get("stats") or {}
        if st.get("commands", 0) >= SOP_MIN_COMMANDS:
            out.append(f"Episode #{ep['id']} “{ep['title']}” → **SOP** ({st['commands']} คำสั่ง ทำซ้ำได้)")
        elif st.get("active_s", 0) >= DELIVERY_MIN_ACTIVE_S and (st.get("project") or ep.get("tags")):
            out.append(f"Episode #{ep['id']} “{ep['title']}” → **Delivery doc** (งานโปรเจกต์ใช้เวลานาน)")
    return out
