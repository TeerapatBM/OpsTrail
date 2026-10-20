"""Static asset safety and design contract; no browser/network required."""
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess

import pytest

STATIC = Path(__file__).resolve().parents[1] / 'src/opstrail/web/static'


class PageParser(HTMLParser):
    in_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        assert not any(re.match(r'on[a-z]+$', key, re.I) for key in attrs)
        if tag == 'script':
            assert attrs.get('src', '').startswith('/static/')
            self.in_script = True

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            assert not data.strip(), 'Inline script body'


def test_static_assets_are_local_and_csp_safe():
    PageParser().feed((STATIC / 'index.html').read_text(encoding='utf-8'))
    for file in STATIC.iterdir():
        if file.suffix in {'.html', '.css', '.js', '.svg'}:
            text = file.read_text(encoding='utf-8')
            # XML namespace identifiers are not external resource references.
            text = text.replace('http://www.w3.org/2000/svg', '')
            assert not re.search(r'https?://[\w<]', text), file.name
    css = (STATIC / 'app.css').read_text(encoding='utf-8')
    assert len(css.encode()) < 60_000
    assert 'prefers-reduced-motion' in css and ':focus-visible' in css
    assert 'prefers-color-scheme: dark' in css
    for selector in (':root', ':root[data-theme="dark"]', ':root[data-theme="light"]'):
        block = re.search(re.escape(selector) + r'\s*\{([^}]+)', css).group(1)
        for token in ('bg', 'panel', 'text', 'muted', 'accent', 'border', 'on-accent'):
            assert f'--{token}:' in block
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    assert html.index('/static/theme.js') < html.index('/static/app.css')
    assert 'data-theme-select' in html
    assert 'data-theme-select' in (STATIC / 'app.js').read_text(encoding='utf-8')


def test_theme_controller():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is optional; run tests/web_theme.cjs when installed')
    subprocess.run([node, str(Path(__file__).with_name('web_theme.cjs'))], check=True, timeout=15)


@pytest.mark.parametrize('mode', ['light', 'dark'])
def test_theme_contrast(mode):
    css = (STATIC / 'app.css').read_text(encoding='utf-8')
    block = re.search(r':root\[data-theme="' + mode + r'"\]\s*\{([^}]+)', css).group(1)
    tokens = dict(re.findall(r'--([\w-]+):\s*(#[\da-f]{6})', block))

    def luminance(hex_value):
        rgb = [int(hex_value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
        return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))

    pairs = [('text', surface, 4.5) for surface in ('bg', 'panel', 'panel-2')]
    pairs += [('muted', surface, 4.5) for surface in ('bg', 'panel', 'panel-2')]
    pairs += [('accent', 'accent-soft', 4.5), ('on-accent', 'accent', 4.5)]
    pairs += [(status, status + '-soft', 4.5) for status in ('ok', 'warn', 'bad')]
    pairs += [('border', surface, 3) for surface in ('bg', 'panel', 'panel-2')]
    for foreground, background, minimum in pairs:
        values = sorted([luminance(tokens[foreground]), luminance(tokens[background])])
        assert (values[1] + .05) / (values[0] + .05) >= minimum, (mode, foreground, background)


def test_snapshot_seed_is_isolated(tmp_path, monkeypatch):
    from importlib.util import module_from_spec, spec_from_file_location
    repo = STATIC.parents[3]
    spec = spec_from_file_location('snapshot_server', repo / 'scripts/ui_snapshot_server.py')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    # Poison the inherited home: the helper must explicitly choose the new synthetic one.
    monkeypatch.setenv('OPSTRAIL_HOME', str(tmp_path / 'must-not-read'))
    monkeypatch.setenv('OPSTRAIL_TEMPLATES', str(tmp_path / 'must-not-read-templates'))
    monkeypatch.setenv('OPSTRAIL_NO_CAPTURE', '0')
    home = tmp_path / 'synthetic'
    svc, metadata = module.seed(home, repo)
    try:
        assert svc.cfg.home == home
        assert not (tmp_path / 'must-not-read').exists()
        assert svc.day(metadata['date'])['episodes']
        assert svc.doc_detail(metadata['session_id'])['version'] == 2
        assert svc.list_recaps()
        assert svc.cfg.export_dir == home / 'exports'
        assert not (home / 'llm.json').exists()
        from starlette.testclient import TestClient
        with TestClient(module.snapshot_app(svc, 8765), base_url='http://127.0.0.1:8765') as client:
            page = client.get('/?snapshot_theme=dark')
            assert page.status_code == 200
            assert '/snapshot-theme/dark.js' in page.text
            assert "script-src 'self'" in page.headers['content-security-policy']
            PageParser().feed(page.text.replace('/snapshot-theme/dark.js', '/static/theme.js'))
            assert '"dark"' in client.get('/snapshot-theme/dark.js').text
            assert client.get('/snapshot-theme/invalid.js').status_code == 404
            assert client.get('/', headers={'host': 'foreign.example'}).status_code == 403
            assert client.post('/api/notes', json={'text': 'blocked'}).status_code == 403
        with pytest.raises(ValueError, match='must not exist'):
            module.seed(home, repo)
    finally:
        svc.store.close()
