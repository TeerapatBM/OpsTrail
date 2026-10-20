"""Synthetic browser capture; never uses a real browser profile or OpsTrail home."""
import json

import pytest
from starlette.testclient import TestClient

from opstrail.activity import Classifier
from opstrail.web.app import create_app

ORIGIN = "chrome-extension://" + "a" * 32
BODY = {"url": "https://portal.azure.com/?token=secret#view/Test/page?password=hidden",
        "title": "Azure password=titleSecret", "tab_id": 7, "ts": "2026-10-19T09:00:00+07:00"}


@pytest.fixture()
def browser_client(svc):
    with TestClient(create_app(svc), base_url="http://127.0.0.1:8765") as c:
        yield c


def headers(c):
    token = c.post("/api/browser/token", headers={"X-OpsTrail": "1"}).json()["token"]
    return {"X-OpsTrail": "1", "X-OpsTrail-Browser-Token": token, "Origin": ORIGIN}


def test_browser_security_and_redaction(browser_client, svc):
    c = browser_client
    h = headers(c)
    for bad in ({}, {"X-OpsTrail": "1", "Origin": ORIGIN},
                {**h, "X-OpsTrail-Browser-Token": "wrong"}, {**h, "X-OpsTrail": "0"},
                {**h, "Host": "evil.test"}, {**h, "Origin": "https://evil.test"}):
        assert c.post("/api/ingest/browser", json=BODY, headers=bad).status_code == 403
    assert c.post("/api/browser/token", headers=h).status_code == 403
    assert c.post("/api/browser/token").status_code == 403
    assert c.get("/api/browser/token").status_code == 405
    assert c.post("/api/notes", json={"text": "x"}, headers=h).status_code == 403
    assert c.options("/api/ingest/browser", headers={"Origin": ORIGIN,
                     "Access-Control-Request-Method": "POST"}).status_code == 403
    assert c.post("/api/ingest/browser", json={**BODY, "incognito": True}, headers=h).status_code == 400
    r = c.post("/api/ingest/browser", json=BODY, headers=h)
    assert r.status_code == 200
    ev = svc.store.events_for_date("2026-10-19")[0]
    assert ev["type"] == "browser" and ev["data"]["domain"] == "portal.azure.com"
    assert ev["data"]["url"] == "https://portal.azure.com/#view/Test/page"
    assert "titleSecret" not in json.dumps(ev)
    assert "token" not in ev["data"] and "tab_id" not in ev["data"]
    svc.refresh()
    ep = svc.store.episodes_between("2026-10-19")[0]
    from opstrail.render import episode_pack
    assert ev["data"]["url"] in episode_pack(ep, [ev], svc.cfg.tz)


@pytest.mark.parametrize("change", [{"url": "file:///private"}, {"url": "http://[bad"},
    {"ts": "invalid"}, {"title": []}, {"tab_id": "x"}])
def test_browser_invalid(browser_client, change):
    c = browser_client
    assert c.post("/api/ingest/browser", json={**BODY, **change}, headers=headers(c)).status_code == 400


@pytest.mark.parametrize("url,title", [("https://mail.google.com/mail/", "Inbox"),
    ("https://secure.kasikornbank.com/", "Bank"), ("https://portal.azure.com/", "Incognito")])
def test_browser_exclusions(browser_client, svc, url, title):
    c = browser_client
    assert c.post("/api/ingest/browser", json={**BODY, "url": url, "title": title},
                  headers=headers(c)).json()["stored"] is False
    assert not svc.store.events_for_date("2026-10-19")


def test_browser_pause_query_and_token_persistence(browser_client, svc):
    c = browser_client
    h = headers(c)
    assert h == headers(c)
    svc.cfg.set_paused(True)
    assert c.post("/api/ingest/browser", json=BODY, headers=h).json()["stored"] is False
    svc.cfg.set_paused(False)
    svc.cfg.capture["browser_keep_query"] = True
    url = "https://user:pass@portal.azure.com/?token=secret&view=one#blade/Test?password=hidden"
    assert c.post("/api/ingest/browser", json={**BODY, "url": url}, headers=h).status_code == 200
    ev = svc.store.events_for_date("2026-10-19")[0]
    text = json.dumps(ev)
    assert "secret" not in text and "hidden" not in text and "user:pass" not in text
    assert "view=one" in text


