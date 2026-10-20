# Claude ↔ GPT ↔ Bro — ทำงานร่วมกันแบบอัตโนมัติ (ใช้แค่ subscription ไม่ใช้ API)

Repo: https://github.com/TeerapatBM/OpsTrail (private)

ตัวหลักคือ `scripts/duo.ps1` ("duo autopilot") ที่รันบนเครื่อง Bro และสั่ง **Claude Code** (login ด้วย Claude Pro/Max)
กับ **Codex** (login ด้วย ChatGPT Plus/Pro) ให้ผลัดกันเขียนโค้ดและตรวจงานกันเอง จนกว่าจะผ่าน
โดยไม่ต้องกด approve อะไรเลย

```
 docs/tasks/T-xxx.md  (**Status:** todo · **Priority:** n)
          │  duo.ps1 เลือก card ที่ priority สูงสุด
          ▼
 git worktree ใหม่ ..\OpsTrail-duo\T-xxx  (branch duo/T-xxx จาก origin/main — ตัวที่คุณใช้อยู่ไม่ถูกแตะ)
          │
          ├─► BUILDER = เจ้าของ card (Claude หรือ GPT)  เขียนโค้ด + test + อัปเดต SPEC/HANDOFF
          ├─► GATE    = duo.ps1 รัน pytest + opstrail eval เองบนเครื่องคุณ (Windows จริง)
          ├─► REVIEWER = อีกตัว อ่าน diff แบบ read-only → VERDICT: APPROVE | CHANGES
          │      ไม่ผ่าน → builder แก้ตาม review/ผล test (สูงสุด 3 รอบ)
          ▼
 ผ่านทั้ง gate + review → PR (label duo) → รอ CI → squash merge → git pull + restart agent ให้เอง
 ไม่ผ่าน → PR label needs-bro (ไม่ merge) — คุณมาดูทีหลังเมื่อว่าง
          ▼
 แจ้งเตือนมุมขวาล่างของ Windows + สรุปใน .duo\last-run.md
```

## ค่าใช้จ่าย

| ส่วน | ใช้อะไร | เสียเงินเพิ่มไหม |
|---|---|---|
| Claude เขียน/ตรวจ | Claude Code login ด้วย Claude Pro/Max | ไม่ — ใช้ usage ของ subscription |
| GPT เขียน/ตรวจ | Codex CLI login ด้วย "Sign in with ChatGPT" | ไม่ — ใช้ usage ของ ChatGPT plan |
| Test + eval | Python บนเครื่องคุณ | ไม่ |
| CI บน GitHub | GitHub Actions minutes ของ private repo | ไม่ (อยู่ในโควตาฟรีรายเดือน; runner Windows กินโควตาเร็วกว่า Linux) |
| Claude review บน GitHub (ไม่บังคับ) | `CLAUDE_CODE_OAUTH_TOKEN` จาก `claude setup-token` | ไม่ — subscription; PR ของ duo ถูกข้าม (ตรวจในเครื่องแล้ว) |

`duo.ps1` **ลบ** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` ฯลฯ ออกจาก environment ของ AI ทุกครั้ง จึงไม่มีทางเผลอใช้ API credit
ถ้าโควตา subscription หมดกลางทาง duo จะหยุดเอง (exit 3) แล้วทำต่อในรอบถัดไป ไม่นับเป็นความล้มเหลว

## ตั้งค่าครั้งแรก (ประมาณ 15 นาที ทำครั้งเดียว)

เปิด PowerShell ใน folder OpsTrail แล้วทำตามลำดับ:

1. **Git + GitHub CLI** (ถ้ายังไม่มี)
   ```powershell
   winget install -e --id Git.Git
   winget install -e --id GitHub.cli
   gh auth login                     # GitHub.com → HTTPS → Login with a web browser
   ```
2. **Claude Code** แล้ว login ด้วย subscription
   ```powershell
   irm https://claude.ai/install.ps1 | iex
   claude                            # พิมพ์ /login → เลือก Claude account (Pro/Max) ไม่ใช่ API key → /exit
   ```
3. **Codex** แล้ว login ด้วย ChatGPT (ต้องมี Node.js: `winget install -e --id OpenJS.NodeJS.LTS`)
   ```powershell
   npm install -g @openai/codex
   codex login                       # เลือก Sign in with ChatGPT
   ```
4. **ขึ้น GitHub** (ถ้ายังไม่ได้ทำ)
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\init-github.ps1
   ```
