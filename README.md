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

## System tray (Windows)

เมื่อติดตั้ง extra `agent` จะมี `pystray` และ `Pillow` สำหรับไอคอน OpsTrail ข้างนาฬิกา
สีเขียว = กำลังบันทึก สีเทา = หยุดบันทึกชั่วคราว (อัปเดตเมื่อ pause ผ่าน hotkey/CLI/หน้าเว็บด้วย)
คลิกขวาเพื่อ **เปิดหน้าเว็บ**, **หยุดบันทึก/บันทึกต่อ**, เพิ่ม **โน้ต**, **ถ่ายรูป**,
เปิด **Daily worklog วันนี้** หรือ **ออก** เพื่อหยุด agent ไอคอนอาจอยู่ในเมนูไอคอนที่ซ่อนอยู่ของ Windows

Daily worklog จะเปิดฉบับเดิมโดยเก็บข้อความที่แก้ไว้ หรือสร้างฉบับแรกถ้ายังไม่มี
ถ้าปิดหน้าเว็บใน config จะใช้ popup review แทน หากยังไม่ได้ติดตั้ง extra หรือไม่มี desktop ที่รองรับ
agent ยังบันทึกตามปกติและใช้ hotkey/CLI ได้ ไอคอนแบบ background นี้ไม่เปิดบน macOS
ติดตั้งหรืออัปเดต extra ด้วย `python -m pip install -e ".[agent]"` แล้วรัน `opstrail restart`

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
| `Ctrl+Alt+V` | พูดสรุปงานประมาณ 20 วินาที (สูงสุด 60 วินาที) แล้วถอดเสียงเป็นโน้ต |
| `Ctrl+Alt+S` | ถ่ายรูปหน้าต่างที่ใช้อยู่ + ใส่คำอธิบาย (ไว้ใช้ใน SOP) |
| `Ctrl+Alt+T` | เริ่ม/จบ "งาน" แบบกำหนดเอง เช่น "ติดตั้ง Splunk UF ที่ลูกค้า X" |
| `Ctrl+Alt+P` | หยุด/เริ่มบันทึกชั่วคราว (เช่น ตอนทำเรื่องส่วนตัว) |

ใน PowerShell มีคำสั่งลัด: `ot-note "..."`, `ot-task start "..."`, `ot-task stop`, `ot-shot --delay 3`

**เก็บผลลัพธ์ของคำสั่ง (opt-in)** — ให้ SOP มีหัวข้อ "ผลลัพธ์ที่คาดหวัง" จากผลจริง เช่น `Status: Running`,
`TcpTestSucceeded : True`: ตั้ง `[capture] shell_output = true` ใน `config.toml` แล้วเปิด PowerShell หน้าต่างใหม่
hook จะเปิด `Start-Transcript` ของแต่ละหน้าต่างไว้ใน `~/.opstrail/transcripts/` และเก็บเฉพาะ **15 บรรทัดแรก**
ของผลลัพธ์แต่ละคำสั่ง (`shell_output_lines`) ซึ่งผ่านการ redact secret ก่อนบันทึกเหมือนคำสั่ง
- ไฟล์ transcript มีผลลัพธ์ดิบ (ยังไม่ redact) — ถูกลบเมื่อพิมพ์ `exit`; ถ้าปิดหน้าต่างด้วย X จะถูกลบตอนเปิด PowerShell ครั้งถัดไป (ไฟล์เก่ากว่า 12 ชม.)
- รองรับเฉพาะ PowerShell (bash/zsh ยังไม่เก็บผลลัพธ์) · ถ้าสั่ง `Stop-Transcript` เองจะหยุดของ OpsTrail ด้วย (คำสั่งยังถูกบันทึกตามปกติ)
- ตอน pause hook จะหยุดและลบไฟล์ transcript ที่ prompt ถัดไป (หน้าต่างที่เปิดตอน pause อยู่จะไม่เริ่ม transcript) แล้วเริ่มไฟล์ใหม่หลัง resume — คำสั่งแรกหลัง resume จะยังไม่มีผลลัพธ์
- รองรับ header ของ transcript ทั้งแบบมีและไม่มี UTF-8 BOM ใน Windows PowerShell 5.1 รวมถึงไฟล์ที่เริ่มใหม่หลัง resume

ตอน 18:00 (ตั้งได้) จะสร้าง Daily worklog ให้ และเปิดหน้าเว็บให้ทบทวนชื่องาน + เติมโน้ต

