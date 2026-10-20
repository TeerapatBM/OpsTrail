# evals/ — golden days (กรรมการกลางของ Claude ↔ GPT)

ทุกครั้งที่มีใครแก้ heuristic การแยกงาน, rules, prompt หรือ template ให้รัน eval ก่อน merge
ตัวเลขต้องไม่แย่ลง — ใช้ตัดสินแทนการเถียงกันว่า "แบบไหนดีกว่า"

```powershell
opstrail eval                 # deterministic: การแยกงาน ประชุม ชื่องาน secret ถูก redact (ไม่ใช้ AI, เร็ว, รันใน CI)
opstrail eval --llm           # + ให้ AI ที่ตั้งค่าไว้เขียนเอกสารจริง แล้วตรวจ: ข้อเท็จจริงที่ต้องมี, ไม่มี secret,
                              #   fact-check (IP/version/host ที่ AI เดา), ครอบคลุมหัวข้อ skeleton ≥ 70%, จำนวน TODO
opstrail eval --case soc-day  # รันเคสเดียว
```

รายงานเก็บที่ `~/.opstrail/evals/eval-*.md` (มีเอกสารที่ AI เขียนไว้ดู)

## เพิ่มวันทำงานจริงเป็นเคส

```powershell
opstrail eval export --date 2026-10-20 --name pfsense-syslog-day
```

- ได้ไฟล์ `evals/days/pfsense-syslog-day.jsonl` (secret ถูก redact ตั้งแต่ตอนบันทึก, IP/user/host ถูกแทนแบบคงที่)
- **เปิดอ่านก่อน commit ทุกครั้ง** — window title อาจมีชื่อลูกค้า/ข้อมูลภายใน แก้หรือลบบรรทัดที่ไม่ควรอยู่ใน repo
- เพิ่ม `[[case]]` ใน `cases.toml` บอกว่าวันนั้น "ควร" แยกเป็นกี่งาน มีประชุมกี่อัน ชื่องานควรมีคำว่าอะไร และเอกสารควรมีข้อมูลอะไร

## รูปแบบเคส

```toml
[[case]]
name = "soc-day"
day = "days/soc-day-01.jsonl"
date = "2026-10-19"
projects = { "Splunk" = ["splunk"] }      # [projects] สำหรับเคสนี้ (ไม่บังคับ)
capture = { shell_output = true }          # [capture] สำหรับเคสนี้ (ไม่บังคับ) เช่น เปิดเก็บผลลัพธ์คำสั่ง

  [case.episodes]
  count_min = 4
  count_max = 5
  meetings = 1
  titles_contain = ["Splunk", "ประชุม: Weekly SOC sync"]
  meeting_time = "11:00–11:40"

  [case.pack]                                # ไม่ใช้ AI: source pack ของงานใน [case.doc] ต้องมีข้อความเหล่านี้
  must_contain = ["Running  splunkd"]

  [case.doc]                                 # ใช้เมื่อ --llm
  template = "sop"
  episodes_with_title = "Splunk"             # ใช้งานที่ชื่อมีคำนี้เป็น source
  must_mention = ["9997", "splunkforwarder"]
  must_not_contain = ["S3cretPass!"]         # secret ในไฟล์ day → ต้องไม่หลุดไปถึงเอกสาร
  max_unsupported = 0                        # จำนวนค่าที่ fact-check หาไม่เจอใน source ที่ยอมได้
```
