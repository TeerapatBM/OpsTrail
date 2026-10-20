"""Review validation and snapshot behavior without external services."""
import json

import pytest

from opstrail import llm, review
from opstrail.service import OpsTrailError


def test_retry_recovers_and_uses_same_snapshot(svc, cfg, monkeypatch):
    llm.save_settings(cfg, {"provider": "openai", "base_url": "http://127.0.0.1:1"}, profile="reviewer")
    sid = svc.start_doc_session("sop", "Review", date="2026-10-19")["session_id"]
    svc.save_draft(sid, "# Draft\npassword=my-draft-secret")
    calls = []

    def complete(config, system, user, *, profile):
        calls.append((system, user, profile))
        if len(calls) == 1:
            svc.save_draft(sid, "# Concurrent revision")
            return llm.LLMResult("invalid", "openai:check")
        return llm.LLMResult('{"issues":[]}', "openai:check")

    monkeypatch.setattr(llm, "complete", complete)
    out = svc.review_draft(sid)
    assert out["version"] == 1 and len(calls) == 2
    assert all(c[2] == "reviewer" and "my-draft-secret" not in c[1] for c in calls)
    assert all("Concurrent revision" not in c[1] for c in calls)
    assert svc.store.query("SELECT version FROM doc_reviews")[0]["version"] == 1
    assert svc.store.get_version(sid)["version"] == 2


def test_review_requires_saved_draft_and_configuration(svc):
    sid = svc.start_doc_session("sop", "Review", date="2026-10-19")["session_id"]
    with pytest.raises(OpsTrailError, match="draft"):
        svc.review_draft(sid)
    svc.save_draft(sid, "# Draft")
    with pytest.raises(OpsTrailError, match="reviewer"):
        svc.review_draft(sid)


@pytest.mark.parametrize("value", [[], None, {"issues": [None]}, {"issues": [{
    "severity": "warning", "quote": "x", "problem": 1, "suggestion": "x"}]},
    {"issues": [], "extra": True}, {"issues": []}])
def test_review_schema(value):
    if value == {"issues": []}:
        assert review.parse_review(json.dumps(value)) == []
    else:
        with pytest.raises(ValueError):
            review.parse_review(json.dumps(value))


def test_review_truncation_and_safe_errors(svc, cfg, monkeypatch):
    llm.save_settings(cfg, {"provider": "openai"}, profile="reviewer")
    sid = svc.start_doc_session("sop", "Review", date="2026-10-19")["session_id"]
    svc.save_draft(sid, "# Draft")
    calls = []

    def truncated(*args, **kwargs):
        calls.append(1)
        return llm.LLMResult('{"issues":[]}', "check", truncated=True)

    monkeypatch.setattr(llm, "complete", truncated)
    with pytest.raises(OpsTrailError):
        svc.review_draft(sid)
    assert len(calls) == 2 and not svc.store.query("SELECT * FROM doc_reviews")

    def fail(*args, **kwargs):
        raise llm.LLMError("password=upstream-secret")

    monkeypatch.setattr(llm, "complete", fail)
    with pytest.raises(OpsTrailError) as exc:
        svc.review_draft(sid)
    assert "upstream-secret" not in str(exc.value)
