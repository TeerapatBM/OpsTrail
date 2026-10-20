# OpsTrail

> บันทึกงานที่ทีมทำจริงแบบเงียบๆ ระหว่างวัน → สรุปเป็น Daily worklog อัตโนมัติ → เปิดหน้าเว็บ
> แล้วกดให้ AI (Claude / GPT / Azure OpenAI) เปลี่ยนเป็น SOP, Delivery doc, Guide — หรือใช้ผ่าน MCP ก็ได้

```
ทำงานตามปกติ ──► OpsTrail จับ: คำสั่ง PowerShell/bash · หน้าต่างที่ใช้ · โน้ต · screenshot
                       │  (ปิดบัง password/token อัตโนมัติ, เก็บในเครื่องเท่านั้น)
                       ▼
              จัดกลุ่มเป็น "งาน" (episodes) ──► 18:00 สร้าง Daily worklog ให้เอง
                       │
                       ▼
   ┌─ หน้าเว็บ http://127.0.0.1:8765  (ดูงาน · แก้ชื่อ/โน้ต · ✨ ให้ AI เขียน · แก้ไข · export)
   └─ หรือ Claude Desktop / VS Code (Copilot-GPT, Claude Code) ผ่าน MCP
                       ▼
                 เอกสาร .docx / .md
```

## ติดตั้ง (Windows)

