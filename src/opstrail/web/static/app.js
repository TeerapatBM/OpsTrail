/* OpsTrail web UI — vanilla JS single-page app (no build step, no external requests). */
"use strict";

// ------------------------------------------------------------------ utils
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
const ACT_LABEL = { meeting: "ประชุม", chat: "แชท", email: "อีเมล", terminal: "Terminal", remote: "Remote", console: "Console",
  research: "ค้นข้อมูล", docs: "เอกสาร", code: "เขียนโค้ด", ai: "AI assistant", files: "ไฟล์", other: "อื่นๆ" };
const state = { status: null, llm: null, templates: null, dirty: false, hash: "", skipHash: false };

function pad(n) { return String(n).padStart(2, "0"); }
function isoDate(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
function today() { return isoDate(new Date()); }
function shiftDate(date, days) { const d = new Date(date + "T12:00:00"); d.setDate(d.getDate() + days); return isoDate(d); }
function thaiDate(date) {
  try {
    return new Intl.DateTimeFormat("th-TH-u-ca-gregory", { weekday: "long", day: "numeric", month: "long", year: "numeric" })
      .format(new Date(date + "T12:00:00"));
  } catch { return date; }
}
function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("th-TH-u-ca-gregory", { dateStyle: "medium", timeStyle: "short" });
}
function prettyKey(combo) {
  return String(combo || "").split("+").map((p) => p.replace(/[<>]/g, "")).map((p) => (p.length === 1 ? p.toUpperCase() : p.charAt(0).toUpperCase() + p.slice(1))).join("+");
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function hashParams() { const q = location.hash.split("?")[1] || ""; return new URLSearchParams(q); }

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) {
    init.method = opts.method || "POST";
    init.headers["content-type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  if (init.method !== "GET") init.headers["x-opstrail"] = "1";
  let res;
  try { res = await fetch(path, init); }
  catch { throw new Error("ติดต่อ OpsTrail ไม่ได้ — agent ยังทำงานอยู่ไหม?"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function toast(msg, err = false) {
  const el = document.createElement("div");
  el.className = "toast" + (err ? " err" : "");
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), err ? 7000 : 3500);
}
const fail = (e) => toast(e.message || String(e), true);

function busy(msg) {
  const el = document.createElement("div");
  el.className = "overlay";
  el.innerHTML = `<div class="box"><div class="spinner"></div><div>${esc(msg)}</div></div>`;
  document.body.appendChild(el);
  return () => el.remove();
}

function modal(inner, { ok = "ตกลง", cancel = "ยกเลิก", hideOk = false } = {}) {
  const dlg = $("#modal");
  const form = $("#modal-form");
  form.innerHTML = inner + `<div class="actions">
    <button class="btn" value="cancel" formnovalidate>${esc(cancel)}</button>
    ${hideOk ? "" : `<button class="btn primary" value="ok">${esc(ok)}</button>`}</div>`;
  return new Promise((resolve) => {
    const onClose = () => {
      dlg.removeEventListener("close", onClose);
      if (dlg.returnValue !== "ok") return resolve(null);
      const vals = {};
      for (const el of form.elements) if (el.name) vals[el.name] = el.type === "checkbox" ? el.checked : el.value;
      resolve(vals);
    };
    dlg.addEventListener("close", onClose);
    dlg.returnValue = "";
    dlg.showModal();
    const first = form.querySelector("input:not([type=hidden]),select,textarea");
    if (first) first.focus();
  });
}

function lightbox(src) {
  const el = document.createElement("div");
  el.className = "overlay lightbox";
  el.innerHTML = `<img src="${esc(src)}" alt="">`;
  el.addEventListener("click", () => el.remove());
  document.body.appendChild(el);
}

function setView(html) {
  const v = $("#view");
  v.innerHTML = html;
  v.focus({ preventScroll: true });
  window.scrollTo(0, 0);
  return v;
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; }
  catch {
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    const ok = document.execCommand("copy"); ta.remove(); return ok;
  }
}

// ------------------------------------------------------------- markdown
function safeUrl(u) { return /^(https?:|mailto:|#|\/)/i.test(u); }
function imgTag(alt, url) {
  const m = /^shot:\/\/(\d+)$/.exec(url);
  if (m) return `<img src="/api/shots/${m[1]}" alt="${alt}" data-zoom="1">`;
  return `<span class="badge">[รูป: ${alt || url}]</span>`;
}
function inlineMd(text) {
  let s = esc(text);
  const codes = [];
  s = s.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, u) => imgTag(alt, u));
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, t, u) => (safeUrl(u) ? `<a href="${u}" target="_blank" rel="noopener noreferrer">${t}</a>` : t));
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/__([^_]+)__/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>");
  s = s.replace(/\[TODO[^\]]*\]/g, (m) => `<span class="todo">${m}</span>`);
  s = s.replace(/\[REDACTED\]/g, '<span class="redacted">[REDACTED]</span>');
  s = s.replace(/\u0000(\d+)\u0000/g, (_, n) => `<code>${codes[+n]}</code>`);
  return s;
}
function splitRow(line) {
  let l = line.trim();
  if (l.startsWith("|")) l = l.slice(1);
  if (l.endsWith("|")) l = l.slice(0, -1);
  return l.split(/(?<!\\)\|/).map((c) => c.trim());
}
function renderMd(src) {
  const lines = String(src || "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let para = [];
  const flush = () => { if (para.length) { out.push(`<p>${inlineMd(para.join(" "))}</p>`); para = []; } };
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const fence = /^\s*(```+|~~~+)(.*)$/.exec(line);
    if (fence) {
      flush();
      const code = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) code.push(lines[i++]);
      i++;
      out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
      continue;
    }
    const hm = /^(#{1,6})\s+(.*)$/.exec(line);
    if (hm) { flush(); const n = hm[1].length; out.push(`<h${n}>${inlineMd(hm[2].replace(/#+\s*$/, ""))}</h${n}>`); i++; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); out.push("<hr>"); i++; continue; }
    if (line.trim().startsWith("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      flush();
      const head = splitRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(splitRow(lines[i++]));
      out.push(`<table><thead><tr>${head.map((c) => `<th>${inlineMd(c)}</th>`).join("")}</tr></thead><tbody>${rows
        .map((r) => `<tr>${head.map((_, k) => `<td>${inlineMd(r[k] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    if (/^\s*>/.test(line)) {
      flush();
      const q = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${inlineMd(q.join(" "))}</blockquote>`);
      continue;
    }
    if (/^(\s*)([-*+]|\d+[.)])\s+/.test(line)) {
      flush();
      const items = [];
      while (i < lines.length) {
        const lm = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(lines[i]);
        if (!lm) break;
        let text = lm[3].replace(/^\[ \]\s*/, "☐ ").replace(/^\[[xX]\]\s*/, "☑ ");
        items.push({ indent: lm[1].replace(/\t/g, "  ").length, ordered: /\d/.test(lm[2]), text });
        i++;
      }
      let html = "";
      const stack = [];
      for (const it of items) {
        while (stack.length && it.indent < stack[stack.length - 1].indent) html += `</li></${stack.pop().tag}>`;
        const top = stack[stack.length - 1];
        if (!top || it.indent > top.indent) { const tag = it.ordered ? "ol" : "ul"; html += `<${tag}><li>`; stack.push({ indent: it.indent, tag }); }
        else html += "</li><li>";
        html += inlineMd(it.text);
      }
      while (stack.length) html += `</li></${stack.pop().tag}>`;
      out.push(html);
      continue;
    }
    if (!line.trim()) { flush(); i++; continue; }
    para.push(line.trim());
    i++;
  }
  flush();
  return out.join("\n");
}

// --------------------------------------------------------------- sidebar
async function refreshStatus() {
  try {
    const st = await api("/api/status");
    state.status = st;
    state.llm = st.llm;
    const agent = st.agent_running
      ? `<span class="dot ok"></span>agent ทำงานอยู่`
      : `<span class="dot bad"></span>agent ไม่ทำงาน`;
    $("#agent-status").innerHTML = `${agent}<br><span class="${st.capturing ? "" : "muted"}">${st.capturing ? "● กำลังบันทึก" : "⏸ หยุดบันทึกชั่วคราว"}</span>`;
    const btn = $("#capture-toggle");
    btn.textContent = st.capturing ? "หยุดบันทึกชั่วคราว" : "บันทึกต่อ";
    btn.className = "btn small" + (st.capturing ? "" : " primary");
  } catch (e) {
    $("#agent-status").innerHTML = `<span class="dot bad"></span>${esc(e.message)}`;
  }
}
$("#capture-toggle").addEventListener("click", async () => {
  try {
    await api("/api/capture", { body: { paused: !!(state.status && state.status.capturing) } });
    await refreshStatus();
  } catch (e) { fail(e); }
});

async function templates() {
  if (!state.templates) state.templates = await api("/api/templates");
  return state.templates;
}

// -------------------------------------------------------------- day page
async function renderDay(date) {
  const params = hashParams();
  if (!state.llm) await refreshStatus();
  setView(`<div class="empty">กำลังโหลด…</div>`);
  let data;
  try { data = await api(`/api/day/${date}`); } catch (e) { return setView(`<div class="banner warn">${esc(e.message)}</div>`); }
  const s = data.summary;
  const recapBtn = data.recap
    ? `<a class="btn" href="#/docs/${data.recap.session_id}">เปิด Daily worklog (v${data.recap.version})</a>`
    : "";
  const v = setView(`
    <div class="page-head">
      <div class="row">
        <a class="btn small" href="#/day/${shiftDate(date, -1)}" title="วันก่อน">◀</a>
        <div><h1>${esc(thaiDate(date))}</h1><div class="muted small">${date === today() ? "วันนี้" : date}</div></div>
        <a class="btn small" href="#/day/${shiftDate(date, 1)}" title="วันถัดไป">▶</a>
        <input type="date" id="pick" value="${date}">
      </div>
      <div class="row">
        ${data.episodes.length && state.llm && state.llm.ready ? `<button class="btn" id="ai-titles" title="ให้ AI ตั้งชื่องานที่ยังเป็นชื่ออัตโนมัติ">✨ ตั้งชื่องานด้วย AI</button>` : ""}
        ${recapBtn}
        <button class="btn primary" id="mk-recap">${data.recap ? "อัปเดต" : "สร้าง"} Daily worklog</button>
      </div>
    </div>
    ${params.get("review") ? `<div class="banner">ทบทวนงานของวันนี้: แก้ชื่องานให้อ่านเข้าใจ และเติมโน้ต (ผลลัพธ์/เหตุผล) แล้วกด <b>อัปเดต Daily worklog</b></div>` : ""}
    <div class="stats">
      <div class="card stat"><div class="v">${esc(s.active)}</div><div class="k">เวลาทำงาน (active)</div></div>
      <div class="card stat"><div class="v">${s.work_items}</div><div class="k">งาน (episodes)</div></div>
      <div class="card stat"><div class="v">${s.commands}</div><div class="k">คำสั่งที่รัน</div></div>
      <div class="card stat"><div class="v">${s.notes}</div><div class="k">โน้ต</div></div>
      <div class="card stat"><div class="v">${s.screenshots}</div><div class="k">รูปหน้าจอ</div></div>
    </div>
    <div class="row" style="margin-bottom:10px">
      <button class="btn small primary" data-tab="eps">งาน</button>
      <button class="btn small" data-tab="tl">Timeline ดิบ</button>
      <span class="grow"></span>
      <button class="btn small" id="add-note">+ โน้ตของวันนี้</button>
    </div>
    <div class="card selbar hidden" id="selbar">
      <b id="selcount"></b>
      <button class="btn small primary" id="sel-doc">สร้างเอกสารจากงานที่เลือก</button>
      <button class="btn small" id="sel-merge">รวมเป็นงานเดียว</button>
      <button class="btn small ghost" id="sel-clear">ล้าง</button>
    </div>
    <div id="eps" class="episodes"></div>
    <div id="tl" class="hidden"></div>`);

  $("#pick", v).addEventListener("change", (e) => { if (e.target.value) location.hash = `#/day/${e.target.value}`; });
  $("#mk-recap", v).addEventListener("click", async () => {
    const done = busy("กำลังสร้าง Daily worklog…");
    try { const r = await api(`/api/day/${date}/recap`, { body: {} }); location.hash = `#/docs/${r.session_id}`; }
    catch (e) { fail(e); } finally { done(); }
  });
  $("#add-note", v).addEventListener("click", () => addNote(null, () => renderDay(date)));
  const aiBtn = $("#ai-titles", v);
  if (aiBtn) aiBtn.addEventListener("click", async () => {
    const done = busy("AI กำลังตั้งชื่องาน…");
    try { const r = await api(`/api/day/${date}/ai-titles`, { body: {} }); toast(`ตั้งชื่อใหม่ ${r.renamed} งาน`); renderDay(date); }
    catch (e) { fail(e); } finally { done(); }
  });
  $$("[data-tab]", v).forEach((b) => b.addEventListener("click", () => {
    $$("[data-tab]", v).forEach((x) => x.classList.toggle("primary", x === b));
    $("#eps", v).classList.toggle("hidden", b.dataset.tab !== "eps");
    $("#tl", v).classList.toggle("hidden", b.dataset.tab !== "tl");
    if (b.dataset.tab === "tl") renderTimeline($("#tl", v), date);
  }));

  const list = $("#eps", v);
  if (!data.episodes.length) {
    list.innerHTML = `<div class="card empty">ยังไม่มีงานที่บันทึกไว้ในวันนี้<br><span class="small">ตรวจว่า agent ทำงานอยู่ (แถบซ้ายล่าง) และ PowerShell เปิดใหม่หลังติดตั้ง</span></div>`;
  }
  for (const ep of data.episodes) list.appendChild(episodeCard(ep, date));

  const selected = () => $$(".ep-sel:checked", list).map((c) => +c.value);
  const updateSel = () => {
    const ids = selected();
    $("#selbar", v).classList.toggle("hidden", !ids.length);
    $("#selcount", v).textContent = `เลือก ${ids.length} งาน`;
  };
  list.addEventListener("change", (e) => { if (e.target.classList.contains("ep-sel")) updateSel(); });
  $("#sel-clear", v).addEventListener("click", () => { $$(".ep-sel", list).forEach((c) => (c.checked = false)); updateSel(); });
  $("#sel-merge", v).addEventListener("click", async () => {
    const ids = selected();
    if (ids.length < 2) return toast("เลือกอย่างน้อย 2 งาน");
    const r = await modal(`<h2>รวม ${ids.length} งานเป็นงานเดียว</h2>
      <label class="field">ชื่องานใหม่<input name="title" placeholder="เว้นว่าง = ใช้ชื่ออัตโนมัติ"></label>`, { ok: "รวมงาน" });
    if (!r) return;
    try { await api("/api/episodes/merge", { body: { ids, title: r.title } }); toast("รวมงานแล้ว"); renderDay(date); } catch (e) { fail(e); }
  });
  $("#sel-doc", v).addEventListener("click", async () => {
    const ids = selected();
    const first = data.episodes.find((e) => e.id === ids[0]);
    await newDocDialog({ episode_ids: ids, title: first ? first.title : "" });
  });
}

function episodeCard(ep, date) {
  const el = document.createElement("div");
  el.className = "card ep";
  const tags = (ep.tags || []).filter((t) => t !== "meeting").map((t) => `<span class="badge accent">${esc(t)}</span>`).join(" ");
  const acts = ep.activities || {};
  const topAct = Object.keys(acts).sort((a, b) => acts[b] - acts[a])[0];
  const actBadge = ep.origin === "meeting" ? `<span class="badge warn">ประชุม</span>`
    : topAct ? `<span class="badge">${esc(ACT_LABEL[topAct] || topAct)}</span>` : "";
  const meta = [
    ep.apps && ep.apps.length ? esc(ep.apps.join(", ")) : "",
    ep.targets && ep.targets.length ? `→ ${esc(ep.targets.join(", "))}` : "",
    `${ep.commands} คำสั่ง${ep.failed_commands ? ` <span class="badge bad">fail ${ep.failed_commands}</span>` : ""}`,
    ep.notes ? `${ep.notes} โน้ต` : "",
    ep.screenshots ? `${ep.screenshots} รูป` : "",
    ep.open_task ? `<span class="badge warn">กำลังทำ</span>` : "",
    ep.origin === "manual" ? `<span class="badge">กำหนดเอง</span>` : "",
  ].filter(Boolean).join(" · ");
  el.innerHTML = `
    <div class="ep-head">
      <input type="checkbox" class="ep-sel" value="${ep.id}" aria-label="เลือกงาน">
      <div class="ep-time">${esc(ep.time)}<span class="muted">${esc(ep.active)}</span></div>
      <div>
        <input class="ep-title" value="${esc(ep.title)}" title="คลิกเพื่อแก้ชื่องาน">
        <div class="ep-meta">${actBadge} ${tags} ${meta}${ep.chats && ep.chats.length ? ` · คุยกับ ${esc(ep.chats.join(", "))}` : ""}</div>
      </div>
      <div class="row">
        <button class="btn small" data-act="note">+ โน้ต</button>
        <button class="btn small" data-act="more">รายละเอียด</button>
      </div>
    </div>
    <div class="ep-detail hidden"></div>`;
  const titleInput = $(".ep-title", el);
  titleInput.addEventListener("keydown", (e) => { if (e.key === "Enter") titleInput.blur(); });
  titleInput.addEventListener("change", async () => {
    try { await api(`/api/episodes/${ep.id}`, { body: { title: titleInput.value } }); toast("บันทึกชื่องานแล้ว"); }
    catch (e) { fail(e); }
  });
  $('[data-act="note"]', el).addEventListener("click", () => addNote(ep.id, () => renderDay(date)));
  $('[data-act="more"]', el).addEventListener("click", async (e) => {
    const box = $(".ep-detail", el);
    if (!box.classList.contains("hidden")) { box.classList.add("hidden"); e.target.textContent = "รายละเอียด"; return; }
    e.target.textContent = "ซ่อน";
    box.classList.remove("hidden");
    box.innerHTML = `<div class="muted">กำลังโหลด…</div>`;
    try { renderEpisodeDetail(box, await api(`/api/episodes/${ep.id}`), date); } catch (err) { box.innerHTML = esc(err.message); }
  });
  return el;
}

function renderEpisodeDetail(box, d, date) {
  const notes = d.events.filter((e) => e.type === "note" || e.type === "task");
  const cmds = d.events.filter((e) => e.type === "shell" || e.type === "ai");
  const shots = d.events.filter((e) => e.type === "screenshot");
  box.innerHTML = `
    <div>
      <h4>โน้ต / การตัดสินใจ</h4>
      ${notes.length ? `<ul class="notes">${notes.map((n) => `<li><span class="muted">${esc(n.time.slice(0, 5))}</span> ${esc(n.text)}</li>`).join("")}</ul>` : `<div class="muted small">ยังไม่มีโน้ต — เติม "ทำไม" ไว้ เอกสารจะดีขึ้นมาก</div>`}
      <h4 style="margin-top:12px">หน้าต่าง/หน้าเว็บที่ใช้</h4>
      ${d.windows.length ? `<ul class="notes small">${d.windows.map((w) => `<li><span class="muted">${esc(w.focus)}</span> ${esc(w.window)}</li>`).join("")}</ul>` : `<div class="muted small">-</div>`}
      <h4 style="margin-top:12px">แท็ก</h4>
      <div class="row"><input id="tags-${d.id}" value="${esc((d.tags || []).join(", "))}" placeholder="เช่น Splunk, ลูกค้า X"><button class="btn small" data-act="tags">บันทึกแท็ก</button></div>
    </div>
    <div>
      <h4>คำสั่ง (${cmds.length})</h4>
      ${cmds.length ? `<div class="cmds">${cmds.map((c) => `<div class="${c.ok === false ? "fail" : ""}"><span class="t">${esc(c.time.slice(0, 5))}</span>${esc(c.text)}${c.ok === false ? "  ✗" : ""}</div>`).join("")}</div>` : `<div class="muted small">ไม่มีคำสั่ง</div>`}
      ${shots.length ? `<h4 style="margin-top:12px">รูปหน้าจอ</h4><div class="shots">${shots.map((s) => `<img src="/api/shots/${s.id}" alt="${esc(s.text)}" title="${esc(s.text)} (shot://${s.id})">`).join("")}</div>` : ""}
    </div>`;
  $$(".shots img", box).forEach((img) => img.addEventListener("click", () => lightbox(img.src)));
  $('[data-act="tags"]', box).addEventListener("click", async () => {
    try { await api(`/api/episodes/${d.id}`, { body: { tags: $(`#tags-${d.id}`, box).value } }); toast("บันทึกแท็กแล้ว"); renderDay(date); }
    catch (e) { fail(e); }
  });
}

async function addNote(episodeId, after) {
  const r = await modal(`<h2>${episodeId ? "เพิ่มโน้ตให้งานนี้" : "เพิ่มโน้ต"}</h2>
    <label class="field">ทำอะไร / ทำไม / ผลเป็นยังไง<textarea name="text" required style="min-height:110px;font-family:var(--font);font-size:14px"></textarea></label>`, { ok: "บันทึก" });
  if (!r || !r.text.trim()) return;
  try { await api("/api/notes", { body: { text: r.text, episode_id: episodeId } }); toast("บันทึกโน้ตแล้ว"); if (after) after(); }
  catch (e) { fail(e); }
}

async function renderTimeline(box, date) {
  box.innerHTML = `<div class="muted">กำลังโหลด…</div>`;
  try {
    const tl = await api(`/api/timeline?date=${date}`);
    if (!tl.events.length) { box.innerHTML = `<div class="card empty">ไม่มีกิจกรรม</div>`; return; }
    box.innerHTML = `<div class="card"><table class="list"><thead><tr><th>เวลา</th><th>ประเภท</th><th>รายละเอียด</th><th>งาน</th></tr></thead><tbody>
      ${tl.events.map((e) => `<tr><td class="mono">${esc(e.time)}</td><td><span class="badge">${esc(e.type)}</span></td>
        <td class="mono ${e.ok === false ? "fail" : ""}">${esc(e.text)}${e.dur ? ` <span class="muted">(${esc(e.dur)})</span>` : ""}</td>
        <td>${e.episode_id ? "#" + e.episode_id : ""}</td></tr>`).join("")}
      </tbody></table></div>
      ${tl.total_events > tl.shown ? `<div class="muted small">แสดง ${tl.shown} จาก ${tl.total_events} รายการล่าสุด</div>` : ""}`;
  } catch (e) { box.innerHTML = esc(e.message); }
}

// ----------------------------------------------------------- documents
async function newDocDialog(preset = {}) {
  const tpls = await templates();
  const llmReady = state.llm && state.llm.ready;
  const fromEpisodes = preset.episode_ids && preset.episode_ids.length;
  const r = await modal(`<h2>สร้างเอกสารใหม่</h2>
    <label class="field">ประเภทเอกสาร<select name="template">${tpls
      .filter((t) => t.name !== "daily-worklog" || !fromEpisodes)
      .map((t) => `<option value="${esc(t.name)}">${esc(t.title)}</option>`).join("")}</select></label>
    <label class="field">ชื่อเอกสาร<input name="title" required value="${esc(preset.title || "")}"></label>
    ${fromEpisodes ? `<div class="muted small">แหล่งข้อมูล: ${preset.episode_ids.length} งานที่เลือก (#${preset.episode_ids.join(", #")})</div>` : `
      <div class="grid2"><label class="field">งานตั้งแต่วันที่<input type="date" name="date" required value="${today()}"></label>
      <label class="field">ถึงวันที่ (ไม่บังคับ)<input type="date" name="date_to"></label></div>`}
    <label class="row small"><input type="checkbox" name="generate" ${llmReady ? "checked" : "disabled"}>
      ให้ AI เขียน draft แรกทันที ${llmReady ? "" : '<span class="muted">(ตั้งค่า AI ในหน้า "ตั้งค่า" ก่อน — หรือใช้ Copy prompt ในหน้าเอกสาร)</span>'}</label>`, { ok: "สร้างเอกสาร" });
  if (!r) return;
  try {
    const body = { template: r.template, title: r.title };
    if (fromEpisodes) body.episode_ids = preset.episode_ids; else { body.date = r.date; body.date_to = r.date_to; }
    const res = await api("/api/docs", { body });
    location.hash = `#/docs/${res.session_id}${r.generate ? "?generate=1" : ""}`;
  } catch (e) { fail(e); }
}

async function renderDocs() {
  setView(`<div class="empty">กำลังโหลด…</div>`);
  let docs, tpls;
  try { [docs, tpls] = await Promise.all([api("/api/docs"), templates()]); } catch (e) { return setView(esc(e.message)); }
  const tplTitle = Object.fromEntries(tpls.map((t) => [t.name, t.title]));
  const v = setView(`
    <div class="page-head"><h1>เอกสาร</h1>
      <div class="row">
        <select id="f-tpl"><option value="">ทุกประเภท</option>${tpls.map((t) => `<option value="${esc(t.name)}">${esc(t.title)}</option>`).join("")}</select>
        <select id="f-status"><option value="">ทุกสถานะ</option><option>draft</option><option>review</option><option>final</option><option>archived</option></select>
        <button class="btn primary" id="new-doc">+ เอกสารใหม่</button>
      </div></div>
    <div class="card"><table class="list"><thead><tr><th>ชื่อเอกสาร</th><th>ประเภท</th><th>สถานะ</th><th>เวอร์ชัน</th><th>แก้ไขล่าสุด</th></tr></thead><tbody id="rows"></tbody></table></div>
    <p class="muted small">เคล็ดลับ: ไปที่หน้า "วันนี้ / งาน" แล้วติ๊กเลือกงานที่เกี่ยวข้อง → "สร้างเอกสารจากงานที่เลือก" จะได้ข้อมูลตรงที่สุด</p>`);
  const draw = () => {
    const ft = $("#f-tpl", v).value, fs = $("#f-status", v).value;
    const rows = docs.filter((d) => (!ft || d.template === ft) && (!fs || d.status === fs));
    $("#rows", v).innerHTML = rows.length ? rows.map((d) => `<tr>
      <td><a href="#/docs/${d.session_id}">${esc(d.title)}</a></td>
      <td>${esc(tplTitle[d.template] || d.template)}</td>
      <td>${statusBadge(d.status)}</td><td>v${d.latest_version}</td><td class="muted">${esc(fmtTime(d.updated_at))}</td></tr>`).join("")
      : `<tr><td colspan="5" class="empty">ยังไม่มีเอกสาร</td></tr>`;
  };
  $("#f-tpl", v).addEventListener("change", draw);
  $("#f-status", v).addEventListener("change", draw);
  $("#new-doc", v).addEventListener("click", () => newDocDialog());
  draw();
}

function statusBadge(s) {
  const cls = { draft: "", review: "warn", final: "ok", archived: "" }[s] || "";
  const th = { draft: "ร่าง", review: "รอตรวจ", final: "เสร็จสมบูรณ์", archived: "เก็บถาวร" }[s] || s;
  return `<span class="badge ${cls}">${esc(th)}</span>`;
}

async function renderDoc(id) {
  const params = hashParams();
  setView(`<div class="empty">กำลังโหลด…</div>`);
  let d, tpls;
  try { [d, tpls] = await Promise.all([api(`/api/docs/${id}`), templates()]); } catch (e) { return setView(`<div class="banner warn">${esc(e.message)}</div>`); }
  await refreshStatus();
  const tpl = tpls.find((t) => t.name === d.template);
  const llmReady = state.llm && state.llm.ready;
  const v = setView(`
    <div class="doc-head">
      <a class="btn small" href="#/docs">←</a>
      <input class="doc-title" id="title" value="${esc(d.title)}">
      <span class="badge accent">${esc(tpl ? tpl.title : d.template)}</span>
      <select id="status">${["draft", "review", "final", "archived"].map((s) => `<option value="${s}" ${s === d.status ? "selected" : ""}>${s}</option>`).join("")}</select>
      <select id="ver"></select>
    </div>
    <div class="card toolbar">
      <input class="ai-instr" id="instr" placeholder="คำสั่งเพิ่มเติมถึง AI (ไม่บังคับ) เช่น “สั้นลง เน้นขั้นตอน”, “เพิ่มส่วน rollback”">
      <button class="btn primary" id="ai">✨ ${d.version ? "ให้ AI ปรับ" : "ให้ AI เขียน"}</button>
      <button class="btn" id="copy">Copy prompt</button>
      <button class="btn" id="paste">Paste ผลลัพธ์</button>
      <span class="sep"></span>
      <button class="btn" id="save">บันทึก (Ctrl+S)</button>
      <button class="btn" id="dl-docx">⬇ .docx</button>
      <button class="btn" id="dl-md">⬇ .md</button>
      <button class="btn" id="add-src">+ เพิ่มงาน</button>
      <button class="btn" id="fc-btn" title="หา IP / version / hostname ในเอกสารที่ไม่มีในข้อมูลที่บันทึก">ตรวจข้อเท็จจริง</button>
    </div>
    <div id="fc"></div>
    ${llmReady ? "" : `<div class="banner warn small">ยังไม่ได้ตั้งค่า AI — ไปที่ <a href="#/settings">ตั้งค่า</a> เพื่อใช้ปุ่ม “ให้ AI เขียน” หรือกด <b>Copy prompt</b> ไปวางใน ChatGPT/Claude แล้วกด <b>Paste ผลลัพธ์</b></div>`}
    <div id="verinfo" class="muted small" style="margin-bottom:6px"></div>
    <div class="tabs"><button class="btn small primary" data-pane="edit">แก้ไข</button><button class="btn small" data-pane="preview">ตัวอย่าง</button></div>
    <div class="panes show-edit" id="panes">
      <div class="editor-wrap"><textarea class="editor" id="md" spellcheck="false" placeholder="ยังไม่มีเนื้อหา — กด “ให้ AI เขียน” หรือพิมพ์เอง"></textarea></div>
      <div class="card preview md" id="preview"></div>
    </div>
    <div class="card pad sources"><h2>แหล่งข้อมูลของเอกสารนี้</h2><div id="srcs"></div></div>`);

  const ta = $("#md", v), pv = $("#preview", v);
  const draw = () => { pv.innerHTML = renderMd(ta.value) || `<div class="muted">ตัวอย่างจะแสดงที่นี่</div>`; };
  const redraw = debounce(draw, 150);
  pv.addEventListener("click", (e) => { if (e.target.dataset.zoom) lightbox(e.target.src); });
  let loaded = d;
  const showVersion = (doc) => {
    loaded = doc;
    ta.value = doc.markdown || "";
    state.dirty = false;
    draw();
    $("#ver", v).innerHTML = doc.versions.length
      ? doc.versions.slice().reverse().map((x) => `<option value="${x.version}" ${x.version === doc.version ? "selected" : ""}>v${x.version} · ${esc(x.author || "")} · ${esc(fmtTime(x.created_at))}</option>`).join("")
      : `<option value="0">ยังไม่มีเวอร์ชัน</option>`;
    const latest = doc.versions.length ? doc.versions[doc.versions.length - 1].version : 0;
    const cur = doc.versions.find((x) => x.version === doc.version);
    $("#verinfo", v).innerHTML = doc.version && doc.version !== latest
      ? `<span class="badge warn">กำลังดู v${doc.version} (ไม่ใช่ล่าสุด)</span> กด “บันทึก” เพื่อใช้เวอร์ชันนี้เป็นเวอร์ชันใหม่`
      : cur ? `v${cur.version}${cur.change_note ? " — " + esc(cur.change_note) : ""}` : "";
    $("#ai", v).textContent = doc.versions.length ? "✨ ให้ AI ปรับ" : "✨ ให้ AI เขียน";
    $("#srcs", v).innerHTML = doc.episodes.length
      ? `<table class="list"><tbody>${doc.episodes.map((e) => `<tr><td class="muted">${esc(e.date)} ${esc(e.time)}</td><td><a href="#/day/${esc(e.date)}">${esc(e.title)}</a></td><td class="muted">${e.commands} คำสั่ง · ${e.notes} โน้ต · ${e.screenshots} รูป</td></tr>`).join("")}</tbody></table>`
      : `<div class="muted">ยังไม่มีงานในแหล่งข้อมูล — กด “+ เพิ่มงาน”</div>`;
  };
  showVersion(d);
  ta.addEventListener("input", () => { state.dirty = true; redraw(); });

  const reload = async (version) => showVersion(await api(`/api/docs/${id}${version ? `?version=${version}` : ""}`));
  const save = async (note) => {
    const r = await api(`/api/docs/${id}/save`, { body: { markdown: ta.value, change_note: note || "" } });
    state.dirty = false;
    toast(`บันทึกเป็น v${r.version} แล้ว`);
    await reload();
  };
  const ensureSaved = async () => {
    if (!state.dirty) return true;
    if (!confirm("มีการแก้ไขที่ยังไม่บันทึก — บันทึกก่อนไหม?")) return false;
    await save("แก้ไขเอง");
    return true;
  };

  $("#title", v).addEventListener("change", async (e) => {
    try { await api(`/api/docs/${id}/meta`, { body: { title: e.target.value } }); toast("เปลี่ยนชื่อแล้ว"); } catch (err) { fail(err); }
  });
  $("#status", v).addEventListener("change", async (e) => {
    try { await api(`/api/docs/${id}/meta`, { body: { status: e.target.value } }); toast("อัปเดตสถานะแล้ว"); } catch (err) { fail(err); }
  });
  $("#ver", v).addEventListener("change", async (e) => {
    if (state.dirty && !confirm("ทิ้งการแก้ไขที่ยังไม่บันทึก?")) { e.target.value = loaded.version; return; }
    try { await reload(+e.target.value); } catch (err) { fail(err); }
  });
  $("#save", v).addEventListener("click", async () => {
    if (!ta.value.trim()) return toast("ยังไม่มีเนื้อหา");
    const r = await modal(`<h2>บันทึกเวอร์ชันใหม่</h2><label class="field">บันทึกการเปลี่ยนแปลง (ไม่บังคับ)<input name="note" placeholder="เช่น แก้ IP, เติมขั้นตอน rollback"></label>`, { ok: "บันทึก" });
    if (!r) return;
    try { await save(r.note); } catch (e) { fail(e); }
  });
  ta.addEventListener("keydown", async (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      if (ta.value.trim()) { try { await save("แก้ไขเอง"); } catch (err) { fail(err); } }
    }
  });
  const showFactCheck = (fc) => {
    const box = $("#fc", v);
    if (!fc) { box.innerHTML = ""; return; }
    if (fc.ok) {
      box.innerHTML = `<div class="banner small">✓ ตรวจข้อเท็จจริง v${fc.version}: ค่าทั้งหมด ${fc.checked} รายการ (IP/version/hostname/port) พบในข้อมูลที่บันทึก · TODO ${fc.todos} จุด</div>`;
    } else {
      const kinds = { ip: "IP", version: "version", host: "hostname", port: "port" };
      box.innerHTML = `<div class="banner warn small"><b>ตรวจข้อเท็จจริง v${fc.version}: พบ ${fc.unsupported.length} ค่าที่ไม่มีในข้อมูลที่บันทึก</b> — อาจเป็นข้อมูลที่ AI เดา ตรวจก่อนส่ง:
        ${fc.unsupported.map((u) => `<code>${esc(u.value)}</code> <span class="muted">(${kinds[u.kind] || u.kind})</span>`).join(", ")} · TODO ${fc.todos} จุด</div>`;
    }
  };
  $("#fc-btn", v).addEventListener("click", async () => {
    try { if (!(await ensureSaved())) return; showFactCheck(await api(`/api/docs/${id}/factcheck?version=${loaded.version || ""}`)); }
    catch (e) { fail(e); }
  });
  const runAI = async () => {
    if (!(state.llm && state.llm.ready)) {
      const r = await modal(`<h2>ยังไม่ได้ตั้งค่า AI</h2><p>ไปที่หน้า <b>ตั้งค่า</b> เพื่อใส่ Claude API / OpenAI / Azure OpenAI key
        หรือใช้ <b>Copy prompt</b> แล้วไปวางใน ChatGPT หรือ Claude บนเว็บ จากนั้นกด <b>Paste ผลลัพธ์</b></p>`, { ok: "ไปหน้าตั้งค่า" });
      if (r) location.hash = "#/settings";
      return;
    }
    try { if (!(await ensureSaved())) return; } catch (e) { return fail(e); }
    const done = busy("AI กำลังเขียนเอกสาร… (ปกติ 20–120 วินาที)");
    try {
      const r = await api(`/api/docs/${id}/generate`, { body: { instruction: $("#instr", v).value } });
      toast(`AI เขียนเสร็จ — บันทึกเป็น v${r.version} (${r.model})`);
      if (r.truncated) toast("คำตอบถูกตัดเพราะยาวเกิน — เพิ่ม max tokens ในหน้าตั้งค่า", true);
      $("#instr", v).value = "";
      await reload();
      showFactCheck(r.fact_check);
    } catch (e) { fail(e); } finally { done(); }
  };
  $("#ai", v).addEventListener("click", runAI);
  $("#copy", v).addEventListener("click", async () => {
    try {
      if (!(await ensureSaved())) return;
      const r = await api(`/api/docs/${id}/prompt?instruction=${encodeURIComponent($("#instr", v).value)}`);
      if (await copyText(r.prompt)) toast(`คัดลอก prompt แล้ว (${r.prompt.length.toLocaleString()} ตัวอักษร) — วางใน ChatGPT/Claude ได้เลย`);
      else await modal(`<h2>Prompt</h2><textarea readonly>${esc(r.prompt)}</textarea>`, { hideOk: true, cancel: "ปิด" });
    } catch (e) { fail(e); }
  });
  $("#paste", v).addEventListener("click", async () => {
    const r = await modal(`<h2>วางผลลัพธ์จาก ChatGPT / Claude</h2>
      <textarea name="md" required placeholder="วาง markdown ทั้งเอกสารที่นี่"></textarea>
      <label class="field">ที่มา<input name="note" value="วางจาก ChatGPT/Claude"></label>`, { ok: "บันทึกเป็นเวอร์ชันใหม่" });
    if (!r || !r.md.trim()) return;
    let md = r.md.trim();
    const m = /^(`{3,}|~{3,})(markdown|md)?[ \t]*\n([\s\S]*)\n\1\s*$/i.exec(md);
    if (m && (m[2] || !/^\s*(```|~~~)/m.test(m[3]))) md = m[3];
    ta.value = md;
    try { await save(r.note); } catch (e) { fail(e); }
  });
  const download = async (fmt) => {
    try { if (!(await ensureSaved())) return; } catch (e) { return fail(e); }
    if (!loaded.version) return toast("ยังไม่มีเวอร์ชันที่บันทึก");
    location.href = `/api/docs/${id}/download?format=${fmt}&version=${loaded.version}`;
  };
  $("#dl-docx", v).addEventListener("click", () => download("docx"));
  $("#dl-md", v).addEventListener("click", () => download("md"));
  $("#add-src", v).addEventListener("click", async () => {
    const r = await modal(`<h2>เพิ่มงานเข้าเอกสารนี้</h2>
      <div class="grid2"><label class="field">งานของวันที่<input type="date" name="date" value="${today()}"></label>
      <label class="field">ถึงวันที่ (ไม่บังคับ)<input type="date" name="date_to"></label></div>
      <label class="field">หรือระบุเลขงาน (episode id) คั่นด้วย ,<input name="ids" placeholder="เช่น 12, 13"></label>
      <div class="muted small">ถ้าใส่เลขงาน จะใช้เฉพาะงานนั้น (ไม่ใช้วันที่)</div>`, { ok: "เพิ่ม" });
    if (!r) return;
    const body = r.ids.trim() ? { episode_ids: r.ids } : { date: r.date, date_to: r.date_to };
    try {
      const res = await api(`/api/docs/${id}/sources`, { body });
      toast(res.sources_added.length ? `เพิ่ม ${res.sources_added.join(", ")} แล้ว — กด “ให้ AI ปรับ” เพื่อรวมเนื้อหาใหม่` : "ไม่มีงานใหม่");
      await reload(loaded.version);
    } catch (e) { fail(e); }
  });
  $$("[data-pane]", v).forEach((b) => b.addEventListener("click", () => {
    $$("[data-pane]", v).forEach((x) => x.classList.toggle("primary", x === b));
    $("#panes", v).className = "panes show-" + b.dataset.pane;
  }));
  if (params.get("generate") && !d.version) {
    history.replaceState(null, "", `#/docs/${id}`);
    state.hash = location.hash;
    runAI();
  }
}

// ------------------------------------------------------------ worklogs
async function renderWorklogs() {
  setView(`<div class="empty">กำลังโหลด…</div>`);
  let rows;
  try { rows = await api("/api/recaps"); } catch (e) { return setView(esc(e.message)); }
  const v = setView(`
    <div class="page-head"><h1>Daily worklog</h1>
      <button class="btn primary" id="mk">สร้าง/อัปเดต ของวันนี้</button></div>
    <p class="muted">สร้างอัตโนมัติทุกวันตามเวลาใน config (ค่าเริ่มต้น 18:00) — เปิดเพื่อแก้ไข ให้ AI ขัดเกลา หรือ export</p>
    <div class="card"><table class="list"><thead><tr><th>วันที่</th><th>สถานะ</th><th>เวอร์ชัน</th><th>แก้ไขล่าสุด</th><th></th></tr></thead><tbody>
    ${rows.length ? rows.map((r) => `<tr><td><a href="#/docs/${r.session_id}">${esc(thaiDate(r.date))}</a></td><td>${statusBadge(r.status)}</td>
      <td>v${r.latest_version}</td><td class="muted">${esc(fmtTime(r.updated_at))}</td><td><a href="#/day/${esc(r.date)}">ดูงานของวัน →</a></td></tr>`).join("")
      : `<tr><td colspan="5" class="empty">ยังไม่มี worklog</td></tr>`}
    </tbody></table></div>`);
  $("#mk", v).addEventListener("click", async () => {
    const done = busy("กำลังสร้าง Daily worklog…");
    try { const r = await api(`/api/day/${today()}/recap`, { body: {} }); location.hash = `#/docs/${r.session_id}`; }
    catch (e) { fail(e); } finally { done(); }
  });
}

// --------------------------------------------------------------- search
function renderSearch() {
  const q0 = hashParams().get("q") || "";
  const v = setView(`
    <div class="page-head"><h1>ค้นหา</h1></div>
    <input id="q" style="width:100%;font-size:16px;padding:10px 14px" placeholder="ค้นจากคำสั่ง ชื่อหน้าต่าง โน้ต และเอกสาร เช่น “syslog”, “splunk add forward-server”" value="${esc(q0)}">
    <div id="res" class="stack" style="margin-top:14px"></div>`);
  const run = debounce(async () => {
    const q = $("#q", v).value.trim();
    const box = $("#res", v);
    if (q.length < 2) { box.innerHTML = `<div class="muted">พิมพ์อย่างน้อย 2 ตัวอักษร</div>`; return; }
    try {
      const r = await api(`/api/search?q=${encodeURIComponent(q)}`);
      box.innerHTML = `
        <div class="card pad"><h2>เอกสาร (${r.docs.length})</h2>
          ${r.docs.length ? r.docs.map((d) => `<div style="margin:8px 0"><a href="#/docs/${d.session_id}"><b>${esc(d.title)}</b></a><div class="muted small">${esc(d.snippet || "")}</div></div>`).join("") : `<div class="muted">ไม่พบ</div>`}</div>
        <div class="card pad"><h2>กิจกรรม (${r.activity.length})</h2>
          ${r.activity.length ? `<table class="list"><tbody>${r.activity.map((a) => `<tr><td class="muted"><a href="#/day/${esc(a.date)}">${esc(a.date)}</a> ${esc(a.time)}</td><td><span class="badge">${esc(a.type)}</span></td><td class="mono">${esc(a.text)}</td></tr>`).join("")}</tbody></table>` : `<div class="muted">ไม่พบ</div>`}</div>`;
    } catch (e) { box.innerHTML = esc(e.message); }
  }, 250);
  $("#q", v).addEventListener("input", run);
  $("#q", v).focus();
  if (q0) run();
}

// ------------------------------------------------------------- settings
async function renderSettings() {
  setView(`<div class="empty">กำลังโหลด…</div>`);
  let s, st;
  try { [s, st] = await Promise.all([api("/api/llm"), api("/api/status")]); } catch (e) { return setView(esc(e.message)); }
  let prof = {};
  try { prof = await api("/api/profile"); } catch { prof = {}; }
  const tplList = await templates();
  const v = setView(`
    <div class="page-head"><h1>ตั้งค่า</h1></div>
    <div class="card pad stack" style="margin-bottom:14px">
      <h2>ผู้จัดทำเอกสาร</h2>
      <div class="grid2">
        <label class="field">ชื่อที่ใส่ในเอกสาร<input id="p-author" value="${esc(prof.author || "")}" placeholder="${esc(prof.effective_author || "")}"></label>
        <label class="field">ทีม / ตำแหน่ง (ไม่บังคับ)<input id="p-team" value="${esc(prof.team || "")}" placeholder="เช่น Security Engineer, Sysware"></label>
      </div>
      <div class="muted small">ถ้าเว้นว่างจะใช้ชื่อ user ของ Windows (“${esc(prof.windows_user || "")}”)</div>
      <div class="row"><button class="btn primary" id="p-save">บันทึก</button></div>
    </div>
    <div class="card pad stack">
      <h2>AI สำหรับเขียนเอกสาร</h2>
      <div class="muted small">ใช้กับปุ่ม “ให้ AI เขียน/ปรับ” — ข้อมูลที่ส่งไปคือ source pack ของเอกสารนั้น (password/token ถูกปิดบังแล้ว)</div>
      <div class="grid2">
        <label class="field">Provider<select id="provider">
          <option value="none">ไม่ใช้ (Copy/Paste prompt)</option>
          <option value="anthropic">Claude API (Anthropic)</option>
          <option value="openai">OpenAI / OpenAI-compatible (Ollama, LM Studio…)</option>
          <option value="azure">Azure OpenAI</option></select></label>
        <label class="field" data-for="anthropic openai">Model<input id="model" list="models" placeholder=""></label>
        <label class="field" data-for="anthropic openai">Base URL (ไม่บังคับ)<input id="base_url" placeholder=""></label>
        <label class="field" data-for="anthropic">Workspace ID (ใส่เมื่อ key ใช้ได้หลาย workspace)<input id="anthropic_workspace_id" placeholder="wrkspc_… — ดูได้ที่ Claude Console → Settings → Workspaces"></label>
        <label class="field" data-for="azure">Azure endpoint<input id="azure_endpoint" placeholder="https://<resource>.openai.azure.com"></label>
        <label class="field" data-for="azure">Deployment name<input id="azure_deployment" placeholder="เช่น gpt-4o-docs"></label>
        <label class="field" data-for="azure">API version<input id="azure_api_version"></label>
        <label class="field" data-for="anthropic openai azure">API key<input id="api_key" type="password" autocomplete="off"></label>
        <label class="field" data-for="anthropic openai azure">Max tokens (ความยาวคำตอบสูงสุด)<input id="max_tokens" type="number" min="1000" max="64000" step="1000"></label>
      </div>
      <datalist id="models"></datalist>
      <div class="muted small" id="keyinfo"></div>
      <div class="row">
        <button class="btn primary" id="save">บันทึก</button>
        <button class="btn" id="test">ทดสอบการเชื่อมต่อ</button>
        <button class="btn danger" id="clear">ลบ API key ที่เก็บไว้</button>
        <span id="testres" class="small"></span>
      </div>
    </div>
    <div class="card pad stack" style="margin-top:14px">
      <h2>สไตล์การเขียนที่ AI เรียนรู้จากคุณ</h2>
      <div class="muted small">ทุกครั้งที่คุณแก้ draft ของ AI แล้วกดบันทึก ระบบจะเก็บส่วนที่แก้ไว้ กด “เรียนรู้จากการแก้ไข” เพื่อสรุปเป็นกติกา
        ที่ AI จะทำตามในครั้งถัดไป (แก้เองได้)</div>
      <div class="row">
        <select id="st-tpl">${tplList.map((t) => `<option value="${esc(t.name)}">${esc(t.title)}</option>`).join("")}</select>
        <span id="st-info" class="muted small"></span>
      </div>
      <textarea id="st-text" style="min-height:140px;width:100%" placeholder="- เช่น ใช้หัวข้อสั้น ไม่เกิน 6 คำ&#10;- ทุกขั้นตอนต้องมีผลลัพธ์ที่คาดหวัง"></textarea>
      <div class="row"><button class="btn primary" id="st-save">บันทึกสไตล์</button>
        <button class="btn" id="st-learn">✨ เรียนรู้จากการแก้ไข</button></div>
    </div>
    <div class="card pad" style="margin-top:14px">
      <h2>การบันทึกกิจกรรม</h2>
      <div class="kv">
        <div>สถานะ</div><div>${st.capturing ? '<span class="badge ok">กำลังบันทึก</span>' : '<span class="badge warn">หยุดชั่วคราว</span>'} · agent ${st.agent_running ? '<span class="badge ok">ทำงาน</span>' : '<span class="badge bad">ไม่ทำงาน</span>'}</div>
        <div>ปุ่มลัด</div><div>${Object.entries(st.hotkeys || {}).map(([k, val]) => `<span class="badge">${esc(prettyKey(val))}</span> ${esc({ note: "โน้ต", screenshot: "ถ่ายรูป", task: "เริ่ม/จบงาน", pause: "หยุด/บันทึกต่อ" }[k] || k)}`).join(" &nbsp; ")}</div>
        <div>ข้อมูล</div><div class="mono">${esc(st.paths.home)}</div>
        <div>ไฟล์ตั้งค่า</div><div class="mono">${esc(st.paths.home)}/config.toml</div>
        <div>ไฟล์ export</div><div class="mono">${esc(st.paths.exports)}</div>
        <div>Templates</div><div class="mono">${esc(st.paths.templates)} <span class="muted">(${esc(st.templates.join(", "))})</span></div>
        <div>เวอร์ชัน</div><div>OpsTrail ${esc(st.version)}</div>
      </div>
    </div>`);
  $("#p-save", v).addEventListener("click", async () => {
    try { prof = await api("/api/profile", { body: { author: $("#p-author", v).value, team: $("#p-team", v).value } }); toast(`บันทึกแล้ว — เอกสารจะใช้ชื่อ “${prof.effective_author}”`); }
    catch (e) { fail(e); }
  });
  const loadStyle = async () => {
    try {
      const st = await api(`/api/style/${encodeURIComponent($("#st-tpl", v).value)}`);
      $("#st-text", v).value = st.style || "";
      $("#st-info", v).textContent = `เก็บการแก้ไขไว้แล้ว ${st.edits} ครั้ง`;
    } catch (e) { fail(e); }
  };
  $("#st-tpl", v).addEventListener("change", loadStyle);
  $("#st-save", v).addEventListener("click", async () => {
    try { await api(`/api/style/${encodeURIComponent($("#st-tpl", v).value)}`, { body: { style: $("#st-text", v).value } }); toast("บันทึกสไตล์แล้ว"); }
    catch (e) { fail(e); }
  });
  $("#st-learn", v).addEventListener("click", async () => {
    const done = busy("AI กำลังสรุปสไตล์จากการแก้ไขของคุณ…");
    try { const st = await api(`/api/style/${encodeURIComponent($("#st-tpl", v).value)}/learn`, { body: {} }); $("#st-text", v).value = st.style; toast("อัปเดตสไตล์แล้ว"); }
    catch (e) { fail(e); } finally { done(); }
  });
  loadStyle();
  const fields = ["model", "base_url", "anthropic_workspace_id", "azure_endpoint", "azure_deployment", "azure_api_version", "max_tokens"];
  const fill = (x) => {
    $("#provider", v).value = x.provider;
    for (const f of fields) $("#" + f, v).value = x[f] ?? "";
    $("#api_key", v).value = "";
    $("#api_key", v).placeholder = x.key_source === "stored" ? "•••••• (เก็บไว้แล้ว — เว้นว่าง = ใช้ key เดิม)"
      : x.key_source ? `ใช้จาก environment variable ${x.key_source}` : (x.provider === "openai" ? "ไม่ต้องใส่ถ้าเป็น Ollama/LM Studio ในเครื่อง" : "วาง API key");
    $("#keyinfo", v).innerHTML = x.has_key
      ? `API key: <b>${x.key_source === "stored" ? (x.key_protection === "dpapi" ? "เก็บในเครื่อง (เข้ารหัสด้วย Windows DPAPI)" : "เก็บในเครื่อง (ไฟล์สิทธิ์ 600 — แนะนำใช้ env OPSTRAIL_LLM_API_KEY)") : "จาก env " + esc(x.key_source)}</b>`
      : "API key: ยังไม่มี — key จะถูกเก็บแบบเข้ารหัส (Windows DPAPI) ใน ~/.opstrail/llm.json หรือตั้ง env OPSTRAIL_LLM_API_KEY";
    toggle();
  };
  const toggle = () => {
    const p = $("#provider", v).value;
    $$("[data-for]", v).forEach((el) => el.classList.toggle("hidden", !el.dataset.for.split(" ").includes(p)));
    $("#model", v).placeholder = (s.default_models && s.default_models[p]) || "";
    $("#base_url", v).placeholder = p === "anthropic" ? "https://api.anthropic.com" : "https://api.openai.com/v1  หรือ  http://localhost:11434/v1";
  };
  $("#provider", v).addEventListener("change", toggle);
  fill(s);
  const collect = () => {
    const body = { provider: $("#provider", v).value };
    for (const f of fields) body[f] = $("#" + f, v).value.trim();
    body.max_tokens = +body.max_tokens || 16000;
    const key = $("#api_key", v).value.trim();
    if (key) body.api_key = key;
    return body;
  };
  $("#save", v).addEventListener("click", async () => {
    try { s = await api("/api/llm", { body: collect() }); fill(s); state.llm = s; toast("บันทึกการตั้งค่า AI แล้ว"); } catch (e) { fail(e); }
  });
  $("#clear", v).addEventListener("click", async () => {
    if (!confirm("ลบ API key ที่เก็บไว้?")) return;
    try { s = await api("/api/llm", { body: { clear_key: true } }); fill(s); state.llm = s; toast("ลบ key แล้ว"); } catch (e) { fail(e); }
  });
  $("#test", v).addEventListener("click", async () => {
    const out = $("#testres", v);
    out.textContent = "กำลังทดสอบ…";
    try {
      s = await api("/api/llm", { body: collect() }); fill(s); state.llm = s;
      const r = await api("/api/llm/test", { body: {} });
      const cur = $("#model", v).value.trim() || (s.default_models || {})[s.provider] || "";
      const known = !r.models.length || r.models.includes(cur) || s.provider === "azure";
      out.innerHTML = `<span class="badge ok">เชื่อมต่อได้</span> ${r.models.length} model` +
        (known ? "" : ` — <span class="badge warn">ไม่พบ model “${esc(cur)}” ใน account นี้</span> คลิกช่อง Model แล้วเลือกจากรายการ จากนั้นกดบันทึก`);
      $("#models", v).innerHTML = r.models.map((m) => `<option value="${esc(m)}">`).join("");
    } catch (e) { out.innerHTML = `<span class="badge bad">ไม่สำเร็จ</span> ${esc(e.message)}`; }
  });
}

// --------------------------------------------------------------- router
const routes = [
  [/^#?\/?(\?.*)?$/, () => renderDay(today()), "day"],
  [/^#\/day\/(\d{4}-\d{2}-\d{2})/, (m) => renderDay(m[1]), "day"],
  [/^#\/worklogs/, () => renderWorklogs(), "worklogs"],
  [/^#\/docs\/(\d+)/, (m) => renderDoc(+m[1]), "docs"],
  [/^#\/docs/, () => renderDocs(), "docs"],
  [/^#\/search/, () => renderSearch(), "search"],
  [/^#\/settings/, () => renderSettings(), "settings"],
];

function route() {
  if (state.skipHash) { state.skipHash = false; return; }
  if (state.dirty && location.hash !== state.hash) {
    if (!confirm("มีการแก้ไขที่ยังไม่บันทึก — ออกจากหน้านี้?")) { state.skipHash = true; location.hash = state.hash; return; }
  }
  state.dirty = false;
  state.hash = location.hash;
  const h = location.hash || "#/";
  for (const [re, fn, name] of routes) {
    const m = re.exec(h);
    if (m) {
      $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === name));
      Promise.resolve(fn(m)).catch(fail);
      return;
    }
  }
  location.hash = "#/";
}

window.addEventListener("hashchange", route);
window.addEventListener("beforeunload", (e) => { if (state.dirty) { e.preventDefault(); e.returnValue = ""; } });
refreshStatus();
setInterval(refreshStatus, 15000);
route();
