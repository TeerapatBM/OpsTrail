"""The golden-day cases are a regression gate: deterministic checks must always pass."""

from __future__ import annotations

from test_web import FakeLLM, fake_llm  # noqa: F401

from opstrail import evals, llm


def test_golden_days_deterministic():
    results = evals.run()
    assert results, "no eval cases found"
    failed = [(r.name, n, d) for r in results for n, ok, d in r.checks if not ok]
    assert not failed, failed


def test_golden_day_with_llm(cfg, fake_llm):
    llm.save_settings(cfg, {"provider": "anthropic", "base_url": fake_llm}, api_key="sk-test")
    FakeLLM.reply = (
        "# SOP: ติดตั้ง Splunk UF\n\n## 1. วัตถุประสงค์ (Purpose)\nส่ง log ไป 10.10.20.5:9997\n"
        "## 2. ขอบเขต (Scope)\n- splunk-uf01\n## 3. ผู้รับผิดชอบ\n- Engineer\n## 4. สิ่งที่ต้องเตรียม\n- sudo\n"
        "## 5. ขั้นตอนการปฏิบัติงาน (Procedure)\n```bash\nsudo dpkg -i splunkforwarder-9.3.0-linux-amd64.deb\n"
        "sudo /opt/splunkforwarder/bin/splunk add monitor /var/log/syslog -index linux\n```\n"
        "## 6. การตรวจสอบผล\n- ok\n## 7. การย้อนกลับ (Rollback)\n[TODO]\n## 8. ปัญหาที่พบบ่อย\n- ลืม -auth\n"
        "## 9. เอกสารอ้างอิง\n- docs\n## 10. ประวัติการแก้ไข\n- 1.0\n"
    )
    case = next(c for c in evals.load_cases() if c["name"] == "soc-day")
    res = evals.run_case(case, use_llm=True, llm_from=cfg)
    failed = [(n, d) for n, ok, d in res.checks if not ok]
    assert not failed, failed
    assert res.doc.startswith("# SOP")
    # a hallucinated IP is caught by the referee
    FakeLLM.reply += "\nbackup ไปที่ 192.168.77.7\n"
    res2 = evals.run_case(case, use_llm=True, llm_from=cfg)
    assert any(n == "fact-check" and not ok and "192.168.77.7" in d for n, ok, d in res2.checks)
