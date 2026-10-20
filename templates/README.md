# Templates

แต่ละ folder = 1 ประเภทเอกสาร (ชื่อ folder = ชื่อ template ที่ใช้ใน MCP เช่น `sop`)

```
<name>/
  template.toml     title + description (บอก AI ว่าเอกสารนี้ใช้เมื่อไร)
  skeleton.md       โครงเอกสาร (หัวข้อ/ตาราง) — AI จะเขียนตามโครงนี้
  guide.md          คำอธิบายว่าแต่ละ section ต้องมีอะไร (กติกาการเขียน)
  examples/         ใส่เอกสารจริงที่ "เขียนดี" 1–3 ไฟล์ (.md .txt .docx) — AI ใช้เป็นตัวอย่าง (few-shot)
  reference.docx    (ไม่บังคับ) Word template ของบริษัท — ใช้ style/หัวกระดาษ/ฟอนต์ ตอน export .docx
```

## เพิ่ม format ของทีม

1. ก๊อปเอกสารตัวอย่างที่ดีใส่ `examples/`
2. ถ้ามี Word template บริษัท ให้บันทึกเป็น `reference.docx` (ลบเนื้อหาออก เหลือ style/header/footer)
3. ปรับ `skeleton.md` ให้หัวข้อตรงกับ format ของทีม และอธิบายแต่ละหัวข้อใน `guide.md`
4. ไม่ต้อง restart — template ถูกโหลดใหม่ทุกครั้งที่เรียกใช้

เพิ่มประเภทใหม่ (เช่น `incident-report`, `change-request`) = สร้าง folder ใหม่ตามโครงด้านบน