5. **ตั้งค่า duo** — copy config ของทั้งสองตัว (ไม่มี permission prompt), ตรวจว่า login ครบ, สร้าง label บน GitHub
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\duo.ps1 -Setup
   powershell -ExecutionPolicy Bypass -File .\scripts\duo.ps1 -DryRun      # ดูว่าจะทำ task ไหน ใครทำ
   ```
6. **ให้ทำงานทุกคืนเอง** (เช่น 22:30 คืนละ 2 งาน — เปิดเครื่อง เสียบปลั๊กไว้ เครื่อง sleep ได้ ปิดเครื่องไม่ได้)
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\duo.ps1 -Schedule 22:30 -MaxTasks 2
   ```
7. (ไม่บังคับ) Claude review PR ที่ไม่ได้มาจาก duo บน GitHub ด้วย subscription:
   `claude setup-token` → GitHub repo → Settings → Secrets and variables → Actions → New secret
   ชื่อ `CLAUDE_CODE_OAUTH_TOKEN` → วาง token (ถ้าไม่ใส่ workflow จะถูกข้าม ไม่ error)

## คำสั่งที่ใช้บ่อย

```powershell
.\scripts\duo.ps1                         # ทำ task ถัดไป 1 งาน (รันทันที)
.\scripts\duo.ps1 -MaxTasks 3             # ทำต่อกันสูงสุด 3 งาน
.\scripts\duo.ps1 -Task T-104             # เจาะจง task (ทำซ้ำได้แม้เคย needs-bro)
.\scripts\duo.ps1 -Task T-104 -Builder claude   # สลับให้ Claude เป็นคนเขียนแทน
.\scripts\duo.ps1 -Status                 # สถานะทุก card + ผลรอบล่าสุด + เวลา schedule
.\scripts\duo.ps1 -NoMerge                # ทำจนเปิด PR แต่ไม่ merge (คุณกดเอง)
.\scripts\duo.ps1 -Unschedule             # ยกเลิกการรันทุกคืน
```

(ถ้ารันจาก PowerShell ที่ยังไม่ตั้ง ExecutionPolicy ให้ขึ้นต้นด้วย `powershell -ExecutionPolicy Bypass -File`)

## ผลลัพธ์อยู่ที่ไหน

