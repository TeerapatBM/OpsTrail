// Run with node --test tests/browser_extension.cjs; no browser profile or network.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../extension/background.js'), 'utf8');

function harness(session = {}) {
  let now = 10000;
  let nextId = 1;
  const timers = new Map();
  const sent = [];
  const listeners = {};
  const event = name => ({ addListener: fn => { listeners[name] = fn; } });
  const state = { tab: { id: 4, active: true, incognito: false, url: 'https://portal.azure.com/', title: 'Azure' },
    win: { id: 1, focused: true, incognito: false }, settings: { token: 'x'.repeat(43), port: 8765 } };
  let fetchImpl = async () => ({ ok: true });
  const context = vm.createContext({
    chrome: {
      tabs: { onActivated: event('activate'), onUpdated: event('update'), query: async () => [state.tab] },
      windows: { onFocusChanged: event('focus'), getLastFocused: async () => state.win },
      storage: { local: { get: async () => state.settings },
        session: { get: async () => session, set: async value => Object.assign(session, value) },
        onChanged: event('settings') }
    },
    Date: class extends Date { constructor(...args) { super(...(args.length ? args : [now])); }
      static now() { return now; } },
    setTimeout: (fn, delay) => { const id = nextId++; timers.set(id, { fn, due: now + delay }); return id; },
    clearTimeout: id => timers.delete(id),
    AbortSignal,
    fetch: async (url, options) => { sent.push({ url, ...options }); return fetchImpl(); }
  });
  vm.runInContext(source, context);
  return { state, sent, listeners, session,
    setFetch(fn) { fetchImpl = fn; },
    async advance(ms) {
      now += ms;
      for (const [id, timer] of [...timers]) {
        if (timer.due <= now) { timers.delete(id); await timer.fn(); }
      }
    }
  };
}

test('active URL capture, trailing debounce and worker restart throttle', async () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '../extension/manifest.json'), 'utf8'));
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.incognito, 'not_allowed');
  assert.deepEqual(manifest.host_permissions, ['http://127.0.0.1/*']);
  assert.equal(manifest.content_scripts, undefined);
  const h = harness();
  h.listeners.activate();
  await h.advance(200);
  assert.equal(h.sent.length, 1);
  assert.equal(h.sent[0].url, 'http://127.0.0.1:8765/api/ingest/browser');
  assert.equal(h.sent[0].headers['X-OpsTrail'], '1');
  assert.equal(h.sent[0].redirect, 'error');
  assert.equal(JSON.parse(h.sent[0].body).tab_id, 4);
  h.state.tab.url += '#blade/Latest';
  h.listeners.update(4, { url: h.state.tab.url }, h.state.tab);
  await h.advance(200);
  assert.equal(h.sent.length, 1);
  await h.advance(2800);
  assert.equal(h.sent.length, 2);
  assert.match(JSON.parse(h.sent[1].body).url, /Latest/);
  const restarted = harness({ lastAttempt: 10000 });
  restarted.listeners.activate();
  await restarted.advance(200);
  assert.equal(restarted.sent.length, 0);
  await restarted.advance(2800);
  assert.equal(restarted.sent.length, 1);
});

test('incognito, unsupported URL, unfocused and unpaired tabs never send', async () => {
  for (const change of [h => h.state.tab.incognito = true, h => h.state.win.incognito = true,
    h => h.state.win.focused = false, h => h.state.tab.url = 'file:///secret',
    h => h.state.settings.token = '']) {
    const h = harness(); change(h); h.listeners.activate(); await h.advance(200);
    assert.equal(h.sent.length, 0);
  }
  const h = harness();
  h.listeners.update(3, { url: 'https://inactive.example' }, { active: false });
  await h.advance(5000);
  assert.equal(h.sent.length, 0);
});

test('an update during a slow request is retained without concurrent sends', async () => {
  const h = harness();
  let resolve;
  h.setFetch(() => new Promise(r => { resolve = r; }));
  h.listeners.activate();
  const first = h.advance(200);
  await new Promise(setImmediate);
  assert.equal(h.sent.length, 1);
  h.state.tab.url += '#latest';
  h.listeners.activate();
  await h.advance(200);
  assert.equal(h.sent.length, 1);
  resolve({ ok: true });
  await first;
  h.setFetch(async () => { throw new Error('offline'); });
  await h.advance(3000);
  assert.equal(h.sent.length, 2);
  assert.match(JSON.parse(h.sent[1].body).url, /latest/);
  await h.advance(10000);
  assert.equal(h.sent.length, 2); // no replay/retry queue
});
