"""Web API, localhost security and LLM provider tests (no real network)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from conftest import DAY
from starlette.testclient import TestClient

from opstrail import llm
from opstrail.web.app import create_app

H = {"x-opstrail": "1"}


@pytest.fixture()
def client(svc):
    app = create_app(svc, port=8765)
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c


# ------------------------------------------------------------------ security
def test_rejects_foreign_host_and_csrf(svc):
    app = create_app(svc, port=8765)
    with TestClient(app, base_url="http://evil.example") as evil:
        assert evil.get("/api/status").status_code == 403  # DNS-rebinding style request
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        assert c.post("/api/notes", json={"text": "x"}).status_code == 403  # no custom header
        r = c.post("/api/notes", json={"text": "x"}, headers={**H, "origin": "https://evil.example"})
        assert r.status_code == 403
        ok = c.post("/api/notes", json={"text": "hello"}, headers={**H, "origin": "http://127.0.0.1:8765"})
        assert ok.status_code == 200
        page = c.get("/")
        assert page.status_code == 200 and "OpsTrail" in page.text
        assert "script-src 'self'" in page.headers["content-security-policy"]
        assert page.headers["x-frame-options"] == "DENY"
        assert c.get("/static/app.js").status_code == 200


def test_shots_only_inside_shots_dir(client, svc, sample_day, tmp_path):
    svc.refresh()
    shot = next(e for e in svc.store.events_for_date(DAY) if e["type"] == "screenshot")
    r = client.get(f"/api/shots/{shot['id']}")
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")
    # an event pointing outside ~/.opstrail/shots must not be served
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"\x89PNG fake")
    eid = svc.record("screenshot", {"path": str(secret), "app": "x"}, source="cli")
    assert client.get(f"/api/shots/{eid}").status_code == 400
    note_id = svc.record("note", {"text": "n"}, source="cli")
    assert client.get(f"/api/shots/{note_id}").status_code == 400


# ---------------------------------------------------------------- workflow
def test_day_episodes_docs_flow(client, svc, sample_day):
    day = client.get(f"/api/day/{DAY}").json()
    assert day["summary"]["work_items"] == 2 and day["recap"] is None
    ep = day["episodes"][0]
    assert client.post(f"/api/episodes/{ep['id']}", json={"title": "ติดตั้ง UF"}, headers=H).json()["title"] == "ติดตั้ง UF"
    detail = client.get(f"/api/episodes/{ep['id']}").json()
    assert any(e["type"] == "shell" for e in detail["events"]) and detail["windows"]

    recap = client.post(f"/api/day/{DAY}/recap", json={}, headers=H).json()
    assert recap["session_id"] and recap["version"] == 1
    assert client.get(f"/api/day/{DAY}").json()["recap"]["session_id"] == recap["session_id"]
    assert client.get("/api/recaps").json()[0]["date"] == DAY

    created = client.post(
        "/api/docs", json={"template": "sop", "title": "SOP UF", "episode_ids": [ep["id"]]}, headers=H
    ).json()
    sid = created["session_id"]
    doc = client.get(f"/api/docs/{sid}").json()
    assert doc["version"] == 0 and doc["episodes"][0]["id"] == ep["id"]

    prompt = client.get(f"/api/docs/{sid}/prompt", params={"instruction": "เน้น rollback"}).json()["prompt"]
    assert "เน้น rollback" in prompt and "Markdown only" in prompt and "save_draft" not in prompt

    assert client.post(f"/api/docs/{sid}/save", json={"markdown": "# SOP\n\nhello"}, headers=H).json()["version"] == 1
    meta = client.post(f"/api/docs/{sid}/meta", json={"status": "review", "title": "SOP UF v2"}, headers=H).json()
    assert meta["status"] == "review" and meta["title"] == "SOP UF v2"
    added = client.post(f"/api/docs/{sid}/sources", json={"date": DAY}, headers=H).json()
    assert added["sources_added"] == [f"date {DAY}"]

    dl = client.get(f"/api/docs/{sid}/download", params={"format": "docx"})
    assert dl.status_code == 200 and dl.content[:2] == b"PK"
    assert "attachment" in dl.headers["content-disposition"]
    md = client.get(f"/api/docs/{sid}/download", params={"format": "md"})
    assert md.status_code == 200 and "hello" in md.text

    found = client.get("/api/search", params={"q": "forward-server"}).json()
    assert found["activity"]
    assert client.get("/api/docs").json()[0]["session_id"] in (sid, recap["session_id"])

    # errors are JSON with 400
    bad = client.post("/api/docs", json={"template": "nope", "title": "x", "date": DAY}, headers=H)
    assert bad.status_code == 400 and "unknown template" in bad.json()["error"]


def test_capture_toggle_and_status(client, cfg):
    assert client.post("/api/capture", json={"paused": True}, headers=H).json() == {"capturing": False}
    assert cfg.is_paused()
    st = client.get("/api/status").json()
    assert st["capturing"] is False and "llm" in st and st["hotkeys"]["note"]
    client.post("/api/capture", json={"paused": False}, headers=H)
    assert not cfg.is_paused()


def test_generate_without_provider_gives_clear_error(client, svc, sample_day):
    svc.refresh()
    ep = svc.list_episodes(DAY)[0]
    sid = svc.start_doc_session("sop", "x", [ep["id"]])["session_id"]
    r = client.post(f"/api/docs/{sid}/generate", json={}, headers=H)
    assert r.status_code == 502 and "no AI provider" in r.json()["error"]


# --------------------------------------------------------------- providers
class FakeLLM(BaseHTTPRequestHandler):
    calls: list[dict] = []
    reply: str | None = None  # override the text returned by /v1/messages

    def log_message(self, *args):  # silence
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("x-api-key") == "sk-org" and not self.headers.get("anthropic-workspace-id"):
            return self._send({"error": {"message": "This API key is not scoped to a workspace, so this request "
                                         "must include the anthropic-workspace-id header"}}, 400)
        FakeLLM.calls.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}})
        self._send({"data": [{"id": "model-a"}, {"id": "model-b"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        FakeLLM.calls.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        if self.path.startswith("/v1/messages"):
            if self.headers.get("x-api-key") == "sk-org" and not self.headers.get("anthropic-workspace-id"):
                return self._send({"type": "error", "error": {"type": "invalid_request_error", "message":
                    "This API key is not scoped to a workspace, so this request must include the "
                    "anthropic-workspace-id header with the ID of the workspace to use."}}, 400)
            if self.headers.get("x-api-key") not in ("sk-test", "sk-org"):
                return self._send({"error": {"message": "invalid x-api-key"}}, 401)
            text = FakeLLM.reply if FakeLLM.reply is not None else "```markdown\n# SOP: จาก Claude\n\nok\n```"
            return self._send({"model": body["model"], "stop_reason": "end_turn",
                               "content": [{"type": "text", "text": text}]})
        return self._send({"model": body.get("model", "dep"), "choices": [
            {"finish_reason": "stop", "message": {"content": "# จาก OpenAI\n\n![x](shot://1)"}}]})


@pytest.fixture()
def fake_llm(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    for var in ("OPSTRAIL_LLM_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    server = HTTPServer(("127.0.0.1", 0), FakeLLM)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    FakeLLM.calls = []
    FakeLLM.reply = None
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_anthropic_provider_via_web(client, svc, sample_day, fake_llm, cfg):
    saved = client.post(
        "/api/llm", json={"provider": "anthropic", "base_url": fake_llm, "model": "claude-x", "api_key": "sk-test"}, headers=H
    ).json()
    assert saved["has_key"] and saved["key_source"] == "stored" and "api_key" not in saved and saved["ready"]
    stored = json.loads((cfg.home / "llm.json").read_text())
    assert "sk-test" not in json.dumps(stored)  # never plain text in the file
    # saving again without a key keeps it
    assert client.post("/api/llm", json={"provider": "anthropic", "base_url": fake_llm, "model": "claude-x", "api_key": ""},
                       headers=H).json()["has_key"]

    assert client.post("/api/llm/test", json={}, headers=H).json()["models"] == ["model-a", "model-b"]
    svc.refresh()
    ep = svc.list_episodes(DAY)[0]
    sid = svc.start_doc_session("sop", "UF", [ep["id"]])["session_id"]
    r = client.post(f"/api/docs/{sid}/generate", json={"instruction": "สั้นๆ"}, headers=H).json()
    assert r["markdown"].startswith("# SOP: จาก Claude") and "```" not in r["markdown"]  # outer fence stripped
    assert r["model"] == "anthropic:claude-x" and r["version"] == 1
    call = [c for c in FakeLLM.calls if c["path"].startswith("/v1/messages")][-1]
    assert call["headers"]["anthropic-version"] == "2023-06-01"
    assert call["body"]["system"] and "สั้นๆ" in call["body"]["messages"][0]["content"]
    assert "Sup3rS3cret" not in call["body"]["messages"][0]["content"]  # redacted data only
    # second run includes the current draft for revision
    client.post(f"/api/docs/{sid}/generate", json={}, headers=H)
    last = [c for c in FakeLLM.calls if c["path"].startswith("/v1/messages")][-1]
    assert "Current draft" in last["body"]["messages"][0]["content"]

    client.post("/api/llm", json={"clear_key": True}, headers=H)
    assert not llm.public_settings(cfg)["has_key"]
    bad = client.post(f"/api/docs/{sid}/generate", json={}, headers=H)
    assert bad.status_code == 502 and "API key missing" in bad.json()["error"]


def test_openai_compatible_local_without_key(cfg, fake_llm):
    llm.save_settings(cfg, {"provider": "openai", "base_url": f"{fake_llm}/v1", "model": "llama3"})
    st = llm.public_settings(cfg)
    assert st["ready"] and not st["has_key"]  # local endpoint needs no key
    res = llm.complete(cfg, "sys", "user")
    assert res.text.startswith("# จาก OpenAI") and res.label == "openai:llama3"
    call = FakeLLM.calls[-1]
    assert call["path"] == "/v1/chat/completions" and call["body"]["messages"][0]["role"] == "system"
    assert "authorization" not in {k.lower() for k in call["headers"]}


def test_azure_provider(cfg, fake_llm, monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "az-key")
    llm.save_settings(cfg, {"provider": "azure", "azure_endpoint": fake_llm, "azure_deployment": "docs-gpt"})
    st = llm.public_settings(cfg)
    assert st["key_source"] == "AZURE_OPENAI_API_KEY" and st["effective_model"] == "docs-gpt"
    res = llm.complete(cfg, "sys", "user")
    call = FakeLLM.calls[-1]
    assert call["path"] == "/openai/deployments/docs-gpt/chat/completions?api-version=2024-10-21"
    assert call["headers"]["api-key"] == "az-key" and "model" not in call["body"]
    assert res.label == "azure:docs-gpt"


def test_http_errors_are_readable(cfg, fake_llm):
    llm.save_settings(cfg, {"provider": "anthropic", "base_url": fake_llm}, api_key="wrong")
    with pytest.raises(llm.LLMError, match="HTTP 401.*invalid x-api-key"):
        llm.complete(cfg, "s", "u")
    llm.save_settings(cfg, {"provider": "anthropic", "base_url": "http://127.0.0.1:9"}, api_key="k")
    with pytest.raises(llm.LLMError, match="cannot reach"):
        llm.complete(cfg, "s", "u")


def test_strip_fences_keeps_inner_code():
    assert llm.strip_fences("```markdown\n# T\n```bash\nls\n```\n```") == "# T\n```bash\nls\n```\n"
    assert llm.strip_fences("```bash\nls\n```\ntext\n```bash\npwd\n```").startswith("```bash")


def test_anthropic_multi_workspace_key_needs_workspace_id(client, cfg, fake_llm):
    client.post("/api/llm", json={"provider": "anthropic", "base_url": fake_llm, "api_key": "sk-org"}, headers=H)
    bad = client.post("/api/llm/test", json={}, headers=H)
    assert bad.status_code == 502 and "Workspace ID" in bad.json()["error"] and "wrkspc_" in bad.json()["error"]
    saved = client.post("/api/llm", json={"provider": "anthropic", "base_url": fake_llm,
                                          "anthropic_workspace_id": "wrkspc_01TEST"}, headers=H).json()
    assert saved["anthropic_workspace_id"] == "wrkspc_01TEST" and saved["has_key"]
    assert client.post("/api/llm/test", json={}, headers=H).json()["ok"]
    res = llm.complete(cfg, "s", "u")
    assert res.text.startswith("```markdown") or res.text
    call = FakeLLM.calls[-1]
    assert call["headers"]["anthropic-workspace-id"] == "wrkspc_01TEST"


def test_stop_when_agent_not_running(home, capsys):
    from opstrail.cli import main

    assert main(["stop"]) == 0
    assert "not running" in capsys.readouterr().out