- แจ้งเตือน Windows: "merged 1, needs you 0 …"
- `.duo\last-run.md` — สรุปรอบล่าสุด; `.duo\logs\<เวลา>\` — prompt/คำตอบ/ผล test ของทุกขั้น
- GitHub: PR label `duo` (ผ่านแล้ว merge) หรือ `needs-bro` (รอคุณ) — ในตัว PR มีสรุปของ builder + review ครบ

### เมื่อเจอ `needs-bro`

1. เปิด PR อ่าน *Review* กับ *Note* (เช่น ต้องทดสอบกับ hardware จริง หรือ 2 ตัวเห็นไม่ตรงกัน)
2. เลือกอย่างใดอย่างหนึ่ง:
   - โอเคแล้ว → กด Merge เอง แล้วแก้ card เป็น `**Status:** done`
   - ให้ลองใหม่ → แก้ card ให้ชัดขึ้น (push ขึ้น main) แล้ว `.\scripts\duo.ps1 -Task T-xxx` (จะได้ branch ใหม่ `duo/T-xxx-2`)
   - ไม่ทำแล้ว → ปิด PR แล้วแก้ card เป็น `**Status:** blocked`

## เพิ่มงานใหม่ให้ duo

copy `docs/tasks/_TEMPLATE.md` เป็น `docs/tasks/T-111-<ชื่อ>.md` → เติม Goal / Contract / Acceptance criteria
→ commit + push ขึ้น main คืนนั้น duo จะหยิบไปทำตาม Priority (เลขน้อยทำก่อน)
`**Suggested owner:** Claude` หรือ `GPT` กำหนดว่าใครเขียน อีกตัวจะเป็นคนตรวจ
ยิ่ง acceptance criteria ชัด (มี test ที่ต้องผ่าน / golden-day case) ยิ่งไม่ต้องกลับมาดู

## สั่งงานเองแบบ interactive (เวลาอยากนั่งดู) — copy prompt ไปวางได้เลย

ทั้งคู่อ่านกติกาจาก `AGENTS.md` เอง (Claude ผ่าน `CLAUDE.md`). หลัง `duo.ps1 -Setup` ทั้งสองตัวจะไม่ถาม permission ใน folder นี้
(Claude: `.claude/settings.json` อนุญาตทุกอย่างยกเว้น force-push และข้อมูลใน `~/.opstrail`;
Codex: `.codex/config.toml` = `approval_policy = "never"` + `workspace-write` — Codex จะถาม "trust this folder?" ครั้งแรกครั้งเดียว)

**Claude Code** (VS Code → Claude panel หรือพิมพ์ `claude` ใน terminal):
```
ทำ task card docs/tasks/T-102-meeting-presence.md ตาม AGENTS.md ให้ครบ acceptance criteria
รัน pytest กับ opstrail eval ให้ผ่าน อัปเดต SPEC/HANDOFF แล้ว commit ด้วย prefix [claude] บน branch t-102
```
**Codex** (VS Code → Codex panel เลือก Agent (full access) หรือพิมพ์ `codex` ใน terminal):
```
Review the diff of branch t-102 against main using AGENTS.md and the task card.
List blockers/majors with file:line and a fix. End with VERDICT: APPROVE or VERDICT: CHANGES.
```
แล้วส่ง review กลับให้อีกตัว: `แก้ตาม review นี้ (blocker/major ทั้งหมด) แล้วรัน test ใหม่: <วาง review>`

## สิ่งที่ AI ทำได้ / ทำไม่ได้ ระหว่างรัน duo

| ทำได้ | ทำไม่ได้ |
|---|---|
| แก้ไฟล์ใน worktree ของ task นั้น, รัน python/pytest/eval, อ่าน docs บนเว็บ | commit / push / merge / `gh` (duo ทำเองหลังผ่าน gate + review) |
| reviewer อ่านไฟล์และรัน test | reviewer แก้ไฟล์ (Claude: ห้าม Edit/Write, Codex: sandbox read-only) |
| | อ่าน `~/.opstrail` (ข้อมูลงานจริงของคุณ), `~/.ssh`, credential files |
| | ใช้ API key (ถูกลบออกจาก environment) |
| | เขียนลง worklog ของคุณ (`OPSTRAIL_NO_CAPTURE=1` ปิด hook ระหว่างรัน) |

Codex บน Windows ใช้ sandbox ถ้าเครื่องไม่รองรับ duo จะสลับไปรันแบบ full access *ภายใน worktree* ให้เอง
(บังคับตั้งแต่ต้นได้ด้วย `-CodexFullAccess`)

## กติกา (สรุปจาก AGENTS.md)

| เรื่อง | กติกา |
|---|---|
| งานหนึ่งชิ้น | 1 task card = 1 branch = 1 PR; commit prefix `[claude]` / `[gpt]` / `[duo]` |
| ก่อน merge | pytest ผ่าน, `opstrail eval` ผ่านทุกข้อ, reviewer = อีก model ตอบ APPROVE, CI เขียว |
| ตัดสินเมื่อเห็นต่าง | ดูผล eval เป็นหลัก; ถ้ายังไม่ลงตัวหลัง 3 รอบ → `needs-bro` + บันทึกใน Decision log |
| ข้อมูลจริง | ห้าม commit ข้อมูลลูกค้า — fixture จาก `opstrail eval export` ต้องอ่านทวนก่อนทุกครั้ง |

## แบ่งงานที่แนะนำ

- **Claude**: capture/segmentation, security, Windows internals, M365/Graph, eval harness, team-mode design (T-102, T-106, T-109, T-110)
- **GPT**: browser extension, web UI, voice, Teams digest, tray, reviewer pass (T-101, T-103, T-104, T-105, T-107, T-108)
- **Bro**: ใช้งานจริง, เพิ่ม golden days จากงานจริง, ใส่ format เอกสารของทีมใน `templates/`, ดู PR ที่ `needs-bro`

## Tuning รายสัปดาห์ (15 นาที)

1. ใช้งานตามปกติ แก้ draft ที่ AI เขียนให้ถูกใจแล้วกดบันทึก (ระบบเก็บสิ่งที่แก้ไว้อัตโนมัติ)
2. หน้าเว็บ → ตั้งค่า → *สไตล์การเขียน* → เรียนรู้จากการแก้ไข (ต่อ template)
3. วันที่ระบบแยกงานผิด → `opstrail eval export --date …` → เพิ่มเป็นเคสใน `evals/cases.toml`
   → เขียน task card สั้นๆ "ทำให้เคส X ผ่าน" → duo แก้ให้ในคืนนั้น
4. Rules ที่จำแนกกิจกรรมเฉพาะของคุณ (portal ลูกค้า, ชื่อเครื่อง) → `~/.opstrail/activity_rules.toml`
