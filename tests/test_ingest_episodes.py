import base64
import time

from conftest import DAY, at, note, shell, window, write_jsonl

from opstrail.events import parse_ts
from opstrail.ingest import ingest_inbox


def test_parse_ts_variants(cfg):
    tz = cfg.tz
    assert parse_ts("2026-10-19T09:15:02.1234567+07:00", tz).microsecond == 123456  # PowerShell 'o'
    assert parse_ts("2026-10-19T09:15:02.12+07:00", tz).microsecond == 120000
    assert parse_ts("2026-10-19T02:15:02Z", tz).hour == 2
    assert parse_ts(1760840102, tz).year == 2025
    assert parse_ts("2026-10-19T09:15:02", tz).utcoffset().total_seconds() == 7 * 3600


def test_ingest_redacts_and_dedupes(cfg, svc, sample_day):
    n = ingest_inbox(cfg, svc.store)
    assert n == 12
    assert not list(cfg.inbox_dir.glob("*.jsonl"))
    events = svc.store.events_for_date(DAY)
    cmds = [e["data"]["cmd"] for e in events if e["type"] == "shell"]
    assert any("[REDACTED]" in c for c in cmds)
    assert not any("Sup3rS3cret" in c for c in cmds)
    # same lines again -> duplicates ignored
    write_jsonl(cfg, "again", [shell(at(9, 10), "ssh admin@splunk-svr")])
    assert ingest_inbox(cfg, svc.store) == 0


def test_bad_lines_are_rejected_not_fatal(cfg, svc):
    path = cfg.inbox_dir / "bad.jsonl"
    path.write_text('{"type":"nope"}\nnot json\n' + '{"v":1,"ts":"%s","type":"note","data":{"text":"ok"}}\n' % at(10, 0),
                    encoding="utf-8")
    assert ingest_inbox(cfg, svc.store) == 1
    assert (cfg.inbox_dir / "rejected.log").read_text(encoding="utf-8").count("\n") == 2


def test_tsv_bash_format(cfg, svc):
    b = lambda s: base64.b64encode(s.encode()).decode()  # noqa: E731
    epoch = int(time.time())
    (cfg.inbox_dir / "bash-host-1.tsv").write_text(
        f"tsv1\t{epoch}\t1\t{b('/opt')}\t{b('systemctl restart splunk')}\thost1\troot\tbash\tS1\n", encoding="utf-8"
    )
    assert ingest_inbox(cfg, svc.store) == 1
    ev = svc.store.events_for_date(cfg.today())[0]
    assert ev["data"]["cmd"] == "systemctl restart splunk"
    assert ev["data"]["success"] is False and ev["host"] == "host1"


def test_episode_grouping(cfg, svc, sample_day):
    svc.refresh()
    eps = svc.list_episodes(DAY)
    assert len(eps) == 2, eps
    morning, afternoon = eps
    assert "Splunk" in morning["tags"] and morning["title"].startswith("Splunk")
    assert "splunk-svr" in morning["targets"]
    assert morning["commands"] == 5 and morning["failed_commands"] == 1
    assert morning["screenshots"] == 1 and morning["notes"] == 1
    assert "Sentinel" in afternoon["tags"]


def test_project_switch_splits_without_gap(cfg, svc):
    write_jsonl(cfg, "switch", [
        window(at(10, 0), "msedge.exe", "Splunk search", 600),
        window(at(10, 10), "msedge.exe", "Sentinel incidents", 900),
        window(at(10, 25), "msedge.exe", "Sentinel KQL", 600),
    ])
    svc.refresh()
    titles = [e["tags"] for e in svc.list_episodes(DAY)]
    assert titles == [["Splunk"], ["Sentinel"]]


def test_short_interior_switch_is_absorbed(cfg, svc):
    write_jsonl(cfg, "blip", [
        window(at(10, 0), "msedge.exe", "Splunk search", 600),
        window(at(10, 10), "msedge.exe", "Sentinel quick look", 60),
        window(at(10, 11), "msedge.exe", "Splunk dashboards", 600),
    ])
    svc.refresh()
    assert len(svc.list_episodes(DAY)) == 1


