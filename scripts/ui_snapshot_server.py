"""Synthetic-only web server for ui-snapshots.ps1; never loads a user's home."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil


def seed(home: Path, repo: Path):
    # Require a new home, so even accidental invocation cannot reuse customer data.
    if home.exists():
        raise ValueError('Snapshot home must not exist')
    home.mkdir(parents=True)
    os.environ['OPSTRAIL_HOME'] = str(home)
    os.environ['OPSTRAIL_NO_CAPTURE'] = '1'
    from opstrail.config import load_config
    from opstrail.service import OpsTrail

    (home / 'config.toml').write_text(
        '[general]\ntimezone = "Asia/Bangkok"\nauthor = "Snapshot Engineer"\n'
        f'export_dir = "{(home / "exports").as_posix()}"\n'
        f'templates_dir = "{(repo / "templates").as_posix()}"\n'
        '[capture]\nshell_output = true\n'
        '[projects]\n"Lab / Splunk" = ["splunk", "forwarder"]\n', encoding='utf-8')
    svc = OpsTrail(load_config(home))
    dates = set()
    for fixture in sorted((repo / 'evals/days').glob('*.jsonl')):
        shutil.copy2(fixture, svc.cfg.inbox_dir / fixture.name)
        for line in fixture.read_text(encoding='utf-8').splitlines():
            if line.strip():
                dates.add(json.loads(line)['ts'][:10])
    if not dates:
        raise ValueError('No golden-day fixtures')
    svc.refresh()
    for date in sorted(dates):
        svc.daily_recap(date)
    date = min(dates)
    doc = svc.start_doc_session('sop', 'ตรวจสอบ Splunk Forwarder ในห้องทดสอบ', date=date)
    draft = '# ตรวจสอบ Splunk Forwarder\n\n## วัตถุประสงค์\nตรวจสอบสถานะจากหลักฐานที่บันทึกไว้ในห้องทดสอบ\n\n'
    draft += '## ขั้นตอน\n1. เปิด PowerShell\n2. ตรวจสอบ service และปลายทางที่ตั้งค่าไว้\n3. บันทึกผลการตรวจสอบ\n\n'
    draft += '## ผลที่คาดหวัง\n[TODO: ยืนยันผลจากแหล่งข้อมูลก่อนใช้งานจริง]\n'
    svc.save_draft(doc['session_id'], draft, 'Synthetic snapshot draft', 'snapshot')
    svc.save_draft(doc['session_id'], draft + '\n## หลักฐาน\nอ้างอิงงานและคำสั่งในแหล่งข้อมูลด้านล่าง\n',
                   'Add evidence section', 'snapshot')
    return svc, {'date': date, 'session_id': doc['session_id']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--ready', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    svc, metadata = seed(args.home.resolve(), Path(__file__).resolve().parents[1])
    import uvicorn
    args.ready.write_text(json.dumps(metadata), encoding='utf-8')
    try:
        uvicorn.run(snapshot_app(svc, args.port), host='127.0.0.1', port=args.port,
                    log_level='warning', log_config=None)
    finally:
        svc.store.close()


def snapshot_app(svc, port):
    """Set a deterministic preference under the real LocalOnly middleware."""
    from starlette.responses import HTMLResponse, Response
    from starlette.routing import Route
    from opstrail.web.app import create_app

    static = Path(__file__).resolve().parents[1] / 'src/opstrail/web/static'

    async def index(request):
        mode = request.query_params.get('snapshot_theme', 'light')
        mode = mode if mode in ('light', 'dark') else 'light'
        html = (static / 'index.html').read_text(encoding='utf-8')
        html = html.replace('<script src="/static/theme.js">',
                            f'<script src="/snapshot-theme/{mode}.js"></script><script src="/static/theme.js">')
        return HTMLResponse(html)

    async def preference(request):
        mode = request.path_params['mode']
        if mode not in ('light', 'dark'):
            return Response(status_code=404)
        return Response('try { localStorage.setItem("opstrail.theme", "' + mode + '"); } catch {}',
                        media_type='text/javascript', headers={'Cache-Control': 'no-store'})

    app = create_app(svc, port=port)
    app.router.routes.insert(0, Route('/', index))
    app.router.routes.insert(0, Route('/snapshot-theme/{mode}.js', preference))
    return app


if __name__ == '__main__':
    main()
