import pytest

from opstrail.redact import MASK, compile_extra, redact_obj, redact_text


@pytest.mark.parametrize(
    "raw, secret",
    [
        ("splunk start --password Sup3rS3cret", "Sup3rS3cret"),
        ("mysql -u root -pHunter22 db", "Hunter22"),
        ("$p = ConvertTo-SecureString 'P@ssw0rd!' -AsPlainText -Force", "P@ssw0rd!"),
        ("New-LocalUser -Name bob -Password $(Read-Host)", None),
        ("curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456' https://x", "abcdefghijklmnopqrstuvwxyz123456"),
        ("git clone https://bob:ghp_abcdefghijklmnopqrstuvwxyz0123456789@github.com/x/y", "ghp_abcdefghijklmnopqrstuvwxyz0123456789"),
        ("DefaultEndpointsProtocol=https;AccountName=a;AccountKey=abc123==;EndpointSuffix=core", "abc123=="),
        ("https://acct.blob.core.windows.net/c/f?sv=2022&sig=AbCdEf%2B123", "AbCdEf%2B123"),
        ("export OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz", "sk-proj-abcdefghijklmnopqrstuvwxyz"),
        ("aws configure set aws_secret_access_key wJalrXUtnFEMI/K7MDENG", None),
        ("net user svc_backup Winter2026! /add", "Winter2026!"),
        ("sshpass -p 'hunter2' ssh root@10.0.0.1", "hunter2"),
        ("token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N", "eyJhbGciOiJIUzI1NiJ9"),
        ("client_secret: 'abc.DEF~123'", "abc.DEF~123"),
        ("LTAI5tAbCdEfGhIjKlMn is the alibaba key", "LTAI5tAbCdEfGhIjKlMn"),
        ("splunk add forward-server 10.0.0.5:9997 -auth admin:S3cret!", "S3cret!"),
        ("curl -u svc:Pa55word https://api.local/x", "Pa55word"),
        ("curl --user 'svc:Pa55word' https://api.local/x", "Pa55word"),
    ],
)
def test_secrets_are_masked(raw, secret):
    out = redact_text(raw)
    if secret:
        assert secret not in out
        assert MASK in out


def test_private_key_block():
    raw = "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\ndef\n-----END OPENSSH PRIVATE KEY-----"
    assert redact_text(raw) == MASK


def test_harmless_commands_untouched():
    for cmd in ("ssh -p 2222 admin@host", "Get-Service splunkd", "kubectl get pods -n prod", "ls -la /etc",
                "docker run -u 1000 img", "splunk add forward-server 10.0.0.5:9997"):
        assert redact_text(cmd) == cmd


def test_extra_patterns_and_nested():
    extra = compile_extra([r"CUST-\d{6}", "("])  # invalid regex ignored
    data = {"cmd": "lookup CUST-123456", "nested": ["password=abc"]}
    out = redact_obj(data, extra)
    assert out["cmd"] == f"lookup {MASK}"
    assert out["nested"][0] == f"password={MASK}"