def test_manual_task_and_incremental_ids(cfg, svc):
    write_jsonl(cfg, "t1", [
        {"v": 1, "ts": at(14, 0), "type": "task", "data": {"action": "start", "title": "Patch web01"}},
        shell(at(14, 1), "Get-HotFix"),
    ])
    svc.refresh()
    first = svc.list_episodes(DAY)
    assert first[0]["title"] == "Patch web01" and first[0]["open_task"]
    # later events (even after a long gap) stay in the open manual task; ids are stable
    write_jsonl(cfg, "t2", [
        shell(at(15, 30), "Restart-Computer -Force"),
        {"v": 1, "ts": at(15, 40), "type": "task", "data": {"action": "stop", "title": "Patch web01"}},
        shell(at(15, 45), "Get-Date"),
    ])
    svc.refresh()
    eps = svc.list_episodes(DAY)
    assert eps[0]["id"] == first[0]["id"] and eps[0]["commands"] == 2 and not eps[0]["open_task"]
    assert len(eps) == 2  # the command after `stop` starts a new episode


def test_update_merge_and_note(cfg, svc, sample_day):
    svc.refresh()
    a, b = svc.list_episodes(DAY)
    upd = svc.update_episode(a["id"], title="ติดตั้ง Splunk UF บน splunk-svr", tags="Splunk,Customer-X", note="เสร็จแล้ว")
    assert upd["title_locked"] and upd["tags"] == ["Splunk", "Customer-X"] and upd["notes"] == 2
    merged = svc.merge_episodes([a["id"], b["id"]], "Splunk + Sentinel")
    assert merged["title"] == "Splunk + Sentinel" and merged["commands"] == 6
    assert len(svc.list_episodes(DAY)) == 1


def test_gap_split(cfg, svc):
    write_jsonl(cfg, "gap", [shell(at(8, 0), "whoami"), shell(at(8, 50), "hostname")])
    svc.refresh()
    assert len(svc.list_episodes(DAY)) == 2


def test_note_popup_events_from_hotkey(cfg, svc):
    write_jsonl(cfg, "n", [note(at(11, 0), "hello")])
    svc.refresh()
    tl = svc.timeline(DAY)
    assert tl["events"][0]["text"] == "hello"


def test_today_events_are_grouped_immediately_and_switch_is_deferred(cfg, svc):
    svc.record("shell", {"cmd": "splunk status"}, source="bash")
    svc.refresh()
    eps = svc.list_episodes()
    assert len(eps) == 1 and eps[0]["tags"] == ["Splunk"]
    # a brand-new different project right now waits until it lasts min_run_min
    svc.record("shell", {"cmd": "az sentinel list"}, source="bash")
    svc.refresh()
    assert len(svc.list_episodes()) == 1
    assert any(e["episode_id"] is None for e in svc.store.events_for_date(cfg.today()))
    # ...and is grouped once it has lasted long enough
    from opstrail.episodes import assign_episodes
    import time as _t
    assign_episodes(svc.store, cfg, cfg.today(), now=_t.time() + 600)
    assert [e["tags"] for e in svc.list_episodes()] == [["Splunk"], ["Sentinel"]]


def test_concurrent_refresh_does_not_duplicate_episodes(cfg, sample_day):
    import threading

    from opstrail.service import OpsTrail

    services = [OpsTrail(cfg) for _ in range(4)]
    threads = [threading.Thread(target=s.refresh) for s in services]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    services[0].refresh()
    eps = services[0].store.episodes_between(DAY)
    assert len(eps) == 2
    assert all(services[0].store.events_for_episode(e["id"]) for e in eps)
    for s in services:
        s.store.close()


def test_project_tag_is_not_carried_over_a_gap(cfg, svc):
    write_jsonl(cfg, "carry", [
        window(at(9, 0), "msedge.exe", "Splunk search", 600),
        window(at(13, 0), "msedge.exe", "Some vendor portal", 900),   # no project keyword, after a long gap
    ])
    svc.refresh()
    eps = svc.list_episodes(DAY)
    assert [e["tags"] for e in eps] == [["Splunk"], []]
