import { SYNC_IDLE_MS } from "./config.js";

// ---- boot overlay: funny messages while Pyodide loads ------------------------------
const BOOT_MSGS = ["Waking up the snake…", "Teaching Python to count to zero…", "Reticulating splines…", "Convincing WebAssembly to cooperate…",
  "Sorting your todos by procrastination level…", "Untangling the strings…", "Herding checkboxes…", "Compiling 9.6 MB of optimism…",
  "Asking git politely…", "Checking nothing is on fire…", "Dusting off the lists…", "import antigravity…", "Feeding the interpreter…",
  "Rounding up stray bullet points…", "Calibrating the strikethrough…", "Almost there. Probably."];
let bootTimer = null;
{
  const msgs = BOOT_MSGS.slice(1).sort(() => Math.random() - 0.5), el = document.getElementById("boot-msg"); let i = 0;
  bootTimer = setInterval(() => { el.classList.add("swap"); setTimeout(() => { el.textContent = msgs[i++ % msgs.length]; el.classList.remove("swap"); }, 180); }, 1500);
}
function bootDone() { clearInterval(bootTimer); const b = document.getElementById("boot"); b.classList.add("gone"); setTimeout(() => b.remove(), 400); }
function bootFailed(err) {
  clearInterval(bootTimer); const b = document.getElementById("boot"); b.classList.add("failed");
  document.getElementById("boot-msg").textContent = "Python did not start: " + String(err.message || err).split("\n").pop().slice(0, 200);
  document.getElementById("boot-retry").hidden = false; document.getElementById("boot-retry").onclick = () => location.reload();
}

// ---- service worker (offline) -------------------------------------------
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(console.warn);
  const hadController = !!navigator.serviceWorker.controller;      // first install claims the page: not an "update"
  navigator.serviceWorker.addEventListener("controllerchange", () => { if (hadController) $("btn-reload").hidden = false; });
  document.addEventListener("click", (e) => { if (e.target.closest?.("#btn-reload")) location.reload(); });
  navigator.storage?.persist?.();
}

// ---- worker RPC ----------------------------------------------------------
const $ = (id) => document.getElementById(id);
const worker = new Worker("js/worker.js", { type: "module" });
const pending = new Map(); let seq = 0;
worker.onerror = (e) => bootFailed(e.message || "worker crashed");
worker.onmessage = ({ data }) => { if (data.fatal) return bootFailed(data.fatal); const p = pending.get(data.id); pending.delete(data.id); data.error ? p.rej(new Error(data.error)) : p.res(data.result); };
const call = (op, ...args) => new Promise((res, rej) => { const id = ++seq; pending.set(id, { res, rej }); worker.postMessage({ id, op, args }); });

let wantFocus = null;
// ---- HTMX <-> Python bridge: requests never hit the network --------------
document.body.addEventListener("htmx:beforeRequest", async (e) => {
  const { requestConfig: rc, target, elt } = e.detail;
  if (!rc.path.startsWith("/")) return;
  e.preventDefault();
  const url = new URL(rc.path, "http://x");
  const params = { ...Object.fromEntries(url.searchParams), ...Object.fromEntries(Object.entries(rc.parameters ?? {})) };
  let html;
  try { html = await call("handle", rc.verb.toUpperCase(), url.pathname, JSON.stringify(params)); }
  catch (err) { console.error(err); $("state").textContent = "error: " + err.message.split("\n").pop().slice(0, 120); return; }
  const style = (elt.getAttribute("hx-swap") || "innerHTML").split(" ")[0];
  wantFocus = /^\/item\/[^/]+\/(edit|addsub)$/.test(url.pathname) ? new Set(document.querySelectorAll(".ed-body, form.sub input[name=text]")) : null;   // only an explicit "edit" may take focus
  htmx.swap(target, html, { swapStyle: style });
  if (rc.verb !== "get") scheduleSync();
});