**ส่ง digest ไป Teams (เลือกเปิดเอง)** — ใน Teams channel สร้าง Power Automate **Workflows**
แบบรับ Webhook แล้วโพสต์ Adaptive Card โดยเลือกการรับ request แบบที่ใช้ URL ได้โดยไม่ต้อง OAuth
([คู่มือ Microsoft](https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/connectors-using))
คัดลอก HTTPS URL ไปที่หน้า **ตั้งค่า → สรุปงานประจำวันไป Teams → บันทึก Webhook**
URL เก็บใน `~/.opstrail/recap.json` ด้วย Windows DPAPI เหมือน API key; ระบบอื่นใช้ base64 ในไฟล์สิทธิ์ 600
อย่าใส่ URL จริงใน `config.toml` — `[recap] teams_webhook_url = ""` เป็นเพียงค่าเริ่มต้นว่างและไม่อ่าน URL จาก TOML
เว้นช่องว่างเมื่อบันทึกเพื่อใช้ค่าเดิม หรือกด **ลบ Webhook / ปิดการส่ง** เพื่อปิด

ตอน agent สร้าง recap อัตโนมัติจะส่งการ์ดสั้นๆ มีชื่องาน/เวลา ประชุม และงานที่ควรทำ SOP/Delivery doc
รวมถึง recap ย้อนหลังของเมื่อวานเมื่อเปิดเครื่องใหม่; กดสร้าง recap เองในเว็บ/CLI/MCP จะไม่ส่งซ้ำ
ชื่ออัตโนมัติและหัวข้อประชุมใช้ `งาน #id` / `ประชุม #id` แทน เพราะอาจมาจาก command/window title
เปลี่ยนชื่องานเองหรือให้ AI ตั้งชื่อเพื่อให้ digest อ่านง่าย (ชื่อที่ซ้ำกับ command/window title จะถูกแทนด้วยเลขงานเช่นกัน)
ไม่ส่ง command, window title, output, notes, screenshots หรือเนื้อหาเอกสาร; สูงสุด 15 รายการต่อหมวด
ส่งใน background มี timeout 10 วินาทีต่อครั้งและ retry อีกหนึ่งครั้ง ไม่ขวาง agent; ล้มเหลวบันทึกเฉพาะข้อความทั่วไป
ใน `logs/agent.log` โดยไม่แสดง URL หากปิด agent ระหว่างส่งอาจไม่ได้รับการ์ด และ timeout อาจทำให้การ์ดซ้ำได้

**ประชุม** (Teams / Zoom / Google Meet) ถูกแยกเป็นงานของตัวเองพร้อมเวลาเป๊ะ — พอประชุมจบ (≥10 นาที) จะมีหน้าต่าง
ให้สรุปสั้นๆ: ประเด็น / การตัดสินใจ / action items แล้วใช้ template **บันทึกการประชุม** ทำเอกสารได้ทันที
(ระบบไม่อัดเสียงหรือดึง transcript — จนกว่าจะเปิดใช้ M365 connector)
ระหว่างประชุมถ้า share screen แล้วไปทำงานใน terminal / browser ก็ยังนับเป็นเวลาประชุม ตราบใดที่หน้าต่างประชุมยังเปิดอยู่
(Windows) และงานที่ทำระหว่างนั้นจะอยู่ในงานประชุมเดียวกัน — ปิดได้ด้วย `[meetings] detect_background = false` ใน `config.toml`

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
- **ให้ AI ตรวจ** — ตั้งค่า → profile **ผู้ตรวจ (reviewer)** เลือก provider/model และ API key แยกจาก writer (เช่น Claude เขียน แล้ว GPT ตรวจ) จากนั้นกดปุ่มใน editor ระบบบันทึกการแก้ไขที่ค้างไว้ก่อน ส่ง draft ล่าสุดกับ source pack ที่ redact แล้ว และแสดงปัญหา/คำแนะนำพร้อมผลตรวจข้อเท็จจริง ผลตรวจผูกกับเวอร์ชันเดิมและไม่แก้ draft อัตโนมัติ; เลือกเวอร์ชันล่าสุดก่อนตรวจ ผลจาก AI ยังต้องตรวจหลักฐานเอง
- `opstrail eval --llm` แสดงคอลัมน์ reviewer score เมื่อเปิดใช้ reviewer (100 หัก error 20 / warning 5; info ไม่หัก) เป็นคำแนะนำแยกจากคะแนน gate; ถ้าตรวจไม่สำเร็จแสดง `unavailable` โดยไม่กระทบ deterministic checks
- **เทียบเวอร์ชัน** (หน้าเอกสาร เมื่อบันทึกแล้ว ≥2 เวอร์ชัน) — เลือกเวอร์ชันใดก็ได้สองเวอร์ชันเพื่อดูข้อความเดิม/ใหม่คู่กัน พร้อมขีดฆ่าส่วนที่ลบและขีดเส้นใต้ส่วนที่เพิ่ม รองรับการไฮไลต์คำภาษาไทย ไม่รวมการแก้ไขที่ยังไม่บันทึก
- **AI streaming** — เห็นข้อความใน editor ขณะ AI กำลังเขียน (Claude / OpenAI-compatible / Azure OpenAI) เมื่อเสร็จจะบันทึกเป็นเวอร์ชันใหม่และตรวจข้อเท็จจริงให้ ระหว่างเขียนจะล็อกการแก้ไข/บันทึก/สลับเวอร์ชัน ถ้า provider ส่งข้อผิดพลาดหรือ stream ขาด จะคืนข้อความเดิมโดยไม่บันทึกคำตอบที่ยังไม่ครบ หากการเชื่อมต่อขาดหลัง server บันทึกแล้ว ให้ตรวจประวัติเวอร์ชันก่อนลองใหม่
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
shell_output = true          # เก็บผลลัพธ์คำสั่ง PowerShell (15 บรรทัดแรก) ไว้ทำ "ผลลัพธ์ที่คาดหวัง"