1. ต้องมี Python 3.10+ (`winget install -e --id Python.Python.3.12`)
2. เปิด PowerShell ที่ folder นี้แล้วรัน

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
   ```

   สคริปต์จะ: สร้าง `.venv` → ติดตั้ง package → สร้าง `~/.opstrail` → ใส่ hook ใน PowerShell profile →
   ตั้งให้ agent เปิดเองตอน login และเริ่มทำงานทันที → ลงทะเบียน MCP ใน Claude Desktop → สร้าง shortcut
   **OpsTrail** บน Desktop → รัน `opstrail doctor` → เปิดหน้าเว็บให้
3. ปิด/เปิด PowerShell ใหม่ (เพื่อให้ hook เริ่มบันทึกคำสั่ง)
4. ในหน้าเว็บ ไปที่ **ตั้งค่า** → เลือก AI (Claude API / OpenAI / Azure OpenAI / Ollama) ใส่ API key → กด *ทดสอบการเชื่อมต่อ*

ไม่อยากให้ทำบางขั้น: `-NoProfileHook`, `-NoStartup`, `-NoClaudeDesktop`, `-NoStart` · ถอนการติดตั้ง: `scripts\uninstall.ps1`

## ใช้งานประจำวัน

| ปุ่มลัด | ทำอะไร |
|---|---|
| `Ctrl+Alt+N` | จดโน้ตสั้นๆ — **ทำไม** ถึงทำ / ตัดสินใจอะไร / ผลเป็นยังไง (สำคัญที่สุดต่อคุณภาพเอกสาร) |
| `Ctrl+Alt+S` | ถ่ายรูปหน้าต่างที่ใช้อยู่ + ใส่คำอธิบาย (ไว้ใช้ใน SOP) |
| `Ctrl+Alt+T` | เริ่ม/จบ "งาน" แบบกำหนดเอง เช่น "ติดตั้ง Splunk UF ที่ลูกค้า X" |
| `Ctrl+Alt+P` | หยุด/เริ่มบันทึกชั่วคราว (เช่น ตอนทำเรื่องส่วนตัว) |

ใน PowerShell มีคำสั่งลัด: `ot-note "..."`, `ot-task start "..."`, `ot-task stop`, `ot-shot --delay 3`

ตอน 18:00 (ตั้งได้) จะสร้าง Daily worklog ให้ และเปิดหน้าเว็บให้ทบทวนชื่องาน + เติมโน้ต

**ประชุม** (Teams / Zoom / Google Meet) ถูกแยกเป็นงานของตัวเองพร้อมเวลาเป๊ะ — พอประชุมจบ (≥10 นาที) จะมีหน้าต่าง
ให้สรุปสั้นๆ: ประเด็น / การตัดสินใจ / action items แล้วใช้ template **บันทึกการประชุม** ทำเอกสารได้ทันที
(ระบบไม่อัดเสียงหรือดึง transcript — จนกว่าจะเปิดใช้ M365 connector)

## หน้าเว็บ (http://127.0.0.1:8765)

เปิดจาก shortcut **OpsTrail** บน Desktop หรือรัน `opstrail web` — agent เปิด server ให้อยู่แล้ว (เข้าได้เฉพาะเครื่องนี้)

| หน้า | ทำอะไรได้ |
|---|---|
| **วันนี้ / งาน** | ดูงานของแต่ละวัน (◀ ▶ เลือกวัน) แก้ชื่องาน เติมโน้ต/แท็ก ดูคำสั่งและรูป ติ๊กหลายงาน → **สร้างเอกสาร** หรือ **รวมงาน** |
| **Daily worklog** | worklog รายวันย้อนหลัง สร้าง/อัปเดตของวันนี้ |
| **เอกสาร** | รายการเอกสารทั้งหมด → editor: markdown + preview, **✨ ให้ AI เขียน/ปรับ** (ใส่คำสั่งเพิ่มได้), version history, **⬇ .docx / .md**, เพิ่มงานจากวันอื่นเข้าเอกสารเดิม |
| **ค้นหา** | ค้นคำสั่ง/หน้าต่าง/โน้ตที่เคยทำ และเนื้อหาเอกสาร (ภาษาไทยได้) |
| **ตั้งค่า** | ชื่อผู้จัดทำ, เลือก AI provider + API key (เข้ารหัส Windows DPAPI), **สไตล์การเขียนที่ AI เรียนรู้จากการแก้ของคุณ**, สถานะการบันทึก |

เครื่องมือช่วยให้แม่นขึ้น:

- **✨ ตั้งชื่องานด้วย AI** (หน้า วันนี้/งาน) — เปลี่ยนชื่ออัตโนมัติเป็นภาษาคนในครั้งเดียว
- **ตรวจข้อเท็จจริง** (หน้าเอกสาร, ทำอัตโนมัติหลัง AI เขียน) — เตือนถ้ามี IP / version / hostname / port ที่ไม่มีในข้อมูลที่บันทึก (AI อาจเดา)
- **เรียนจากการแก้ไข** — ทุกครั้งที่คุณแก้ draft ของ AI แล้วบันทึก ระบบจำส่วนที่แก้ และใช้ใน prompt ครั้งถัดไป
- **กฎจำแนกกิจกรรม** — เพิ่ม portal ลูกค้า/ชื่อเครื่องของคุณใน `~/.opstrail/activity_rules.toml` (ดูตัวอย่างใน `src/opstrail/data/activity_rules.toml`)

ไม่อยากใช้ API key? กด **Copy prompt** → วางใน ChatGPT/Claude บนเว็บ → ก๊อปผลลัพธ์ → **Paste ผลลัพธ์** ได้เหมือนกัน

## ใช้ผ่าน Claude Desktop / VS Code (MCP)

ใน **Claude Desktop** หรือ **VS Code Chat (Copilot/GPT — Agent mode)** พิมพ์ได้เลย เช่น

- "ใช้ opstrail สรุปงานวันนี้เป็น daily worklog"
- "ดูงานเมื่อวาน แล้วทำ SOP การติดตั้ง Splunk Universal Forwarder จาก episode ที่เกี่ยวข้อง"
- "เอางาน Sentinel ตั้งแต่ 2026-10-14 ถึงวันนี้ ทำเป็น Delivery doc ให้ลูกค้า แล้ว export เป็น docx"
- "ทำเอกสาร session #12 ต่อ วันนี้ทำเพิ่มเรื่อง analytic rules"

หรือใช้ prompt สำเร็จรูปของ server: `daily_worklog`, `write_document`, `continue_document`

แต่ละเอกสาร = 1 **doc session** มี version history ทำต่อข้ามวันได้ ดึงงานจากหลายวัน/หลายงานได้
ไฟล์ export อยู่ที่ `~/Documents/OpsTrail/<template>/`

## VS Code + Claude + GPT

เปิด `OpsTrail.code-workspace` ใน VS Code (หลังรัน `install.ps1` แล้ว — สคริปต์จะก๊อป `setup/vscode` → `.vscode`
และ `setup/github` → `.github` ให้):

- `.vscode/mcp.json` ลงทะเบียน OpsTrail MCP ให้ Copilot Chat/GPT ใช้ได้ทันที (กด Start ในไฟล์ถ้ายังไม่รัน)
- `AGENTS.md` + `.github/copilot-instructions.md` + `CLAUDE.md` = กติกาเดียวกันสำหรับทุก AI ที่ช่วยพัฒนา (Codex อ่าน `AGENTS.md`, Copilot อ่าน copilot-instructions, Claude Code อ่าน `CLAUDE.md`)
- `docs/HANDOFF.md` = กระดานงานร่วมระหว่าง Claude ↔ GPT (backlog, claim, review, decision log)
- Tasks: `Terminal → Run Task → OpsTrail: …` (install, tests, doctor, recap, agent)

## พัฒนาร่วมกัน Claude ↔ GPT (อัตโนมัติ ใช้แค่ subscription)

Repo: https://github.com/TeerapatBM/OpsTrail — `scripts\duo.ps1` สั่ง **Claude Code** (Claude Pro/Max) กับ **Codex**
(ChatGPT plan) ให้ผลัดกันเขียนและตรวจงานจาก task card ใน `docs/tasks/` เอง: builder เขียน → script รัน pytest + eval
→ อีก model review → แก้จนผ่าน → PR + CI → merge → อัปเดตเครื่องคุณและ restart agent ให้ ไม่ต้องกด approve และไม่ใช้ API key

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\duo.ps1 -Setup                       # ครั้งแรก
powershell -ExecutionPolicy Bypass -File .\scripts\duo.ps1 -Schedule 22:30 -MaxTasks 2  # ทุกคืน
powershell -ExecutionPolicy Bypass -File .\scripts\duo.ps1 -Status                      # ดูสถานะ
```

