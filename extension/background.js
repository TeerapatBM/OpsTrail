"use strict";

// No content scripts, history reads, telemetry, or durable URL queue.
const INTERVAL = 3000;
let timer;
let busy = false;
let dirty = false;

function schedule(delay = 200) {
  dirty = true;
  clearTimeout(timer);
  timer = setTimeout(flush, delay);
}

async function flush() {
  timer = undefined;
  if (busy) return;
  busy = true;
  dirty = false;
  try {
    const { token, port = 8765 } = await chrome.storage.local.get(["token", "port"]);
    if (!token || !Number.isInteger(port) || port < 1 || port > 65535) return;
    // session storage survives service-worker suspension without retaining URLs on disk.
    const { lastAttempt = 0 } = await chrome.storage.session.get("lastAttempt");
    const remaining = INTERVAL - (Date.now() - lastAttempt);
    if (remaining > 0) { schedule(remaining); return; }
    const win = await chrome.windows.getLastFocused();
    if (!win.focused || win.incognito) return;
    const [tab] = await chrome.tabs.query({ active: true, windowId: win.id });
    if (!tab || tab.incognito || !tab.url || !/^https?:\/\//i.test(tab.url)) return;
    // Recheck focus after the asynchronous tab lookup.
    const current = await chrome.windows.getLastFocused();
    if (!current.focused || current.id !== win.id || current.incognito) return;
    const [active] = await chrome.tabs.query({ active: true, windowId: win.id });
    if (!active || active.id !== tab.id || active.url !== tab.url || active.incognito) return;
    await chrome.storage.session.set({ lastAttempt: Date.now() });
    await fetch(`http://127.0.0.1:${port}/api/ingest/browser`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-OpsTrail": "1", "X-OpsTrail-Browser-Token": token },
      body: JSON.stringify({ url: tab.url, title: tab.title || "", tab_id: tab.id,
        ts: new Date().toISOString(), incognito: false }),
      signal: AbortSignal.timeout(5000),
      redirect: "error",
      credentials: "omit"
    });
  } catch {
    // Server stopped, permission denied, or tab closed: drop capture without logging URLs/tokens.
  } finally {
    busy = false;
    if (dirty && !timer) schedule();
  }
}

function requestCapture() {
  schedule();
}
chrome.tabs.onActivated.addListener(requestCapture);
chrome.tabs.onUpdated.addListener((_id, changes, tab) => {
  if (tab.active && !tab.incognito && (changes.url || changes.title)) requestCapture();
});
chrome.windows.onFocusChanged.addListener(requestCapture);
chrome.storage.onChanged.addListener((_changes, area) => {
  if (area === "local") requestCapture();
});
