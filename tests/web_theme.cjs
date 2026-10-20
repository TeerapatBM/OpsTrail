/* Dependency-free tests of the real pre-paint theme controller. */
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = readFileSync(require('node:path').join(__dirname, '../src/opstrail/web/static/theme.js'), 'utf8');
for (const initial of ['auto', 'light', 'dark', 'invalid', null, 'denied']) {
  let saved = initial, listener, storageListener;
  const controls = [{ value: '' }, { value: '' }];
  const root = { dataset: {} };
  const media = { matches: false, addEventListener(type, fn) { listener = fn; } };
  const context = vm.createContext({
    document: { documentElement: root, querySelectorAll() { return controls; } },
    matchMedia: () => media,
    localStorage: {
      getItem() { if (initial === 'denied') throw Error('denied'); return saved; },
      setItem(key, value) { if (initial === 'denied') throw Error('denied'); assert.equal(key, 'opstrail.theme'); saved = value; }
    },
    window: { addEventListener(type, fn) { if (type === 'storage') storageListener = fn; } }
  });
  vm.runInContext(source, context);
  const expected = ['light', 'dark'].includes(initial) ? initial : 'auto';
  assert.equal(root.dataset.theme, expected === 'auto' ? 'light' : expected);
  media.matches = true; listener();
  assert.equal(root.dataset.theme, expected === 'auto' ? 'dark' : expected);
  vm.runInContext('theme.set("light")', context);
  assert.equal(root.dataset.theme, 'light');
  assert(controls.every((c) => c.value === 'light'));
  listener(); assert.equal(root.dataset.theme, 'light');
  vm.runInContext('theme.set("auto")', context);
  assert.equal(root.dataset.theme, 'dark');
  assert(controls.every((c) => c.value === 'auto'));
  storageListener({ key: 'opstrail.theme', newValue: 'light' });
  assert.equal(root.dataset.theme, 'light');
  storageListener({ key: 'opstrail.theme', newValue: null });
  assert.equal(root.dataset.theme, 'dark');
}
console.log('PASS theme: light/dark/auto, OS changes, invalid/denied storage, synchronized selectors, cross-tab changes');

// Keep the token contrast checks runnable even where the shared Python cannot launch.
const css = readFileSync(require('node:path').join(__dirname, '../src/opstrail/web/static/app.css'), 'utf8');
const luminance = (hex) => {
  const v = hex.slice(1).match(/../g).map((x) => parseInt(x, 16) / 255)
    .map((x) => x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4);
  return v[0] * .2126 + v[1] * .7152 + v[2] * .0722;
};
for (const mode of ['light', 'dark']) {
  const block = css.match(new RegExp(':root\\[data-theme="' + mode + '"\\]\\s*\\{([^}]+)'))[1];
  const tokens = Object.fromEntries([...block.matchAll(/--([\w-]+):\s*(#[\da-f]{6})/g)].map((m) => [m[1], m[2]]));
  const pairs = [];
  for (const surface of ['bg', 'panel', 'panel-2']) {
    pairs.push(['text', surface, 4.5], ['muted', surface, 4.5], ['border', surface, 3]);
  }
  pairs.push(['accent', 'accent-soft', 4.5], ['on-accent', 'accent', 4.5]);
  for (const status of ['ok', 'warn', 'bad']) pairs.push([status, status + '-soft', 4.5]);
  for (const [a, b, min] of pairs) {
    const light = [luminance(tokens[a]), luminance(tokens[b])].sort((a, b) => a - b);
    assert((light[1] + .05) / (light[0] + .05) >= min, mode + ': ' + a + '/' + b);
  }
}
console.log('PASS contrast: AA text/status/buttons and 3:1 control boundaries in both themes');