// ---- strings (connections) between items --------------------------------
let linkFrom = null;
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-link]"); if (!b) return;
  if (!linkFrom) { linkFrom = b.dataset.link; b.classList.add("armed"); return; }
  const a = linkFrom; linkFrom = null;
  htmx.ajax("POST", "/link", { values: { a, b: b.dataset.link }, target: "#main", swap: "innerHTML" });
});
function drawStrings() {
  for (const box of document.querySelectorAll(".cols, .detail")) {
    box.querySelector(":scope > svg.strings")?.remove();
    const links = JSON.parse(box.dataset.links || "[]"); if (!links.length) continue;
    const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg"), r0 = box.getBoundingClientRect();
    svg.setAttribute("class", "strings"); svg.setAttribute("width", box.scrollWidth); svg.setAttribute("height", box.scrollHeight);
    const rel = (x, y) => [x - r0.left + box.scrollLeft, y - r0.top + box.scrollTop];
    const centreY = (row) => {                                // an item scrolled out of its column: pin the end to that column's edge
      const r = row.getBoundingClientRect(), br = row.closest(".board")?.getBoundingClientRect();
      const y = r.top + r.height / 2; return br ? Math.min(Math.max(y, br.top + 3), br.bottom - 3) : y;
    };
    for (const [a, b] of links) {
      const ea = box.querySelector(`#i-${a} > .row`), eb = box.querySelector(`#i-${b} > .row`); if (!ea || !eb) continue;
      const pa = ea.getBoundingClientRect(), pb = eb.getBoundingClientRect(), ya = centreY(ea), yb = centreY(eb);
      let xa, xb, bow;
      if (pa.left > pb.right) { xa = pa.left; xb = pb.right; bow = -Math.max(40, (xa - xb) / 3); }          // a is to the right of b
      else if (pb.left > pa.right) { xa = pa.right; xb = pb.left; bow = Math.max(40, (xb - xa) / 3); }      // b is to the right of a
      else { xa = pa.right; xb = pb.right; bow = Math.min(36, Math.max(20, Math.abs(yb - ya) / 4)); }                      // same column: loop out to the right, never further than the gap between columns
      const [x1, y1] = rel(xa, ya), [x2, y2] = rel(xb, yb);
      const p = document.createElementNS(NS, "path");
      const same = !(pa.left > pb.right || pb.left > pa.right);
      p.setAttribute("d", `M${x1},${y1} C${x1 + bow},${y1} ${same ? x2 + bow : x2 - bow},${y2} ${x2},${y2}`);
      svg.append(p);
      for (const [x, y] of [[x1, y1], [x2, y2]]) { const c = document.createElementNS(NS, "circle"); c.setAttribute("cx", x); c.setAttribute("cy", y); c.setAttribute("r", 2.5); svg.append(c); }
    }
    box.prepend(svg);
  }
}
let strRaf = 0; document.addEventListener("scroll", () => { cancelAnimationFrame(strRaf); strRaf = requestAnimationFrame(drawStrings); }, true);   // columns scroll on their own
document.body.addEventListener("htmx:afterSettle", drawStrings);
addEventListener("resize", drawStrings);