ขั้นตอนติดตั้ง Claude Code / Codex, การดู PR ที่ติด `needs-bro`, prompt สำหรับสั่งเองแบบ interactive และการเพิ่มงานใหม่:
[`docs/COLLABORATION.md`](docs/COLLABORATION.md) · กรรมการตัดสินคือ `opstrail eval` (golden days ใน `evals/`)

## ปรับ format เอกสารของทีม

ดู `templates/README.md` — ใส่เอกสารตัวอย่างดีๆ ใน `templates/<type>/examples/`, Word template บริษัทเป็น
`reference.docx`, แก้หัวข้อใน `skeleton.md` / กติกาใน `guide.md` เพิ่มประเภทใหม่ = สร้าง folder ใหม่

## ตั้งค่า

แก้ `~/.opstrail/config.toml` (มีคำอธิบายภาษาไทยทุกบรรทัด) เช่น

```toml
[projects]            # ใช้จัดกลุ่มงานอัตโนมัติ
"Splunk" = ["splunk", "splunkd"]
"Sentinel" = ["sentinel", "kql", "log analytics"]

[capture]
exclude_apps = ["line.exe", "keepass.exe"]
auto_screenshot_title_patterns = ["(?i)vSphere Client", "(?i)Microsoft Azure"]

[recap]
time = "17:30"
```

## ความเป็นส่วนตัว / ความปลอดภัย

- หน้าเว็บ bind เฉพาะ `127.0.0.1` + ตรวจ Host header (กัน DNS rebinding) + ต้องมี header เฉพาะสำหรับคำสั่งที่แก้ข้อมูล (กัน CSRF จากเว็บอื่น) + CSP
- API key ของ AI เก็บแบบเข้ารหัส Windows DPAPI (ผูกกับ user ของเครื่องนี้) — ข้อมูลที่ส่งให้ AI คือ source pack ที่ redact แล้ว
  ถ้าต้องการให้ข้อมูลลูกค้าอยู่ใน tenant ของบริษัท ใช้ **Azure OpenAI** หรือ model ในเครื่อง (Ollama)
