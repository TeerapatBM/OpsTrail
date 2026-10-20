/* Run with node tests/web_editor_smoke.cjs; uses an installed Playwright, no downloads.
   UI-only fixtures: Python API/provider behavior is covered in test_web.py. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const vm = require('node:vm');
const { chromium } = require('playwright');
const staticDir = path.resolve(__dirname, '../src/opstrail/web/static');
const source = fs.readFileSync(path.join(staticDir, 'app.js'), 'utf8');

async function utilities() {
  const context = vm.createContext({ TextDecoder, Intl, fetch: null });
  vm.runInContext(source.slice(0, source.indexOf('const fail =')), context);
  const hunks = [{ op: 'equal', before: 'ติดตั้งระ', after: 'ติดตั้งระ' },
    { op: 'replace', before: 'บบ', after: 'เบียบ' },
    { op: 'insert', before: '', after: '<script>alert(1)</script>' }];
  context.hunks = hunks;
  assert.match(vm.runInContext('diffSide(hunks, "before")', context), /<del>ระบบ<\/del>/);
  assert(!vm.runInContext('diffSide(hunks, "after")', context).includes('<script>'));
  vm.runInContext('Intl = {}', context);
  assert.match(vm.runInContext('diffSide(hunks, "before")', context), /<del>บบ<\/del>/);
  assert(!vm.runInContext('diffSide(hunks, "after")', context).includes('<script>'));

  let cancelled = false, count = 0;
  const payload = Buffer.from('event: delta\r\ndata: {"event":"delta","text":"ไทย\\n"}\r\n\r\nevent: done\r\ndata: {"event":"done","version":3}\r\n\r\n');
  const reader = { async read() { return count < payload.length ? { value: payload.subarray(count, ++count), done: false } : { done: true }; },
    async cancel() { cancelled = true; }, releaseLock() {} };
  context.fetch = async () => ({ ok: true, headers: { get: () => 'text/event-stream' }, body: { getReader: () => reader } });
  const deltas = [];
  context.onDelta = (text) => deltas.push(text);
  const result = await vm.runInContext('streamAI("/test", {}, onDelta)', context);
  assert.equal(result.version, 3);
  assert.deepEqual(deltas, ['ไทย\n']);
  assert(cancelled);
  count = payload.length;
  await assert.rejects(vm.runInContext('streamAI("/test", {}, onDelta)', context), /การเชื่อมต่อขาด/);
  console.log('PASS utilities: Thai word boundaries, escaping/fallback, byte-split UTF-8/CRLF SSE, incomplete stream');
}

async function smoke() {
  let latest = 2, release, mode = 'ok', generations = 0;
  const drafts = { 1: '# คู่มือ\nติดตั้งระบบเก่า', 2: '# คู่มือ\nติดตั้งระบบใหม่<script>alert(1)</script>' };
  const factCheck = { ok: true, version: 3, checked: 0, todos: 0 };
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const json = (data) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(data)); };
    res.setHeader('content-security-policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:");
    if (url.pathname === '/api/status') return json({ llm: { ready: true }, capturing: false });
    if (url.pathname === '/api/templates') return json([{ name: 'sop', title: 'คู่มือ' }]);
    if (url.pathname === '/api/docs/1') {
      const version = Number(url.searchParams.get('version')) || latest;
      return json({ session_id: 1, template: 'sop', title: 'Smoke', status: 'draft', version, markdown: drafts[version], episodes: [],
        versions: Object.keys(drafts).map((v) => ({ version: +v, author: 'fixture', created_at: '2026-10-20T00:00:00Z' })) });
    }
    if (url.pathname === '/api/docs/1/diff') {
      const a = drafts[url.searchParams.get('from')], b = drafts[url.searchParams.get('to')];
      return json({ hunks: a === b ? [{ op: 'equal', before: a, after: b }] : [
        { op: 'equal', before: '# คู่มือ\nติดตั้งระบบ', after: '# คู่มือ\nติดตั้งระบบ' },
        { op: 'replace', before: a.slice('# คู่มือ\nติดตั้งระบบ'.length), after: b.slice('# คู่มือ\nติดตั้งระบบ'.length) }] });
    }
    if (url.pathname === '/api/docs/1/review') {
      assert.equal(req.headers['x-opstrail'], '1');
      return json({ version: latest, model: 'checker<script>', fact_check: { ...factCheck, version: latest },
        issues: [{ severity: 'warning', quote: '<script>alert(1)</script>', problem: '<img src=x onerror=alert(1)>', suggestion: 'ตรวจหลักฐาน' }] });
    }
    if (url.pathname === '/api/docs/1/generate') {
      assert.equal(url.searchParams.get('stream'), '1');
      assert.equal(req.headers['x-opstrail'], '1');
      generations++;
      res.writeHead(200, { 'content-type': 'text/event-stream' });
      const send = (event) => res.write('data: ' + JSON.stringify(event) + '\n\n');
      send({ event: 'delta', text: '# กำลังเขียนไทย' });
      release = () => {
        if (mode === 'error') send({ event: 'error', error: 'ทดสอบ provider error' });
        else {
          drafts[++latest] = '# กำลังเขียนไทย\n\nเสร็จแล้ว';
          send({ event: 'done', version: latest, markdown: drafts[latest], model: 'fixture', fact_check: factCheck });
        }
        res.end();
      };
      return;
    }
    const name = url.pathname === '/' ? 'index.html' : url.pathname.replace('/static/', '');
    if (!['index.html', 'app.js', 'app.css'].includes(name)) { res.writeHead(404); return res.end(); }
    res.setHeader('content-type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html');
    res.end(fs.readFileSync(path.join(staticDir, name)));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined });
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    await page.goto(`http://127.0.0.1:${server.address().port}/#/docs/1`);
    await page.locator('#md').waitFor();
    await page.locator('#diff-btn').click();
    await page.waitForFunction(() => document.querySelector('#diff-output ins'));
    assert.equal(await page.locator('#diff-output script').count(), 0);
    assert.match(await page.locator('#diff-output').textContent(), /<script>/);
    await page.locator('#diff-to').selectOption('1');
    await page.waitForFunction(() => !document.querySelector('#diff-output ins'));
    await page.locator('#diff-close').click();
    await page.locator('#review-btn').click();
    await page.waitForFunction(() => document.querySelector('#review-result li'));
    assert.equal(await page.locator('#review-result script, #review-result img').count(), 0);
    assert.match(await page.locator('#review-result').textContent(), /checker<script>/);
    assert.equal(await page.locator('#ver').inputValue(), '2');
    await page.locator('#ai').click();
    await page.waitForFunction(() => document.querySelector('#md').value === '# กำลังเขียนไทย');
    assert(await page.locator('#save').isDisabled());
    assert(await page.locator('#ver').isDisabled());
    await page.evaluate(() => { document.querySelector('#md').dispatchEvent(new KeyboardEvent('keydown', { key: 's', ctrlKey: true, bubbles: true })); location.hash = '#/docs'; });
    await page.waitForFunction(() => location.hash === '#/docs/1');
    assert.equal(generations, 1);
    release();
    await page.waitForFunction(() => !document.querySelector('#ai').disabled);
    assert.equal(await page.locator('#ver').inputValue(), '3');
    assert.match(await page.locator('#fc').textContent(), /v3/);
    const saved = await page.locator('#md').inputValue();
    mode = 'error';
    await page.locator('#ai').click();
    await page.waitForFunction(() => document.querySelector('#md').value === '# กำลังเขียนไทย');
    release();
    await page.waitForFunction(() => !document.querySelector('#ai').disabled);
    assert.equal(await page.locator('#md').inputValue(), saved);
    assert.equal(await page.locator('#ver').inputValue(), '3');
    // A blocked navigation during generation must not swallow the next navigation.
    await page.evaluate(() => { location.hash = '#/docs/1?smoke=1'; });
    await page.waitForFunction(() => state.hash === location.hash, undefined, { timeout: 2000 });
    await page.waitForFunction(() => document.querySelector('#md')?.value.includes('เสร็จแล้ว'));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.locator('#diff-btn').click();
    await page.waitForFunction(() => document.querySelector('#diff-output ins'));
    assert.deepEqual(errors, []);
    console.log('PASS Playwright: review escaping/version preservation, diff selection/escaping, live output before completion, locked actions/navigation, saved fact-check, error recovery, mobile/dark; no console errors');
  } finally {
    if (browser) await browser.close();
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
}

utilities().then(smoke).catch((e) => { console.error(e); process.exitCode = 1; });