// ---- drag & drop (native HTML5 DnD). Sources: an item row, or a sub-item row. Server decides what a drop means. ----------
let drag = null;                                              // { kind: "item", el: li.item } | { kind: "line", el: li, item, line }
const clearMarks = () => document.querySelectorAll(".drop-before,.drop-after,.drop-into,.drop-end").forEach(el => el.classList.remove("drop-before", "drop-after", "drop-into", "drop-end"));
const zoneOf = (e, el, three) => { const r = el.getBoundingClientRect(), f = (e.clientY - r.top) / r.height; return three ? (f < 0.25 ? "before" : f > 0.75 ? "after" : "into") : (f < 0.5 ? "before" : "after"); };
function dropTarget(e) {
  if (!drag) return null;
  const t = e.target, mode = t.closest?.(".board")?.dataset.mode;
  const grp = t.closest?.("h3.grp[data-color]");                               // "By color" view: drop an item on a heading = recolour
  if (grp) return drag.kind === "item" ? { el: grp, color: grp.dataset.color, cls: "drop-into" } : null;
  if (mode === "color") return null;
  const sub = t.closest?.("ul.check li");                                      // a sub-item row: drop before/after it
  if (sub) {
    if (!sub.dataset.line) return null;                                        // frozen item: not a target
    if (drag.kind === "line" && drag.el === sub) return null;
    if (drag.kind === "item" && drag.el.contains(sub)) return null;
    const zone = zoneOf(e, sub, false);
    return { el: sub, titem: sub.dataset.item, tline: sub.dataset.line, zone, cls: "drop-" + zone };
  }
  const row = t.closest?.(".row");                                             // an item row: before / after (reorder) or onto it (= its sub-item)
  if (row) {
    const li = row.closest("li.item");
    if (drag.kind === "item" && li === drag.el) return null;
    const zone = zoneOf(e, row, true);
    return { el: li, target: li.dataset.id, zone, cls: "drop-" + zone };   // the whole card is marked: that is where the drop lands
  }
  const card = t.closest?.("li.item:not(.editing)");                           // anywhere else on an item (its text, padding, rows' gaps) = onto the item
  if (card && !(drag.kind === "item" && card === drag.el)) return { el: card, target: card.dataset.id, zone: "into", cls: "drop-into" };
  const side = t.closest?.("[data-droplist]");                                 // sidebar entry: end of that list
  if (side) return { el: side, list: side.dataset.droplist, cls: "drop-end" };
  const col = t.closest?.(".col, .board");                                     // empty space in a column: end of that list
  if (col) return { el: col, list: col.dataset.list || col.querySelector(".board")?.dataset.list, cls: "drop-end" };
  return null;
}
document.addEventListener("dragstart", (e) => {
  const line = e.target.closest?.("ul.check li[data-line]");
  if (line) drag = { kind: "line", el: line, item: line.dataset.item, line: line.dataset.line };
  else {
    const li = e.target.matches?.("li.item[draggable]") ? e.target : null; if (!li) return;     // the whole card is the handle, sub-items and all
    drag = { kind: "item", el: li, item: li.dataset.id };
  }
  e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", drag.item);
  const r = drag.el.getBoundingClientRect(); e.dataTransfer.setDragImage(drag.el, Math.min(e.clientX - r.left, r.width), Math.min(e.clientY - r.top, r.height));   // ghost = the full card
  requestAnimationFrame(() => drag?.el.classList.add("dragging"));
});
document.addEventListener("dragover", (e) => {
  const t = dropTarget(e); clearMarks(); if (!t) return;
  e.preventDefault(); e.dataTransfer.dropEffect = "move"; t.el.classList.add(t.cls);
});
document.addEventListener("drop", (e) => {
  const t = dropTarget(e), d = drag; clearMarks(); if (!t || !d) return;
  e.preventDefault();
  if (t.color !== undefined) { htmx.ajax("POST", `/item/${d.item}/color`, { values: { color: t.color }, target: "#main", swap: "innerHTML" }); return; }
  const values = d.kind === "line" ? { src_item: d.item, src_line: d.line } : { item: d.item };
  for (const k of ["target", "zone", "list", "titem", "tline"]) if (t[k] !== undefined) values[k] = t[k];   // never send undefined: htmx would stringify it
  htmx.ajax("POST", "/move", { values, target: "#main", swap: "innerHTML" });
});
document.addEventListener("dragend", () => { drag?.el.classList.remove("dragging"); drag = null; clearMarks(); });