[recap]
time = "17:30"
```

## ความเป็นส่วนตัว / ความปลอดภัย

- Voice note เปิดไมโครโฟนเฉพาะเมื่อกด `Ctrl+Alt+V` หรือปุ่ม **พูดสรุป (Voice)** ใน popup สรุปประชุม
  มีหน้าต่างจับเวลาและปุ่มหยุด; Esc/ปิดหน้าต่าง = ยกเลิก เสียง WAV ชั่วคราวถูกลบเมื่อจบหรือเกิดข้อผิดพลาด
  ค่าเริ่มต้น `[voice] backend = "local"` ใช้ faster-whisper `small` ในเครื่อง (ดาวน์โหลด model ครั้งแรกไป
  `$OPSTRAIL_HOME/models` หรือ `~/.opstrail/models`; ต้องมี internet สำหรับดาวน์โหลด แต่ไม่ส่งเสียงออก)
  ติดตั้งเพิ่มด้วย `python -m pip install -e ".[voice]"` แล้ว `opstrail restart`; หากยังไม่ติดตั้งจะมี toast แนะนำ
  รองรับไทย + English; โน้ตผ่าน redaction และผูกกับงานปัจจุบัน/ที่เพิ่งจบ หรือประชุมที่กดปุ่ม
  ถ้าเลือก `[voice] backend = "openai"` หรือ `"azure"` จะส่ง **เสียงดิบที่ยัง redact ไม่ได้** ไป cloud เท่านั้น
  ใช้ key ใน Settings เมื่อ provider ตรงกัน หรือ `OPENAI_API_KEY` / `AZURE_OPENAI_API_KEY`;
  OpenAI ใช้ `whisper-1` ส่วน Azure ต้องตั้ง HTTPS endpoint ใน Settings และ `[voice] azure_deployment`
  เป็นชื่อ **Whisper deployment** (แยกจาก chat deployment) อาจมีค่าบริการตาม provider
  การยกเลิกหลังเริ่ม upload หยุดการส่งที่เกิดขึ้นแล้วไม่ได้ แต่จะไม่เก็บโน้ต;
  ขณะ pause จะไม่เริ่มอัด และจะทิ้งผลถ้า pause ระหว่างทำงาน ไม่อัดเสียงประชุมอัตโนมัติ
  ถ้าเครื่องหรือ process ปิดผิดปกติ อาจมี WAV ค้างในโฟลเดอร์ TEMP ให้ลบ `opstrail-voice-*.wav`
- หน้าเว็บ bind เฉพาะ `127.0.0.1` + ตรวจ Host header (กัน DNS rebinding) + ต้องมี header เฉพาะสำหรับคำสั่งที่แก้ข้อมูล (กัน CSRF จากเว็บอื่น) + CSP
- API key ของ AI เก็บแบบเข้ารหัส Windows DPAPI (ผูกกับ user ของเครื่องนี้) — ข้อมูลที่ส่งให้ AI คือ source pack ที่ redact แล้ว
  ถ้าต้องการให้ข้อมูลลูกค้าอยู่ใน tenant ของบริษัท ใช้ **Azure OpenAI** หรือ model ในเครื่อง (Ollama)
- **ไม่ใช่ keylogger**: บน Windows ใช้ `RegisterHotKey` — Windows แจ้งเฉพาะปุ่มลัดของ OpsTrail ไม่มีการดักทุกปุ่มที่พิมพ์ (ไม่โดน EDR มองว่าเป็น keyboard hook)
- ข้อมูลหลักอยู่ใน `~/.opstrail` บนเครื่องตัวเอง; ส่งออกเมื่อ AI client อ่านผ่าน MCP,
  ใช้ AI write / AI ตรวจ (รวม `eval --llm`), เปิด Teams digest หรือเลือก cloud backend สำหรับ Voice note
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
| เปิด `shell_output` แล้วไม่มีผลลัพธ์ใน source pack | เปิด PowerShell หน้าต่างใหม่ (hook อ่าน config ตอนเปิด), ตรวจว่ามีไฟล์ใน `~/.opstrail/transcripts/` — host ที่ไม่รองรับ `Start-Transcript` จะบันทึกแค่คำสั่ง |
| ปุ่มลัดไม่ทำงาน | ดู `~/.opstrail/logs/agent.log` — ถ้าเขียนว่า "could not be registered" แปลว่าโปรแกรมอื่นจองปุ่มนั้นไว้ ให้เปลี่ยนใน `[hotkeys]` ของ config แล้ว restart agent |
| Claude Desktop ไม่เห็น opstrail | `opstrail install-claude` แล้ว quit Claude จาก tray แล้วเปิดใหม่ |
| VS Code ไม่เห็น tools | เปิด `.vscode/mcp.json` → กด Start, ใช้ Chat แบบ Agent mode |
| หน้าเว็บเปิดไม่ได้ | agent ไม่ได้รัน → `opstrail web` หรือดับเบิลคลิก "OpsTrail Agent" ใน Startup; port ชน → แก้ `[web] port` |
| ให้ AI เขียนแล้ว error | หน้า ตั้งค่า → ทดสอบการเชื่อมต่อ (key/model/endpoint) ถ้าอยู่หลัง proxy บริษัทตั้ง `HTTPS_PROXY` |
| Claude API: "not scoped to a workspace … anthropic-workspace-id" | key ของคุณใช้ได้หลาย workspace → ใส่ **Workspace ID** (`wrkspc_…` จาก Claude Console → Settings → Workspaces) ในหน้าตั้งค่า หรือสร้าง key ใหม่ที่ผูกกับ workspace เดียว |
| อัปเดตไฟล์แล้วหน้าเว็บ/agent ยังเป็นของเก่า | `opstrail restart` แล้วกด Ctrl+F5 ในเบราว์เซอร์ |
| รูปภาษาไทยใน .docx ผิดฟอนต์ | ตั้ง `[export] docx_font` หรือใส่ `reference.docx` ของบริษัท |

สถาปัตยกรรมและ contract ทั้งหมด: [`SPEC.md`](SPEC.md)

## ติดตั้ง extension

OpsTrail Browser Capture สำหรับ Edge/Chrome ช่วยเก็บ URL จริงของหน้า admin console เช่น Azure blade,
Sentinel rule หรือ vCenter แทนการอาศัยชื่อหน้าต่างอย่างเดียว

1. เปิด OpsTrail agent หรือ `opstrail web` แล้วเข้า `http://127.0.0.1:8765/#/settings`
2. ที่ **Browser extension** กด **แสดง token** → **คัดลอก token**
3. เปิด `edge://extensions` หรือ `chrome://extensions` แล้วเปิด **Developer mode**
4. กด **Load unpacked** แล้วเลือกโฟลเดอร์ `extension` ใน repo นี้
5. เปิด **Extension options** ของ OpsTrail Browser Capture วาง token และพอร์ต OpsTrail
   (ค่าเริ่มต้น `8765`) แล้วกด **บันทึก** จากนั้นสลับแท็บเพื่อเริ่มบันทึก