def test_browser_domain_boundaries_and_custom_redaction(browser_client, svc):
    c = browser_client
    h = headers(c)
    svc.cfg.capture["exclude_domains"] = ["example.org"]
    for url in ("https://EXAMPLE.ORG./", "https://sub.example.org/"):
        assert c.post("/api/ingest/browser", json={**BODY, "url": url}, headers=h).json()["stored"] is False
    svc.cfg.redaction["extra_patterns"] = ["CustomerName"]
    assert c.post("/api/ingest/browser", json={**BODY, "url": "https://example.org.evil.test/CustomerName",
                  "title": "CustomerName"}, headers=h).json()["stored"] is True
    ev = svc.store.events_for_date("2026-10-19")[0]
    assert "CustomerName" not in json.dumps(ev)
    assert h["X-OpsTrail-Browser-Token"] not in c.get("/api/status").text


def test_invalid_privacy_pattern_fails_closed(browser_client, svc):
    c = browser_client
    svc.cfg.capture["exclude_title_patterns"] = ["["]
    assert c.post("/api/ingest/browser", json=BODY, headers=headers(c)).json()["stored"] is False


def test_pairing_token_new_app_and_corrupt_file(browser_client, svc):
    c = browser_client
    token = headers(c)["X-OpsTrail-Browser-Token"]
    with TestClient(create_app(svc), base_url="http://127.0.0.1:8765") as other:
        assert headers(other)["X-OpsTrail-Browser-Token"] == token
    (svc.cfg.home / "browser_token").write_text("corrupt", encoding="ascii")
    assert c.post("/api/browser/token", headers={"X-OpsTrail": "1"}).status_code == 400
    assert c.post("/api/ingest/browser", json=BODY, headers={"X-OpsTrail": "1",
                  "X-OpsTrail-Browser-Token": "corrupt"}).status_code == 403


@pytest.mark.parametrize("url,subject", [
    ("https://portal.azure.com/#view/Microsoft_Azure_Monitoring/LogsBlade", "Azure portal"),
    ("https://portal.azure.com/#blade/Microsoft_Azure_Security_Insights/Analytics", "Microsoft Sentinel"),
    ("https://security.microsoft.com/sentinel/rules", "Microsoft Sentinel")])
def test_browser_url_classification(url, subject):
    assert Classifier().classify("browser", {"url": url, "title": "Admin"}) == ("console", subject)


def test_browser_title_and_user_url_rules(tmp_path):
    rules = tmp_path / "rules.toml"
    rules.write_text('[[rule]]\nactivity="console"\nurl_regex="vcenter"\n'
                     'title_regex="Admin"\nsubject="Lab"\n', encoding="utf-8")
    clf = Classifier(rules)
    assert clf.classify("browser", {"url": "https://vcenter/ui", "title": "Admin"}) == ("console", "Lab")
    assert clf.classify("browser", {"url": "https://vcenter/ui", "title": "Home"}) == ("other", "")
    assert clf.classify("browser", {"url": "https://example.org", "title": "Admin"}) == ("other", "")
    assert clf.classify("browser", {"url": "https://example.org", "title": "Microsoft Sentinel"}) == ("console", "Microsoft Sentinel")


def test_invalid_url_rule_does_not_classify_every_browser(tmp_path):
    rules = tmp_path / "rules.toml"
    rules.write_text('[[rule]]\nactivity="console"\nurl_regex="["\nsubject="Wrong"\n', encoding="utf-8")
    assert Classifier(rules).classify("browser", {"url": "https://example.org/", "title": "Admin"}) == ("other", "")