// ---- live highlighting inside the editing field (presentation only: a styled copy sits behind a transparent textarea) ----
const escHtml = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(__[^_\n]+__)|(\*[^*\s][^*\n]*\*)|((?<![\w])_[^_\n]+_(?![\w]))|(\[[^\]\n]+\]\([^)\n]+\))|(https?:\/\/[^\s<>)]+)/g;
function hlInline(raw) {
  let out = "", last = 0;
  for (const m of raw.matchAll(INLINE)) {
    out += escHtml(raw.slice(last, m.index)); last = m.index + m[0].length; const t = m[0];
    if (m[1]) out += `<span class="h-code">${escHtml(t)}</span>`;
    else if (m[2] || m[3]) out += `<b class="h-b"><i class="h-m">${t.slice(0, 2)}</i>${escHtml(t.slice(2, -2))}<i class="h-m">${t.slice(-2)}</i></b>`;
    else if (m[4] || m[5]) out += `<em class="h-i"><i class="h-m">${t[0]}</i>${escHtml(t.slice(1, -1))}<i class="h-m">${t.slice(-1)}</i></em>`;
    else if (m[6]) { const k = t.indexOf("]("); out += `<span class="h-link">${escHtml(t.slice(0, k + 1))}</span><span class="h-m">${escHtml(t.slice(k + 1))}</span>`; }
    else out += `<span class="h-url">${escHtml(t)}</span>`;
  }
  return out + escHtml(raw.slice(last));
}
function hlText(value) {
  let titleDone = false;
  return value.split("\n").map((l) => {
    const head = /^(\s*#{1,6}\s+)(.*)$/.exec(l);
    if (!titleDone && l.trim()) { titleDone = true; return `<b class="h-title">${head ? `<i class="h-m">${escHtml(head[1])}</i>${hlInline(head[2])}` : hlInline(l)}</b>`; }
    const row = /^(\s*)([-*+] )(\[[ xX]\] ?)(.*)$/.exec(l);                               // sub-item row
    if (row) { const inner = hlInline(row[4]); return escHtml(row[1]) + `<i class="h-m">${escHtml(row[2] + row[3])}</i>` + (/x/i.test(row[3]) ? `<span class="h-done">${inner}</span>` : inner); }
    if (head) return `<b class="h-b"><i class="h-m">${escHtml(head[1])}</i>${hlInline(head[2])}</b>`;
    return hlInline(l);
  }).join("\n") + "\n";                                                                    // trailing newline keeps both layers equally tall
}
function syncHighlight(ta) {
  const pre = ta.parentElement.querySelector(".hl"); if (!pre) return;
  pre.innerHTML = hlText(ta.value);
  ta.style.height = "auto"; ta.style.height = ta.scrollHeight + 2 + "px";                  // grow with the text: no inner scrolling to keep in sync
}
document.addEventListener("input", (e) => { if (e.target.matches?.(".hl-wrap textarea")) syncHighlight(e.target); });
document.body.addEventListener("htmx:afterSwap", () => document.querySelectorAll(".hl-wrap textarea").forEach(syncHighlight));

// ---- two-step delete: the first click arms the button, the second (within 3 s) goes through ----------------------
document.addEventListener("click", (e) => {
  const b = e.target.closest?.("[data-confirm]"); if (!b) return;
  if (b.classList.contains("armed")) { clearTimeout(b._t); return; }
  e.stopImmediatePropagation(); e.preventDefault();
  b.classList.add("armed"); b._label = b.innerHTML; b.textContent = b.dataset.confirm;
  b._t = setTimeout(() => { b.classList.remove("armed"); b.innerHTML = b._label; }, 3000);
}, true);

// ---- rename a list in place: pencil in the sidebar, double-click on the list title ----------------------------------
function renameList(el) {
  const lid = el.dataset.rename, host = el.closest("li") || el; if (!lid || host.querySelector("input.rename")) return;
  const label = host.querySelector("a") || el, inp = document.createElement("input");
  inp.className = "rename"; inp.value = host.dataset.name || el.dataset.name || label.textContent.trim(); inp.maxLength = 80;
  let over = false;
  const done = (save) => { if (over) return; over = true; const v = inp.value.trim(); inp.remove(); label.hidden = false;
    if (save && v) htmx.ajax("POST", `/list/${lid}/rename`, { values: { name: v }, target: "#app", swap: "innerHTML" }); };
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); done(true); } else if (e.key === "Escape") done(false); });
  inp.addEventListener("blur", () => done(true));
  label.hidden = true; label.after(inp); inp.focus(); inp.select();
}
document.addEventListener("click", (e) => { const b = e.target.closest?.("button.ren[data-rename]"); if (b) { e.preventDefault(); renameList(b); } });
document.addEventListener("dblclick", (e) => { const h = e.target.closest?.("h2[data-rename]"); if (h) renameList(h); });