- **ไม่ใช่ keylogger**: บน Windows ใช้ `RegisterHotKey` — Windows แจ้งเฉพาะปุ่มลัดของ OpsTrail ไม่มีการดักทุกปุ่มที่พิมพ์ (ไม่โดน EDR มองว่าเป็น keyboard hook)
- ข้อมูลทั้งหมดอยู่ใน `~/.opstrail` บนเครื่องตัวเอง ไม่มีการส่งออก (ยกเว้นตอนที่ AI client อ่านผ่าน MCP)
- password, token, key, connection string, JWT, `-Password`, `ConvertTo-SecureString`, URL credentials ฯลฯ
  ถูกแทนด้วย `[REDACTED]` ก่อนบันทึก เพิ่ม pattern เองได้ที่ `[redaction] extra_patterns`
- แอป/หน้าต่างที่ไม่บันทึก: chat, password manager, banking, InPrivate/Incognito (แก้ได้)
- ลบข้อมูลดิบ: `opstrail purge --date 2026-10-20` หรือ `--before 2026-09-01` (เอกสารไม่ถูกลบ)
- ถ้าใช้กับทีม ให้แจ้งและขอความยินยอมตาม PDPA ว่าเก็บอะไร และให้ทุกคนดู/ลบข้อมูลตัวเองได้

## คำสั่ง CLI

```text
opstrail web                         เปิดหน้าเว็บ (ถ้า agent ไม่ได้รันอยู่ จะเปิด server ให้)
opstrail restart | stop              รีสตาร์ท/หยุด agent (หลังอัปเดตไฟล์ OpsTrail ให้รัน restart)
opstrail eval [--llm] | eval export --date D --name N    วัดคุณภาพ (golden days) / เก็บวันจริงเป็นเคสทดสอบ
opstrail status | doctor | timeline [--date] | episodes [--date --to --rebuild]
opstrail note "..." | task start "..." | task stop | shot [--delay 3] | pause | resume
opstrail recap [--date] [--print] [--export docx]
opstrail docs list | show <id> | new <template> "<title>" --episodes 3,4 | export <id> --format docx | search <q>
opstrail mcp [--http --port 8766]   (HTTP: ตั้ง OPSTRAIL_MCP_TOKEN ก่อนเปิดให้เครื่องอื่นใช้)
opstrail purge --date|--before | install-claude [--remove]
```

## แก้ปัญหา

| อาการ | ทางแก้ |
|---|---|
| ไม่มีคำสั่ง PowerShell ใน timeline | เปิดหน้าต่างใหม่, ตรวจว่า profile มีบรรทัด `OpsTrail.ps1` และอยู่ **ท้ายสุด** (หลัง oh-my-posh) |
| ปุ่มลัดไม่ทำงาน | ดู `~/.opstrail/logs/agent.log` — ถ้าเขียนว่า "could not be registered" แปลว่าโปรแกรมอื่นจองปุ่มนั้นไว้ ให้เปลี่ยนใน `[hotkeys]` ของ config แล้ว restart agent |
| Claude Desktop ไม่เห็น opstrail | `opstrail install-claude` แล้ว quit Claude จาก tray แล้วเปิดใหม่ |
| VS Code ไม่เห็น tools | เปิด `.vscode/mcp.json` → กด Start, ใช้ Chat แบบ Agent mode |
| หน้าเว็บเปิดไม่ได้ | agent ไม่ได้รัน → `opstrail web` หรือดับเบิลคลิก "OpsTrail Agent" ใน Startup; port ชน → แก้ `[web] port` |
| ให้ AI เขียนแล้ว error | หน้า ตั้งค่า → ทดสอบการเชื่อมต่อ (key/model/endpoint) ถ้าอยู่หลัง proxy บริษัทตั้ง `HTTPS_PROXY` |
| Claude API: "not scoped to a workspace … anthropic-workspace-id" | key ของคุณใช้ได้หลาย workspace → ใส่ **Workspace ID** (`wrkspc_…` จาก Claude Console → Settings → Workspaces) ในหน้าตั้งค่า หรือสร้าง key ใหม่ที่ผูกกับ workspace เดียว |
| อัปเดตไฟล์แล้วหน้าเว็บ/agent ยังเป็นของเก่า | `opstrail restart` แล้วกด Ctrl+F5 ในเบราว์เซอร์ |
| รูปภาษาไทยใน .docx ผิดฟอนต์ | ตั้ง `[export] docx_font` หรือใส่ `reference.docx` ของบริษัท |

สถาปัตยกรรมและ contract ทั้งหมด: [`SPEC.md`](SPEC.md)