ส่ง URL/title เฉพาะแท็บที่ใช้งานในหน้าต่าง browser ที่โฟกัสไปยังเครื่องนี้เท่านั้น สูงสุดหนึ่งครั้งต่อ
3 วินาที ไม่บันทึก Incognito/InPrivate หาก web server ปิดอยู่จะข้ามข้อมูลโดยไม่ส่งย้อนหลัง
ดู URL ที่บันทึกได้ใน timeline และ source pack ของเอกสาร

Pause ของ OpsTrail หยุดการเก็บข้อมูล browser ด้วย ค่าเริ่มต้นตัด query string รวมถึง query ใน fragment
แต่เก็บเส้นทาง `#blade/...` ไว้ และผ่าน redaction ก่อนบันทึก ตั้งค่า `[capture] browser_keep_query = true`
ใน `config.toml` เฉพาะเมื่อต้องใช้ query จริง เพิ่มโดเมนส่วนตัวใน `[capture] exclude_domains` ได้
(รวม subdomain อัตโนมัติ; รายการเริ่มต้นมีธนาคารหลักในไทยและ personal mail บางบริการ)
และใช้ `exclude_title_patterns` ได้ตามเดิม จากนั้น restart agent/web server

Token เก็บใน `<OPSTRAIL_HOME>/browser_token` (ปกติ `~/.opstrail/browser_token`) และใน extension storage
ของเครื่องนี้ ห้ามแชร์ token หากต้องการเปลี่ยนให้ลบไฟล์นี้แล้วแสดง token ใหม่ใน Settings และจับคู่ใหม่
หากต้องการปิด extension ให้กด **ลบ token / ปิดการบันทึก** ใน Options หรือปิด extension
