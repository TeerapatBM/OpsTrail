"""Learn-from-edits, style lessons, fact-check and AI episode titles."""

from __future__ import annotations

import json

from conftest import DAY
from starlette.testclient import TestClient
from test_web import H, FakeLLM, fake_llm  # noqa: F401  (fixture re-export)

from opstrail import llm, quality
from opstrail.web.app import create_app


def _setup_llm(cfg, url):
    llm.save_settings(cfg, {"provider": "anthropic", "base_url": url, "model": "claude-x"}, api_key="sk-test")


def test_user_edit_after_ai_draft_is_learned(cfg, svc, sample_day, fake_llm):
    _setup_llm(cfg, fake_llm)
    svc.refresh()
    ep = svc.list_episodes(DAY)[0]
    sid = svc.start_doc_session("sop", "UF", [ep["id"]])["session_id"]
    FakeLLM.reply = "# SOP: UF\n\n## 1. Purpose\n\nติดตั้งแบบยาวมากเกินไป และมีรายละเอียดเยอะ\n"
    svc.generate_draft(sid)
    svc.save_draft(sid, "# SOP: UF\n\n## 1. วัตถุประสงค์\n\nติดตั้ง UF\n", "แก้เอง", author="web")
    fb = svc.store.feedback_for("sop")
    assert len(fb) == 1 and "+## 1. วัตถุประสงค์" in fb[0]["diff"] and "-## 1. Purpose" in fb[0]["diff"]
    # saving again as the user (no AI in between) is not a correction of the AI
    svc.save_draft(sid, "# SOP: UF\n\nอีกรอบ\n", author="web")
    assert len(svc.store.feedback_for("sop")) == 1
    # the next prompt carries the correction
    _, user = svc.llm_prompt(sid)
    assert "Recent corrections by the user" in user and "+## 1. วัตถุประสงค์" in user

    FakeLLM.reply = "- ใช้หัวข้อภาษาไทยก่อน แล้ววงเล็บภาษาอังกฤษ\n- เขียนสั้น กระชับ"
    st = svc.learn_style("sop")
    assert st["style"].startswith("- ใช้หัวข้อภาษาไทย") and st["edits"] == 1
    assert quality.read_style(cfg, "sop").startswith("- ใช้หัวข้อภาษาไทย")
    _, user = svc.llm_prompt(sid)
    assert "Style lessons learned" in user and "เขียนสั้น กระชับ" in user
    assert "Style lessons learned" in svc.source_pack(sid)  # MCP clients get it too


def test_fact_check_flags_invented_values(svc, sample_day):
    svc.refresh()
    ep = svc.list_episodes(DAY)[0]
    sid = svc.start_doc_session("sop", "UF", [ep["id"]])["session_id"]
    svc.save_draft(sid, "SOP-SPLUNK-001 / CVE-2024-1234: ติดตั้ง splunkforwarder-9.3.0 บน splunk-svr ส่งไป 10.0.0.5:9997 (port 9997)\n"
                        "และ backup ไปที่ 10.9.9.9 ด้วย Splunk 9.4.1 บน logsrv-02\n")
    fc = svc.fact_check(sid)
    bad = {u["value"] for u in fc["unsupported"]}
    assert {"10.9.9.9", "9.4.1", "logsrv-02"} <= bad
    assert not bad & {"10.0.0.5:9997", "9.3.0", "splunk-svr", "9997", "SOP-SPLUNK-001", "CVE-2024-1234"}
    assert fc["ok"] is False and fc["checked"] >= 6


def test_ai_titles_rename_auto_episodes(cfg, svc, sample_day, fake_llm):
    _setup_llm(cfg, fake_llm)
    svc.refresh()
    eps = svc.list_episodes(DAY)
    svc.update_episode(eps[1]["id"], title="ชื่อที่ผู้ใช้ตั้งเอง")  # locked titles are left alone
    FakeLLM.reply = json.dumps([{"id": eps[0]["id"], "title": "ติดตั้ง Splunk UF บน splunk-svr"},
                                {"id": eps[1]["id"], "title": "should be ignored"}, {"id": 999, "title": "x"}])
    res = svc.ai_title_episodes(DAY)
    assert res["renamed"] == 1
    after = svc.list_episodes(DAY)
    assert after[0]["title"] == "ติดตั้ง Splunk UF บน splunk-svr" and after[0]["title_locked"]
    assert after[1]["title"] == "ชื่อที่ผู้ใช้ตั้งเอง"
    prompt = FakeLLM.calls[-1]["body"]["messages"][0]["content"]
    assert "Sup3rS3cret" not in prompt and "splunk-svr" in prompt


def test_quality_endpoints(svc, cfg, sample_day):
    app = create_app(svc, port=8765)
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        assert c.post("/api/profile", json={"author": "Teerapat S.", "team": "Sysware"}, headers=H).json()["effective_author"] == "Teerapat S."
        assert c.get("/api/profile").json()["team"] == "Sysware"
        st = c.post("/api/style/sop", json={"style": "- สั้น"}, headers=H).json()
        assert st["style"] == "- สั้น" and c.get("/api/style/sop").json()["style"] == "- สั้น"
        assert c.get("/api/style/nope").status_code == 400
        bad = c.post("/api/style/sop/learn", json={}, headers=H)
        assert bad.status_code == 400  # no edits yet
        svc.refresh()
        ep = svc.list_episodes(DAY)[0]
        sid = svc.start_doc_session("sop", "x", [ep["id"]])["session_id"]
        svc.save_draft(sid, "host 10.1.2.3")
        assert c.get(f"/api/docs/{sid}/factcheck").json()["unsupported"][0]["value"] == "10.1.2.3"
