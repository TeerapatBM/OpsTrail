"""Teams digest uses synthetic data and a loopback webhook only."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from starlette.testclient import TestClient

from conftest import DAY, at, shell, window, write_jsonl
from opstrail import teams
from opstrail.agent.daemon import Agent
from opstrail.web.app import create_app


@pytest.fixture
def webhook():
    calls = []
    statuses = []
    destinations = []
    entered, release = threading.Event(), threading.Event()
    release.set()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            destinations.append(self.path)
            calls.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            entered.set()
            release.wait(5)
            status = statuses.pop(0) if statuses else 202
            self.send_response(status)
            if status == 302:
                self.send_header('Location', '/redirect-target')
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}/secret?sig=DO-NOT-LOG', calls, statuses, entered, release, destinations
    release.set()
    server.shutdown()
    server.server_close()
    thread.join(2)


def test_settings_secret_keep_clear_and_csrf(svc, webhook):
    url = webhook[0]
    with TestClient(create_app(svc), base_url='http://127.0.0.1:8765') as client:
        route = '/api/recap/settings'
        assert client.get(route).json() == {'has_webhook': False}
        assert client.post(route, json={'teams_webhook_url': url}).status_code == 403
        headers = {'X-OpsTrail': '1'}
        saved = client.post(route, json={'teams_webhook_url': url}, headers=headers)
        assert saved.json() == {'has_webhook': True}
        assert url not in saved.text + client.get(route).text
        assert url not in (svc.cfg.home / 'recap.json').read_text()
        assert url not in svc.cfg.config_path.read_text()
        assert client.post(route, json={'teams_webhook_url': ''}, headers=headers).json()['has_webhook']
        assert teams.webhook_url(svc.cfg) == url
        assert client.post(route, json={'clear_webhook': True}, headers=headers).json() == {'has_webhook': False}
        assert teams.webhook_url(svc.cfg) == ''


def test_card_shape_privacy_and_retry(svc, cfg, webhook):
    url, calls, statuses, _, _, _ = webhook
    write_jsonl(cfg, 'private', [shell(at(9, 0), 'Get-SecretCustomerData'),
                               window(at(9, 1), 'pwsh.exe', 'PRIVATE-WINDOW-TITLE', 3600),
                               window(at(14, 0), 'ms-teams.exe', 'Private meeting | Microsoft Teams', 600)])
    svc.refresh()
    episodes = svc.store.episodes_between(DAY)
    # Candidate detection uses stats, but those stats and raw data must not be posted.
    episodes[0]['stats']['commands'] = 9
    payload = teams.build_card(cfg, DAY, episodes)
    statuses.extend([500, 202])
    assert teams.deliver(url, payload)
    assert len(calls) == 2 and calls[0] == calls[1]
    card = calls[0]['attachments'][0]
    assert calls[0]['type'] == 'message'
    assert card['contentType'] == 'application/vnd.microsoft.card.adaptive'
    assert card['content']['type'] == 'AdaptiveCard'
    assert card['content']['version'] == '1.4'
    text = json.dumps(calls[0], ensure_ascii=False)
    assert 'Get-SecretCustomerData' not in text and 'PRIVATE-WINDOW-TITLE' not in text
    assert 'Private meeting' not in text
    assert '09:00' in text and '14:00' in text and 'SOP' in text
    assert 'ประชุม' in text and 'งานที่ควรทำเป็นเอกสาร' in text


def test_failures_are_bounded_and_do_not_log_url(webhook, caplog):
    url, calls, statuses, _, _, _ = webhook
    statuses.extend([503, 503, 202])
    assert not teams.deliver(url, {'type': 'message'})
    assert len(calls) == 2
    assert 'Teams' in caplog.text and 'DO-NOT-LOG' not in caplog.text and url not in caplog.text


def test_auto_recap_dispatch_is_nonblocking_and_gated(svc, sample_day, webhook):
    url, calls, _, entered, release, _ = webhook
    svc.refresh()
    assert svc.send_teams_digest(DAY) is None
    svc.save_recap_settings(url)
    release.clear()
    agent = Agent(svc)
    agent._recap_if_needed(DAY, popup=False)
    assert entered.wait(2)
    assert not release.is_set()  # recap returned while HTTP is still waiting
    agent._recap_if_needed(DAY, popup=False)
    release.set()
    assert len(calls) == 1


def test_invalid_and_corrupt_webhooks_fail_closed(cfg, svc):
    for value in ('file:///secret', 'http://example.com/secret', 'https://user:pass@example.com/x', 'bad'):
        with pytest.raises(ValueError, match='Webhook'):
            svc.save_recap_settings(value)
    cfg.recap['teams_webhook_url'] = 'https://example.com/plaintext-is-ignored'
    assert teams.webhook_url(cfg) == ''
    (cfg.home / 'recap.json').write_text('{broken', encoding='utf-8')
    assert svc.send_teams_digest(DAY) is None
    (cfg.home / 'recap.json').write_text('{"teams_webhook_url": "dpapi:broken"}', encoding='utf-8')
    assert svc.send_teams_digest(DAY) is None


def test_card_keeps_explicit_titles_and_bounds_size(cfg):
    ep = {'id': 1, 'title': 'ติดตั้งระบบ password=private', 'title_locked': True,
          'start_epoch': 1792375200, 'end_epoch': 1792378800,
          'origin': 'manual', 'stats': {'active_s': 3600, 'project': 'test'}}
    payload = teams.build_card(cfg, DAY, [ep] * 1000)
    text = json.dumps(payload, ensure_ascii=False)
    assert 'ติดตั้งระบบ' in text and 'private' not in text
    assert 'Delivery doc' in text
    assert len(json.dumps(payload).encode()) < 28000


def test_explicit_title_cannot_republish_capture(svc, cfg, webhook):
    url, calls, _, _, _, _ = webhook
    write_jsonl(cfg, 'capture', [shell(at(9, 0), 'Get-PrivateDatabase'),
                               window(at(9, 1), 'pwsh.exe', 'PRIVATE TITLE', 120),
                               shell(at(13, 0), 'Remove-Data    -Force')])
    svc.refresh()
    ep = svc.store.episodes_between(DAY)[0]
    svc.save_recap_settings(url)
    for title in ('Run Get-PrivateDatabase now', 'Review PRIVATE TITLE', 'Remove-Data -Force'):
        svc.update_episode(ep['id'], title=title)
        worker = svc.send_teams_digest(DAY)
        worker.join(3)
        assert not worker.is_alive()
        text = json.dumps(calls[-1])
        assert 'Get-PrivateDatabase' not in text and 'PRIVATE TITLE' not in text
        assert 'Remove-Data' not in text


def test_delivery_timeout_retry_is_bounded(monkeypatch, caplog):
    attempts = []

    class TimeoutOpener:
        def open(self, req, timeout):
            attempts.append(timeout)
            raise TimeoutError('https://secret.example/?sig=PRIVATE')

    monkeypatch.setattr(teams.urllib.request, 'build_opener', lambda *args: TimeoutOpener())
    assert not teams.deliver('https://example.com/webhook', {'type': 'message'})
    assert attempts == [10, 10]
    assert 'PRIVATE' not in caplog.text


def test_custom_redaction_and_empty_day(cfg):
    cfg.redaction['extra_patterns'] = ['CUSTOMER']
    ep = {'id': 7, 'title': 'CUSTOMER deployment', 'title_locked': True, 'origin': 'manual',
          'start_epoch': 1792375200, 'end_epoch': 1792378800, 'stats': {}}
    text = json.dumps(teams.build_card(cfg, DAY, [ep]))
    assert 'CUSTOMER' not in text
    assert teams.build_card(cfg, DAY, [])['attachments'][0]['content']['body']


def test_redirect_does_not_forward_digest(webhook):
    url, calls, statuses, _, _, destinations = webhook
    statuses.extend([302, 302])
    assert not teams.deliver(url, {'type': 'message'})
    assert len(calls) == 2
    assert destinations == ['/secret?sig=DO-NOT-LOG'] * 2
