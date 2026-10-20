"""T-106: opt-in command output (`data.output`) – ingest, redaction, source pack."""

from __future__ import annotations

from opstrail.config import load_config
from opstrail.redact import redact_text
from opstrail.render import command_lines
from opstrail.service import OpsTrail

from conftest import DAY, at, write_jsonl


def enable_output(home, lines: int = 15):
    with (home / "config.toml").open("a", encoding="utf-8") as fh:
        fh.write(f"\n[capture]\nshell_output = true\nshell_output_lines = {lines}\n")
    return load_config(home)


def shell_out(ts: str, cmd: str, output: str, **extra) -> dict:
    data = {"cmd": cmd, "cwd": "C:\\work", "success": True, "output": output, **extra}
    return {"v": 1, "ts": ts, "type": "shell", "source": "powershell", "data": data}


def stored_shells(svc: OpsTrail) -> list[dict]:
    svc.refresh()
    return [e for e in svc.store.events_for_date(DAY) if e["type"] == "shell"]


def test_output_is_dropped_unless_opted_in(cfg, svc):
    assert cfg.capture["shell_output"] is False and cfg.capture["shell_output_lines"] == 15
    write_jsonl(cfg, "ps", [shell_out(at(9, 0), "Get-Service splunkd", "Running  splunkd", output_truncated=True)])
    (ev,) = stored_shells(svc)
    assert "output" not in ev["data"] and "output_truncated" not in ev["data"]


def test_output_is_stored_and_cut_to_configured_lines(home):
    cfg = enable_output(home, lines=3)
    svc = OpsTrail(cfg)
    try:
        write_jsonl(cfg, "ps", [
            shell_out(at(9, 0), "Get-Content a.log", "\r\nl1\r\nl2  \r\nl3\r\nl4\r\n"),
            shell_out(at(9, 1), "Get-Service x", "Running  x"),
            shell_out(at(9, 2), "Set-Location C:\\", "\n\n"),
        ])
        log, svc_ev, cd = stored_shells(svc)
        assert log["data"]["output"] == "l1\nl2\nl3" and log["data"]["output_truncated"] is True
        assert svc_ev["data"]["output"] == "Running  x" and "output_truncated" not in svc_ev["data"]
        assert "output" not in cd["data"]
        assert log["text"] == "Get-Content a.log"  # search text / timelines stay command-only
    finally:
        svc.store.close()


def test_secrets_in_output_are_redacted(home):
    cfg = enable_output(home)
    svc = OpsTrail(cfg)
    output = "\n".join([
        "SPLUNK_HOST=10.10.20.5",
        "SPLUNK_PASSWORD=Pa55w0rd!Uf",
        "admin password: Pa55w0rd!Uf",
        "Authorization: Bearer abcdefghijklmnop1234567890",
        "token=ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "-----BEGIN RSA PRIVATE KEY-----",
        "MIIEowIBAAKCAQEAsecretkeymaterial",
    ])
    try:
        write_jsonl(cfg, "ps", [shell_out(at(9, 0), "Get-Content .\\uf.env", output)])
        (ev,) = stored_shells(svc)
        out = ev["data"]["output"]
        for secret in ("Pa55w0rd!Uf", "abcdefghijklmnop1234567890", "ghp_abc", "MIIEowIBAAKCAQEA"):
            assert secret not in out, secret
        assert "SPLUNK_HOST=10.10.20.5" in out and "SPLUNK_PASSWORD=[REDACTED]" in out
    finally:
        svc.store.close()


def test_redaction_of_env_style_keys_and_cut_pem():
    assert redact_text("$env:SPLUNK_PASSWORD='x1y2'") == "$env:SPLUNK_PASSWORD=[REDACTED]"
    assert redact_text("DB_API_KEY: abc123") == "DB_API_KEY: [REDACTED]"
    assert redact_text("passwordless login enabled") == "passwordless login enabled"
    cut = "key:\n-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\nAAAA"
    assert redact_text(cut) == "key:\n[REDACTED]"
    full = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\nafter"
    assert redact_text(full) == "[REDACTED]\nafter"


def test_quoted_secret_cut_by_line_truncation_is_redacted():
    # the PowerShell hook cuts output lines at 400 chars + "...": the closing quote is lost
    secret = "S" * 500
    for line in (f'password="{secret}"', f"api_key: '{secret}'", f"--token \"{secret}\"",
                 f'AccountKey="{secret}"'):
        cut = line[:400] + "..."
        out = redact_text(cut + "\nnext line")
        assert "SSSS" not in out and "[REDACTED]" in out, out
        assert out.endswith("\nnext line")  # masked to the end of the cut line only
    assert redact_text('password="abc" user=bob') == "password=[REDACTED] user=bob"


def test_source_pack_shows_output_under_each_command(home):
    cfg = enable_output(home, lines=40)
    svc = OpsTrail(cfg)
    try:
        long_out = "\n".join(f"log line {i}" for i in range(1, 31))
        write_jsonl(cfg, "ps", [
            shell_out(at(9, 0), "Get-Service splunkd", "Status   Name\n------   ----\nRunning  splunkd"),
            shell_out(at(9, 1), "Get-Content splunkd.log -Tail 30", long_out),
            {"v": 1, "ts": at(9, 2), "type": "shell", "source": "powershell", "data": {"cmd": "Restart-Service splunkd"}},
        ])
        svc.refresh()
        (ep,) = svc.list_episodes(DAY)
        sid = svc.start_doc_session("sop", "UF", [ep["id"]])["session_id"]
        pack = svc.source_pack(sid)
        assert "captured output" in pack
        lines = pack.splitlines()
        i = next(n for n, line in enumerate(lines) if line.endswith("Get-Service splunkd"))
        assert lines[i + 1 : i + 4] == ["    │ Status   Name", "    │ ------   ----", "    │ Running  splunkd"]
        j = next(n for n, line in enumerate(lines) if line.endswith("Get-Content splunkd.log -Tail 30"))
        shown = lines[j + 1 : j + 17]
        assert shown[0] == "    │ log line 1" and shown[14] == "    │ log line 15" and shown[15] == "    │ …"
        assert "log line 16" not in pack  # max 15 lines per command in the pack
        assert lines[j + 17].endswith("Restart-Service splunkd")
        # the daily worklog / title prompts list commands only
        events = svc.store.events_for_episode(ep["id"])
        assert all("│" not in line for line in command_lines(events, cfg.tz))
    finally:
        svc.store.close()


def test_repeated_command_keeps_latest_output_and_limit_counts_commands(cfg):
    tz = cfg.tz
    base = 1_760_000_000

    def ev(i: int, cmd: str, output: str = "") -> dict:
        data = {"cmd": cmd, "cwd": "C:\\"}
        if output:
            data["output"] = output
        return {"id": i, "type": "shell", "epoch": base + i, "data": data}

    events = [ev(1, "Get-Service x", "Stopped  x"), ev(2, "Get-Service x", "Running  x")]
    lines = command_lines(events, tz, with_output=True)
    assert len(lines) == 2 and lines[0].endswith("(x2)") and lines[1] == "    │ Running  x"

    many = [ev(i, f"cmd {i}", "out") for i in range(10)]
    lines = command_lines(many, tz, limit=4, with_output=True)
    assert sum(1 for line in lines if "cmd " in line) == 4 and "more commands omitted" in lines[4]
    assert lines.count("    │ out") == 4
