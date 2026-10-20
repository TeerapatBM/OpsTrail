# Claude ↔ GPT ↔ Bro — วิธีทำงานร่วมกันบน GitHub

Repo: https://github.com/TeerapatBM/OpsTrail (private)

```
            docs/tasks/T-xxx.md  ──(init-github.ps1 -CreateIssues)──►  GitHub Issue
                                                                         │
                    ┌────────────────────────────────────────────────────┤ Bro assign
                    ▼                                                    ▼
   GPT: Copilot coding agent / Codex                     Claude: Claude Code (VS Code / Cowork)
        เปิด branch + PR                                      เปิด branch + PR
                    │                                                    │
                    └───────────────► Pull Request ◄─────────────────────┘
                                         │
              CI (Windows + Linux): pytest · eval (golden days) · PowerShell 5.1 parse
              Claude review (GitHub Action) · GPT review (Copilot review / Codex review)
                                         │
                                   Bro กด Merge
```

## ตั้งค่าครั้งแรก (ทำครั้งเดียว)

1. ติดตั้ง Git ถ้ายังไม่มี: `winget install -e --id Git.Git` (และ GitHub CLI ถ้าจะสร้าง issue อัตโนมัติ: `winget install -e --id GitHub.cli` → `gh auth login`)
2. ใน folder OpsTrail รัน
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\init-github.ps1 -CreateIssues
   ```
   → push โค้ดขึ้น repo, สร้าง `.github/` (CI, Claude review, Copilot setup, templates), สร้าง issue จาก task card
3. GitHub → Settings → Secrets and variables → Actions → `ANTHROPIC_API_KEY`
   (ใช้ key ที่ **ผูกกับ workspace เดียว** — key แบบหลาย workspace ต้องส่ง header เพิ่มซึ่ง action อาจไม่รองรับ)
4. GPT:
   - **Copilot coding agent**: เปิด issue → Assignees → เลือก *Copilot* (ต้องมี Copilot plan ที่เปิด coding agent)
   - **Codex**: ใน ChatGPT → Codex → เชื่อม GitHub repo นี้ → สั่ง "ทำ issue #N ตาม AGENTS.md"
5. Claude: เปิด repo ใน VS Code (Claude Code extension) หรือสั่งผมใน Cowork (ถ้าให้สิทธิ์ GitHub กับ session) → "ทำ issue #N"

## กติกา (สรุปจาก AGENTS.md)

| เรื่อง | กติกา |
|---|---|
| งานหนึ่งชิ้น | 1 issue = 1 branch = 1 PR, ชื่อ branch `t-101-browser-extension`, commit prefix `[claude]` / `[gpt]` |
| ก่อนเริ่ม | อ่าน `AGENTS.md`, `SPEC.md`, task card; ถ้าจะเปลี่ยน contract ให้แก้ SPEC ใน PR เดียวกัน |
| ก่อนเปิด PR | `pytest -q` ผ่าน, `opstrail eval` ผ่าน (คะแนนไม่ต่ำกว่า main), อัปเดต `docs/HANDOFF.md` |
| Review | งานของ GPT → Claude review (อัตโนมัติ) · งานของ Claude → ขอ GPT review (Copilot "Request review" หรือ Codex review) |
| ตัดสินเมื่อเห็นต่าง | ดูผล eval เป็นหลัก ถ้ายังเสมอ → Bro ตัดสิน บันทึกใน Decision log |
| ข้อมูลจริง | ห้าม commit ข้อมูลลูกค้า — fixture จาก `opstrail eval export` ต้องอ่านทวนก่อนทุกครั้ง |

## แบ่งงานที่แนะนำ

- **Claude**: capture/segmentation, security, Windows internals, M365/Graph, eval harness, team-mode design (T-102, T-106, T-109, T-110)
- **GPT**: browser extension, web UI, voice, Teams digest, tray, reviewer pass (T-101, T-103, T-104, T-105, T-107, T-108)
- **Bro**: ทดสอบบนเครื่องจริง, เพิ่ม golden days จากงานจริง, ใส่ format เอกสารของทีมใน `templates/`, merge

## Tuning รายสัปดาห์ (15 นาที)

1. ใช้งานตามปกติ แก้ draft ที่ AI เขียนให้ถูกใจแล้วกดบันทึก (ระบบเก็บสิ่งที่แก้ไว้อัตโนมัติ)
2. หน้าเว็บ → ตั้งค่า → *สไตล์การเขียน* → ✨ เรียนรู้จากการแก้ไข (ต่อ template)
3. วันที่ระบบแยกงานผิด → `opstrail eval export --date …` → เพิ่มเป็นเคสใน `evals/cases.toml` → เปิด issue ให้ Claude/GPT แก้ จนเคสผ่าน
4. Rules ที่จำแนกกิจกรรมเฉพาะของคุณ (portal ลูกค้า, ชื่อเครื่อง) → `~/.opstrail/activity_rules.toml`