// ---- Tab inside the editor indents by 4 spaces (Shift+Tab outdents); it never leaves the field ------------------
function edit(ta, from, to, text, selStart, selEnd) {
  ta.setSelectionRange(from, to);
  if (!document.execCommand("insertText", false, text)) { ta.setRangeText(text, from, to, "end"); ta.dispatchEvent(new Event("input", { bubbles: true })); }   // execCommand keeps native undo
  ta.setSelectionRange(selStart, selEnd);
}
document.addEventListener("keydown", (e) => {
  const ta = e.target; if (e.key !== "Tab" || e.ctrlKey || e.metaKey || e.altKey || e.isComposing || !ta.matches?.("form.editor textarea, form.add textarea")) return;
  e.preventDefault();
  const v = ta.value, s0 = ta.selectionStart, e0 = ta.selectionEnd, IND = "    ";
  const multi = v.slice(s0, e0).includes("\n");
  if (!e.shiftKey && !multi) return edit(ta, s0, e0, IND, s0 + 4, s0 + 4);
  const ls = v.lastIndexOf("\n", s0 - 1) + 1, le = e0 > s0 && v[e0 - 1] === "\n" ? e0 - 1 : (v.indexOf("\n", e0) < 0 ? v.length : v.indexOf("\n", e0));
  const lines = v.slice(ls, le).split("\n");
  const out = lines.map((l) => e.shiftKey ? l.replace(/^( {1,4}|\t)/, "") : IND + l);
  const text = out.join("\n"), delta0 = out[0].length - lines[0].length;
  const a = Math.max(ls, s0 + delta0);
  edit(ta, ls, le, text, a, e0 > s0 ? ls + text.length : a);
});

// ---- keyboard: Ctrl+Enter saves/adds, Esc cancels an edit, Enter in the add box adds (Shift+Enter = new line) ------
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && linkFrom) { linkFrom = null; document.querySelectorAll("[data-link].armed").forEach(x => x.classList.remove("armed")); }
  const el = e.target, form = el.closest?.("form.editor, form.add"); if (!form || e.isComposing) return;
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); form.requestSubmit(); return; }
  if (form.classList.contains("editor")) { if (e.key === "Escape") form.querySelector("[data-cancel]").click(); }
  else if (el.tagName === "TEXTAREA" && e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
});
document.body.addEventListener("htmx:afterSettle", () => {
  const root = wantFocus; wantFocus = null; if (!root) return;
  const f = [...document.querySelectorAll(".editor .ed-body, form.sub input[name=text]")].find((x) => !root.has(x));
  if (f && document.activeElement !== f) { f.focus(); f.setSelectionRange?.(f.value.length, f.value.length); }
});

// ---- sync scheduling: few commits ----------------------------------------
let timer = null;
const scheduleSync = () => { clearTimeout(timer); timer = setTimeout(syncNow, SYNC_IDLE_MS); };
async function syncNow() {
  clearTimeout(timer); if (!navigator.onLine) return;
  $("state").textContent = "syncing…";
  const msg = $("state").textContent = await call("sync");
  const busy = document.querySelector(".editor, form.sub") || document.activeElement?.matches?.("textarea, input:not([type=checkbox])");
  if (!/^up to date|pending|not signed/.test(msg) && !busy) await refreshView();   // remote changes merged in -> re-render
}
async function refreshView() { htmx.swap($("app"), await call("handle", "GET", "/", "{}"), { swapStyle: "innerHTML" }); }
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") syncNow(); });
addEventListener("online", syncNow);
$("btn-sync").onclick = syncNow;

// ---- login ----------------------------------------------------------------
const setAuth = (on) => { $("btn-share").hidden = !on; $("btn-login").hidden = on; $("btn-logout").hidden = !on; $("btn-sync").hidden = !on; };
// ---- add a device: QR + share key (the key carries the token, so it is shown only on request) ---------------------------
const flash = (btn) => { const i = btn.querySelector("i"), c = i.className; i.className = "fa-solid fa-check"; setTimeout(() => (i.className = c), 1200); };
const copy = async (text, btn) => { try { await navigator.clipboard.writeText(text); flash(btn); } catch { const s = $("share-key"); s.select(); } };
$("btn-share").onclick = async () => {
  const key = await call("share_key"); if (!key) return;
  const link = location.origin + location.pathname + "#join=" + key, qr = qrcode(0, "M");
  qr.addData(link); qr.make(); $("qr").innerHTML = qr.createSvgTag({ scalable: true, margin: 0 });
  $("share-key").value = key; $("share-dlg").dataset.link = link; $("share-dlg").showModal();
};
$("copy-key").onclick = (e) => copy($("share-key").value, e.currentTarget);
$("copy-link").onclick = (e) => copy($("share-dlg").dataset.link, e.currentTarget);
$("share-dlg").addEventListener("close", () => { $("qr").innerHTML = ""; $("share-key").value = ""; delete $("share-dlg").dataset.link; });
async function offerJoin() {                                  // opened from a share link: ask before connecting
  if (!location.hash.startsWith("#join=")) return;
  const key = decodeURIComponent(location.hash.slice(6)); history.replaceState(null, "", location.pathname + location.search);   // the secret leaves the address bar / history
  const who = $("join-who"), ok = $("join-ok"); who.className = ""; who.textContent = ""; ok.disabled = true; $("join-dlg").showModal();
  const r = await call("peek", key);
  if (r.startsWith("!")) { who.className = "bad"; who.textContent = r.slice(1); return; }
  who.innerHTML = '<i class="fa-solid fa-user"></i>'; who.append(r); ok.disabled = false;
  $("join-dlg").addEventListener("close", async () => {
    if ($("join-dlg").returnValue !== "ok") return;
    $("state").textContent = await call("login", key); setAuth(true); await loadShell();
  }, { once: true });
}
$("btn-login").onclick = () => $("login-dlg").showModal();
$("pat-eye").onclick = () => { const i = $("pat"), show = i.type === "password"; i.type = show ? "text" : "password"; $("pat-eye").firstElementChild.className = "fa-solid fa-eye" + (show ? "-slash" : ""); };
$("btn-logout").onclick = async () => { await call("logout"); setAuth(false); await loadShell(); };
$("login-dlg").addEventListener("close", async () => {
  if ($("login-dlg").returnValue !== "ok" || !$("pat").value.trim()) return;
  $("state").textContent = await call("login", $("pat").value.trim()); $("pat").value = ""; setAuth(true); await loadShell();
});
async function loadShell() { htmx.swap($("app"), await call("handle", "GET", "/", "{}"), { swapStyle: "innerHTML" }); }

(async () => {
  const slow = setTimeout(() => bootFailed("this is taking far too long (60 s)"), 60000);
  try {
    const signedIn = await call("ready");
    await loadShell(); setAuth(signedIn); offerJoin();
    if (new URLSearchParams(location.search).has("demo")) {            // http://localhost:8000/?demo  -> example lists
      history.replaceState(null, "", location.pathname);
      if (!document.querySelector("aside li[data-droplist]")) htmx.swap($("app"), await call("handle", "POST", "/demo", "{}"), { swapStyle: "innerHTML" });
    }
    if (signedIn) syncNow();
    clearTimeout(slow); bootDone();
  } catch (err) {
    clearTimeout(slow); console.error(err); bootFailed(err); }
})();
