/* PurffleShorts Studio — no framework, no build step. Talks to the local JSON API in studio.py. */
"use strict";

const TOKEN = document.querySelector('meta[name="studio-token"]').content;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const I = {
  check: '<svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v5h1"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M7 4.5v15l12.5-7.5z"/></svg>',
  pen: '<svg viewBox="0 0 24 24"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4z"/></svg>',
  up: '<svg viewBox="0 0 24 24"><path d="M18 15l-6-6-6 6"/></svg>',
  down: '<svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>',
  plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
  upload: '<svg viewBox="0 0 24 24"><path d="M12 16V4M7 9l5-5 5 5M4 20h16"/></svg>',
  dl: '<svg viewBox="0 0 24 24"><path d="M12 4v12M7 11l5 5 5-5M4 20h16"/></svg>',
  yt: '<svg viewBox="0 0 24 24"><rect x="2.5" y="5" width="19" height="14" rx="4"/><path d="M10 9v6l5-3z"/></svg>',
  spark: '<svg viewBox="0 0 24 24"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/></svg>',
  film: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4M3 16h4M17 8h4M17 16h4"/></svg>',
  doc: '<svg viewBox="0 0 24 24"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/></svg>',
  bulb: '<svg viewBox="0 0 24 24"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V16h5v-.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z"/></svg>',
  bag: '<svg viewBox="0 0 24 24"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><path d="M3 6h18M16 10a4 4 0 0 1-8 0"/></svg>',
  star: '<svg viewBox="0 0 24 24"><path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21 7 14.2 2 9.3l6.9-1z"/></svg>',
  link: '<svg viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7.1-7.1l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7.1 7.1l1.7-1.7"/></svg>',
  scissors: '<svg viewBox="0 0 24 24"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M8.6 7.6 20 18M8.6 16.4 20 6"/></svg>',
  chart: '<svg viewBox="0 0 24 24"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>',
  refresh: '<svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-2.6-6.4M21 4v5h-5"/></svg>',
  copy: '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
};

const FORMATS = [
  ["auto", "Auto", "The AI picks the best format"],
  ["facts", "Facts", "Rapid-fire surprising facts"],
  ["story", "Story", "A true story with a twist"],
  ["listicle", "Top 3", "Countdown to number one"],
  ["myth", "Myth vs fact", "Bust a common belief"],
  ["quiz", "Quiz", "Question, suspense, answer"],
  ["explainer", "Explainer", "One idea, one analogy"],
  ["motivational", "Motivation", "A story and a takeaway"],
  ["news", "News", "What happened and why"],
  ["dialogue", "Dialogue", "Two voices, back and forth", true],
  ["chat", "Text story", "Animated text messages", true],
  ["reddit", "Reddit story", "Post card, then the story", true],
  ["product", "Product", "Product demos and comparisons", true],
];
const MULTI = new Set(["dialogue", "chat"]);
const STAGES = [["topic", "Topic"], ["script", "Script"], ["review", "Review"], ["voice", "Voice"], ["footage", "Footage"],
  ["captions", "Captions"], ["render", "Render"], ["check", "Check"], ["upload", "Upload"]];
const STATUS_CHIP = { uploaded: "ok", scheduled: "blue", rendered: "accent", queued: "", failed: "bad", "upload-unknown": "bad" };
const KIND_ICON = { make: I.film, draft: I.pen, clip: I.scissors, plan: I.bulb, scout: I.bag, upload: I.upload, stats: I.chart };

const store = {
  get(k, d) { try { const v = localStorage.getItem("purffle." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("purffle." + k, JSON.stringify(v)); return true; } catch { return false; } },
};

async function get(url) {
  const r = await fetch(url);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}
async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-Studio-Token": TOKEN }, body: JSON.stringify(body || {}) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

const savedDraft = store.get("draftState", null);
const S = {
  info: null, options: null, jobs: [], view: "create",
  form: store.get("form", {}), draft: savedDraft ? savedDraft.script : store.get("draft", null), createJob: store.get("createJob", null),
  draftSource: savedDraft ? savedDraft.source : store.get("draftSource", {}),
  previousDraft: store.get("previousDraft", null),
  affiliateDrafts: store.get("affiliateDrafts", {}),
  prod: { platform: "", sort: "viral", q: "", starred: false, selected: [], mode: "stores", store_id: "", query: "", scout_plat: "", url: "", limit: 8 },
  lib: { status: "", q: "" }, seen: new Map(), voices: {},
};

// ------------------------------------------------------------------ helpers
function toast(html, kind = "info", ms = 5200) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `${kind === "ok" ? I.check : kind === "bad" ? I.x : I.info}<div>${html}</div>`;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), ms);
}
function paint(root = document) {  // CSP forbids inline styles: sizes are applied from data attributes
  $$("[data-w]", root).forEach(el => { el.style.width = Math.max(0, Math.min(100, +el.dataset.w)) + "%"; });
  $$("[data-p]", root).forEach(el => { el.style.setProperty("--p", el.dataset.p); el.style.setProperty("--c", scoreColor(+el.dataset.p)); });
}
const scoreColor = p => p >= 75 ? "var(--ok)" : p >= 55 ? "var(--accent)" : "var(--bad)";
const fmtSec = s => s == null ? "" : s >= 60 ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}` : `${Math.round(s)}s`;
const fmtNum = n => n == null ? "–" : Number(n).toLocaleString();
function ago(ts) {
  if (!ts) return "";
  const t = typeof ts === "number" ? ts * 1000 : Date.parse(ts);
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(t).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
function seg(name, opts, cur) {
  return `<div class="seg" role="group">${opts.map(([v, label]) =>
    `<button type="button" data-seg="${name}" data-v="${esc(v)}" aria-pressed="${String(v) === String(cur)}">${label}</button>`).join("")}</div>`;
}
function sel(name, opts, cur) {
  return `<select data-f="${name}">${opts.map(([v, label]) => `<option value="${esc(v)}"${String(v) === String(cur) ? " selected" : ""}>${esc(label)}</option>`).join("")}</select>`;
}
const shortTitle = t => (t || "").replace(/\s*#shorts$/i, "");
const words = t => (t || "").trim().split(/\s+/).filter(Boolean).length;
const saveForm = () => store.set("form", S.form);
let draftStorageFailed = false;
function saveDraft() {
  // The script and its billing/source identity must change together.
  const saved = store.set("draftState", { script: S.draft, source: S.draftSource });
  if (saved) {
    store.set("draft", S.draft);
    store.set("draftSource", S.draftSource);
  } else if (!draftStorageFailed) {
    toast("This browser could not save your script. Keep this page open and copy your edits before leaving.", "bad", 12000);
  }
  draftStorageFailed = !saved;
  return saved;
}
function replaceDraft(script, source = {}) {
  if (S.draft) {
    S.previousDraft = { script: S.draft, source: S.draftSource };
    store.set("previousDraft", S.previousDraft);
  }
  S.draft = script ? JSON.parse(JSON.stringify(script)) : null;
  S.draftSource = JSON.parse(JSON.stringify(source));
  saveDraft();
}
function restorePreviousDraft() {
  const previous = S.previousDraft;
  if (!previous || !confirm("Restore the previous script? The current script will be kept as the previous version.")) return;
  replaceDraft(previous.script, previous.source || {});
  if (S.draft.language) S.form.language = S.draft.language;
  if (S.draft.style) S.form.style = S.draft.style;
  saveForm();
  drawForm();
  drawEditor();
}

// ------------------------------------------------------------------ boot & routing
async function boot() {
  try {
    [S.info, S.options] = await Promise.all([get("/api/info"), get("/api/options")]);
  } catch (e) {
    $("#main").innerHTML = `<div class="empty"><b>Can't reach the Studio server</b>${esc(e.message)}</div>`;
    return;
  }
  const i = S.info;
  S.form = Object.assign({
    mode: "topic", topic: "", url: "", style: i.style || "auto", language: i.language, duration: i.duration,
    speed: i.speed || 1,
    aspect: ["9:16", "16:9", "1:1", "4:5"].includes(i.aspect) ? i.aspect : "9:16", caption_style: i.caption_style,
    caption_position: i.caption_position, grade: i.grade, transition: i.transition, review: i.review, tts: i.tts,
    voice: "", voice_b: "", provider: "", model: "", also_langs: (i.also_languages || []).join(", "), music: true,
    model_planner: i.llm_models?.planner || "", model_script: i.llm_models?.script || "",
    model_review: i.llm_models?.review || "", model_translation: i.llm_models?.translation || "",
    model_clip: i.llm_models?.clip || "",
    upload: false, offline: !i.llm_ok, visuals: i.visuals,
  }, S.form);
  if (!i.llm_ok) S.form.offline = true;
  status();
  window.addEventListener("hashchange", route);
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") closeDrawer();
    if (e.key === "Tab" && !$("#drawer").hidden) {
      const controls = $$('#drawer-panel button, #drawer-panel a[href], #drawer-panel input, #drawer-panel select, #drawer-panel summary, #drawer-panel video[controls]')
        .filter(el => !el.disabled && el.getClientRects().length);
      const first = controls[0], last = controls[controls.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    }
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && S.view === "create" && $("#drawer").hidden) startMake();
  });
  $("#drawer").addEventListener("click", e => { if (e.target.closest("[data-close]")) closeDrawer(); });
  route();
  tick();
  setInterval(tick, 1500);
  setInterval(async () => { try { S.info = await get("/api/info"); status(); } catch { /* server restarting */ } }, 15000);
}

function status() {
  const i = S.info;
  $("#status").innerHTML = [
    ["AI", i.llm_ok ? i.llm : "demo only"], ["Voice", i.tts], ["Uploads left", i.upload ? `${Math.max(0, i.quota_left)} / ${i.daily_limit}` : "off"],
  ].map(([k, v]) => `<div class="row"><span>${k}</span><b title="${esc(v)}">${esc(v)}</b></div>`).join("");
  const ib = $("#ibadge");
  ib.hidden = !i.ideas;
  ib.textContent = i.ideas;
  const pb = $("#pbadge");
  if (pb) { pb.hidden = !i.products; pb.textContent = i.products; }
  showCostAlerts(i.costs);
}

const VIEWS = { create: viewCreate, library: viewLibrary, queue: viewQueue, ideas: viewIdeas, products: viewProducts, clip: viewClip, channel: viewChannel, costs: viewCosts, system: viewSystem };
function route() {
  const v = (location.hash || "#create").slice(1).split("/")[0];
  S.view = VIEWS[v] ? v : "create";
  $$("#nav a").forEach(a => a.classList.toggle("active", a.dataset.view === S.view));
  const m = $("#main");
  m.onclick = m.onchange = m.oninput = m.onsubmit = null;
  m.innerHTML = "";
  VIEWS[S.view]();
  m.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

// ------------------------------------------------------------------ jobs polling
async function tick() {
  let jobs;
  try { jobs = await get("/api/jobs"); } catch { return; }
  S.jobs = jobs;
  const active = jobs.filter(j => j.status === "running" || j.status === "queued").length;
  const qb = $("#qbadge");
  qb.hidden = !active;
  qb.textContent = active;
  for (const j of jobs) {
    const before = S.seen.get(j.id);
    S.seen.set(j.id, j.status);
    if (before && before !== j.status && ["done", "failed"].includes(j.status)) finished(j);
  }
  // A draft that finished while this page was closed or reloading still belongs in the editor.
  const cj = currentCreateJob();
  if (cj && cj.kind === "draft" && cj.status === "done" && !S.createJob.loaded) finished(cj);
  if (S.view === "queue") drawJobs();
  if (S.view === "create") drawLive();
}

function finished(j) {
  const r = j.result || {};
  if (j.kind === "draft" && j.status === "done" && currentCreateJob() === j) {
    if (S.createJob.loaded) return;
    S.createJob.loaded = true;
    store.set("createJob", S.createJob);
    const source = { usage_run_id: r.usage_run_id || "" };
    if (r.product_ids && r.product_ids.length) source.product_ids = r.product_ids;
    if (r.images && r.images.length) source.images = r.images;
    if (r.videos && r.videos.length) source.videos = r.videos;
    replaceDraft(r.script, source);
    toast("Script ready — read it, edit anything, then render.", "ok");
    if (S.view === "create") drawSide();
    return;
  }
  if (j.status === "failed") {
    toast(`<b>${esc(j.label)}</b><br>${esc((r.error || j.message || "failed").slice(0, 220))}`, "bad", 9000);
  } else if (j.kind === "make" || j.kind === "clip") {
    const id = r.id || (r.clips && r.clips.find(c => c.ok) || {}).id;
    const needsReview = [r, ...(r.clips || []), ...(r.variants || [])]
      .some(v => ["upload-unknown", "upload-failed", "failed"].includes(v.status));
    toast(`<b>${esc(r.title || j.label)}</b> is ready.${needsReview ? " Some versions or uploads need attention." : ""} ${id ? `<a href="#library" data-open="${id}">Open video</a>` : ""}`, needsReview ? "bad" : "ok", 9000);
    if (S.view === "products") refreshProductsList();
  } else if (j.kind === "plan") {
    toast(`${r.ideas} new idea(s) in the queue.`, "ok");
    if (S.view === "ideas") viewIdeas();
  } else if (j.kind === "scout") {
    toast(`Scouted ${r.products || 0} product(s) with viral dossier.`, "ok");
    if (S.view === "products") viewProducts();
  } else if (j.kind === "upload") {
    toast(`Upload: ${esc(r.status)}`, r.status === "failed" ? "bad" : "ok");
  } else if (j.kind === "stats") {
    toast(`Stats refreshed for ${r.updated} video(s).`, "ok");
    if (S.view === "channel") viewChannel();
  }
  get("/api/info").then(i => { S.info = i; status(); }).catch(() => {});
  if (S.view === "library") drawLibrary();
  if (S.view === "create") drawSide();
}

document.addEventListener("click", e => {
  const o = e.target.closest("[data-open]");
  if (o) { e.preventDefault(); if (S.view !== "library") location.hash = "#library"; openVideo(+o.dataset.open); }
});

// ------------------------------------------------------------------ CREATE
function payload(extra = {}) {
  const f = S.form;
  const p = {
    style: f.style === "auto" ? "" : f.style, language: f.language, duration: f.duration, speed: f.speed,
    aspect: f.aspect,
    caption_style: f.caption_style, caption_position: f.caption_position, grade: f.grade, transition: f.transition,
    tts: f.tts, voice: f.voice, voice_b: f.voice_b, provider: f.provider, model: f.model, review: f.review,
    ...modelPayload(),
    also_langs: f.also_langs, music: f.music, upload: f.upload && S.info.upload && !f.offline, offline: f.offline,
    visuals: f.visuals,
  };
  if (!extra.product_ids && !extra.script && !extra.idea_id) {
    if (f.mode === "topic") p.topic = f.topic.trim();
    if (f.mode === "url") {
      p.url = f.url.trim();
      if ((f.affiliate_url || "").trim()) p.product_links = [(f.affiliate_url || "").trim()];
    }
    if (f.mode === "queue") p.source = "queue";
  }
  return Object.assign(p, extra.script ? S.draftSource : {}, extra);
}
function modelPayload() {
  const f = S.form;
  return Object.fromEntries(["planner", "script", "review", "translation", "clip"]
    .map(stage => [`model_${stage}`, f[`model_${stage}`] || ""]));
}

let _jobLaunchBusy = false;
async function startMake(extra = {}) {
  if (_jobLaunchBusy) return;
  const f = S.form;
  if (f.mode === "url" && !f.url.trim() && !extra.script && !extra.product_ids && !extra.idea_id) {
    return toast("Paste the address of a web page first.", "bad");
  }
  _jobLaunchBusy = true;
  try {
    const { job } = await post("/api/make", payload(extra));
    S.createJob = { id: job, kind: "make", session: TOKEN };
    store.set("createJob", S.createJob);
    S.seen.set(job, "queued");
    toast(extra.script ? "Rendering your script…" : "Making your video…", "info", 3000);
    drawSide();
    tick();
  } catch (e) { toast(esc(e.message), "bad"); }
  finally { _jobLaunchBusy = false; }
}
async function startDraft(extra = {}) {
  if (_jobLaunchBusy) return;
  const f = S.form;
  if (f.offline) return toast("Drafting needs an AI model. Turn off demo mode (and add a key in .env).", "bad");
  if (f.mode === "url" && !f.url.trim() && !extra.product_ids && !extra.idea_id) {
    return toast("Paste the address of a web page first.", "bad");
  }
  _jobLaunchBusy = true;
  try {
    const { job } = await post("/api/draft", payload(extra));
    S.createJob = { id: job, kind: "draft", session: TOKEN };
    store.set("createJob", S.createJob);
    S.seen.set(job, "queued");
    drawSide();
    tick();
  } catch (e) { toast(esc(e.message), "bad"); }
  finally { _jobLaunchBusy = false; }
}

function viewCreate() {
  const i = S.info, f = S.form;
  $("#main").innerHTML = `
  <div class="page-head"><div><h1>Create</h1><p>From an idea to a finished, captioned video. Draft first to read and edit the script, or go straight to the render.</p></div></div>
  ${i.llm_ok ? "" : `<div class="banner">${I.info}<p><b>No AI model is set up yet.</b> Demo mode renders a sample video with no keys. Add one API key (or run Ollama) in <span class="mono">.env</span> to write real scripts — see <a href="#system">System</a>.</p></div>`}
  <div class="create"><div id="form"></div><div class="sticky" id="side"></div></div>`;
  drawForm();
  drawSide();
}

function drawForm() {
  const f = S.form, o = S.options;
  const langs = Object.entries(o.languages);
  const provs = [["", "Default (.env)"], ...o.providers.map(p => [p.name, `${p.label}${p.ready ? "" : " — no key"}`])];
  const multi = MULTI.has(f.style);
  $("#form").innerHTML = `
  <section class="card">
    <h2>What's it about?</h2>
    <div class="src-tabs">${seg("mode", [["topic", "Topic"], ["url", "Web page"], ["queue", "Idea queue"], ["auto", "Surprise me"]], f.mode)}</div>
    ${f.mode === "topic" ? `<div class="field"><input type="text" data-f="topic" value="${esc(f.topic)}" placeholder="e.g. Why octopuses have three hearts" aria-label="Topic"><p class="hint">Be as broad or specific as you like — the AI finds the surprising angle.</p></div>`
    : f.mode === "url" ? `<div class="field"><input type="url" data-f="url" value="${esc(f.url)}" placeholder="https://… an article, product page, blog post or Wikipedia page" aria-label="Web page">
      <input type="text" data-f="affiliate_url" value="${esc(f.affiliate_url || "")}" placeholder="Affiliate link (optional) — e.g. Produto 1: https://amzn.to/..." aria-label="Affiliate link">
      <p class="hint">The page's text (or product info & photos) becomes the script's source material — or scout best-sellers on <a href="#products">Products</a>.</p></div>`
    : f.mode === "queue" ? `<p class="hint">Uses the oldest idea from your queue (${i_ideas()} waiting) — plan more on the <a href="#ideas">Ideas</a> or <a href="#products">Products</a> page.</p>`
    : `<p class="hint">Picks a fresh topic from your niches and topic sources in .env.</p>`}
  </section>

  <section class="card">
    <h2>Format</h2>
    <div class="formats">${FORMATS.map(([k, name, blurb, isNew]) =>
      `<button type="button" class="fmt" data-seg="style" data-v="${k}" aria-pressed="${f.style === k}"><b>${name}${isNew ? '<span class="new">NEW</span>' : ""}</b><span>${blurb}</span></button>`).join("")}</div>
  </section>

  <section class="card">
    <h2>Shape & voice</h2>
    <div class="grid2">
      <div class="field"><label>Language</label>${sel("language", langs.map(([c, n]) => [c, `${n} (${c})`]), f.language)}</div>
      <div class="field"><label>Narration length</label><div class="range-row"><input type="range" min="15" max="120" step="5" data-f="duration" value="${f.duration}" aria-label="Narration length in seconds"><output id="dur-out">${f.duration}s</output></div></div>
    </div>
    <div class="field"><label for="video-speed">Final video speed</label><div class="range-row"><input id="video-speed" type="range" min="0.5" max="2" step="0.05" data-f="speed" value="${f.speed}" aria-describedby="speed-hint"><output id="speed-out">${+Number(f.speed).toFixed(2)}×</output></div>
      <p class="hint" id="speed-hint">About ${Math.round(f.duration / f.speed)}s after export. Voice pitch is preserved; music and captions follow the same speed.</p></div>
    <div class="field"><label>Aspect</label>${seg("aspect", [["9:16", '<i class="shape s916"></i>9:16 Short'], ["16:9", '<i class="shape s169"></i>16:9 YouTube'], ["1:1", '<i class="shape s11"></i>1:1 Square'], ["4:5", '<i class="shape s45"></i>4:5 Feed']], f.aspect)}</div>
    <div class="grid2">
      <div class="field"><label>Voice engine</label>${sel("tts", o.tts.map(t => [t, { edge: "Microsoft neural (free)", openai: "OpenAI", openrouter: "OpenRouter", elevenlabs: "ElevenLabs", kokoro: "Kokoro (local)", coqui: "Coqui (local)", system: "System voice" }[t] || t]), f.tts)}</div>
      <div class="field"><label>${multi ? "Voice A" : "Voice"}</label><input type="text" data-f="voice" list="voices" value="${esc(f.voice)}" placeholder="automatic for the language"></div>
    </div>
    ${multi ? `<div class="field"><label>Voice B (second speaker)</label><input type="text" data-f="voice_b" list="voices" value="${esc(f.voice_b)}" placeholder="automatic contrasting voice"></div>` : ""}
    <datalist id="voices"></datalist>
  </section>

  <section class="card">
    <h2>Look</h2>
    <div class="swatches">${o.caption_styles.map(c => `<button type="button" class="sw" data-seg="caption_style" data-v="${c}" aria-pressed="${f.caption_style === c}">${capSample(c)}<small>${c}</small></button>`).join("")}</div>
    <div class="field"><label>Caption position</label>${seg("caption_position", [["upper", "Top"], ["center", "Middle"], ["lower", "Lower third"]], f.caption_position)}</div>
    <div class="grid2">
      <div class="field"><label>Colour grade</label>${sel("grade", o.grades.map(g => [g, g]), f.grade)}</div>
      <div class="field"><label>Transitions</label>${sel("transition", o.transitions.map(t => [t, t]), f.transition)}</div>
    </div>
    <div class="field"><label>Footage & images</label><div class="checks-inline">${o.visuals.map(v => `<label><input type="checkbox" data-visual="${v}"${(f.visuals || []).includes(v) ? " checked" : ""}>${{ pexels: "Pexels", pixabay: "Pixabay", local: "My media folder", pollinations: "AI images (Pollinations, key advised)", "openai-images": "OpenAI images", "openrouter-images": "OpenRouter images", "openrouter-video": "OpenRouter video" }[v] || v}</label>`).join("")}</div></div>
    <div class="field"><label class="switch"><input type="checkbox" data-f="music"${f.music ? " checked" : ""}><span>Background music<small>From your music folder, ducked under the voice</small></span></label></div>
  </section>

  <section class="card">
    <h2>AI & publishing</h2>
    <div class="grid2">
      <div class="field"><label>AI model provider</label>${sel("provider", provs, f.provider)}</div>
      <div class="field"><label>Model</label><input type="text" data-f="model" value="${esc(f.model)}" placeholder="provider default"></div>
    </div>
    <details class="field"><summary>Choose a model for each stage</summary>
      <p class="hint">Use OpenRouter IDs such as <span class="mono">openai/gpt-6-luna</span>. Blank uses the configured model.</p>
      <div class="grid2">${[["planner", "Idea planning"], ["script", "Script writing"], ["review", "Script review"],
        ["translation", "Translation"], ["clip", "Clip selection"]].map(([stage, label]) =>
        `<div class="field"><label>${label}</label><input type="text" data-f="model_${stage}" value="${esc(f[`model_${stage}`] || "")}" placeholder="inherit default"></div>`).join("")}</div>
    </details>
    <div class="field"><label>Script Doctor</label>${seg("review", [["off", "Off"], ["score", "Score only"], ["rewrite", "Score & rewrite"]], f.review)}<p class="hint">A second AI pass grades the hook and pacing, then rewrites weak lines.</p></div>
    <div class="field"><label>Also make it in</label><input type="text" data-f="also_langs" value="${esc(f.also_langs)}" placeholder="e.g. es, hi, pt — translated copies, same footage"></div>
    <div class="grid2">
      <label class="switch"><input type="checkbox" data-f="upload"${f.upload ? " checked" : ""}${S.info.upload ? "" : " disabled"}><span>Upload to YouTube<small>${S.info.upload ? `${S.info.privacy}, or scheduled` : "disabled in .env (UPLOAD=false)"}</small></span></label>
      <label class="switch"><input type="checkbox" data-f="offline"${f.offline ? " checked" : ""}><span>Demo mode<small>No keys: sample script, generated backgrounds</small></span></label>
    </div>
  </section>

  <div class="go-row">
    <button class="btn" id="draft-btn" type="button">${I.pen}Draft script</button>
    <button class="btn primary" id="make-btn" type="button">${I.play}Create video</button>
  </div>`;
  bindForm();
  loadVoices();
}
const i_ideas = () => S.info.ideas || 0;

function capSample(style) {
  if (style === "karaoke") return `<span class="cap karaoke"><u>THREE</u> <i>HEARTS</i></span>`;
  return `<span class="cap ${style}">THREE <i>HEARTS</i></span>`;
}

function bindForm() {
  const root = $("#form");
  root.addEventListener("click", e => {
    const b = e.target.closest("[data-seg]");
    if (!b) return;
    const k = b.dataset.seg, v = b.dataset.v;
    const multiBefore = MULTI.has(S.form.style);
    S.form[k] = v;
    saveForm();
    if (k === "mode" || (k === "style" && MULTI.has(v) !== multiBefore)) return drawForm();
    $$(`[data-seg="${k}"]`, root).forEach(x => x.setAttribute("aria-pressed", String(x.dataset.v === v)));
    if (k === "caption_style" || k === "aspect") drawSide();
  });
  root.addEventListener("input", e => {
    const el = e.target;
    if (el.dataset.visual) {
      S.form.visuals = $$("[data-visual]", root).filter(x => x.checked).map(x => x.dataset.visual);
    } else if (el.dataset.f) {
      S.form[el.dataset.f] = el.type === "checkbox" ? el.checked : el.type === "range" ? +el.value : el.value;
      if (el.dataset.f === "duration") $("#dur-out").textContent = el.value + "s";
      if (["duration", "speed"].includes(el.dataset.f)) {
        $("#speed-out").textContent = `${+Number(S.form.speed).toFixed(2)}×`;
        $("#speed-hint").textContent = `About ${Math.round(S.form.duration / S.form.speed)}s after export. Voice pitch is preserved; music and captions follow the same speed.`;
      }
      if (el.dataset.f === "language" || el.dataset.f === "tts") loadVoices();
    }
    saveForm();
  });
  $("#make-btn").onclick = () => startMake();
  $("#draft-btn").onclick = () => startDraft();
}

async function loadVoices() {
  const f = S.form, dl = $("#voices");
  if (!dl || f.tts !== "edge") { if (dl) dl.innerHTML = ""; return; }
  const lang = f.language;
  if (!S.voices[lang]) {
    try { S.voices[lang] = await get("/api/voices?lang=" + encodeURIComponent(lang)); } catch { S.voices[lang] = []; }
  }
  if (S.form.language === lang && $("#voices")) {
    $("#voices").innerHTML = S.voices[lang].map(v => `<option value="${esc(v.name)}">${esc(v.gender)} · ${esc(v.locale)}</option>`).join("");
  }
}

function currentCreateJob() {
  // Job ids restart with the server, so a job remembered from an earlier session is not this one.
  if (!S.createJob || S.createJob.session !== TOKEN) return null;
  return S.jobs.find(j => j.id === S.createJob.id) || null;
}

function drawSide() {
  const side = $("#side");
  if (!side) return;
  side.innerHTML = `<div id="live"></div><div id="editor"></div>`;
  drawLive();
  drawEditor();
}

function drawLive() {
  const box = $("#live");
  if (!box) return;
  const j = currentCreateJob();
  if (!j || (j.status === "done" && j.kind === "draft") || j.status === "cancelled") { box.innerHTML = ""; return; }
  const r = j.result || {};
  const idx = STAGES.findIndex(([k]) => k === j.stage);
  const running = j.status === "running" || j.status === "queued";
  const name = j.status === "queued" ? "Waiting for the previous job" : j.status === "failed" ? "Failed"
    : j.status === "done" ? "Finished" : (STAGES[idx] || [0, "Starting"])[1];
  box.innerHTML = `<section class="card live ${j.status}">
    <div class="actions"><span class="status-pill ${j.status}">${j.kind === "draft" ? "Drafting" : "Making"} · ${j.status}</span>
      ${!running ? `<button class="btn ghost sm" id="live-close" type="button" aria-label="Dismiss">${I.x}</button>` : ""}</div>
    <h3>${esc(r.title || j.label)}</h3>
    ${running ? `<div class="stages">${STAGES.map(([k], n) => `<span class="${n < idx ? "done" : n === idx ? "now" : ""}" title="${k}"></span>`).join("")}</div>
      <div class="stage-name"><b>${esc(name)}</b><span>${esc(j.message || "")}</span></div>` : ""}
    ${j.status === "done" && r.id ? `<div class="actions"><button class="btn primary sm" type="button" data-open="${r.id}">${I.play}Watch</button>
      ${r.score != null ? `<span class="chip ${r.score >= 75 ? "ok" : r.score >= 55 ? "accent" : "bad"}">Retention score ${r.score}</span>` : ""}
      <span class="chip">${esc(r.status)}</span>${(r.variants || []).map(v => `<span class="chip ${v.ok ? "ok" : "bad"}">${esc(v.language)} ${v.ok ? "✓" : "✗"}</span>`).join("")}</div>` : ""}
    ${j.status === "failed" ? `<div class="err">${esc(r.error || j.message)}</div>` : ""}
    ${running ? `<pre class="log" id="live-log">${esc(j.log.slice(-8).join("\n"))}</pre>` : ""}
  </section>`;
  const c = $("#live-close");
  if (c) c.onclick = () => { S.createJob = null; store.set("createJob", null); drawSide(); };
}

function drawEditor() {
  const box = $("#editor");
  if (!box) return;
  const d = S.draft, f = S.form;
  const j = currentCreateJob();
  if (!d) {
    if (j && (j.status === "running" || j.status === "queued")) { box.innerHTML = ""; return; }
    box.innerHTML = `<section class="card"><h2>Preview</h2>
      <div class="phone"><div class="bar"></div><div class="ph-hook">This animal has 3 hearts</div>${capSample(f.caption_style)}</div>
      <p class="hint">Caption style <b>${esc(f.caption_style)}</b> · ${esc(f.aspect)} · ${esc(f.language)}</p>
      ${S.previousDraft ? `<button class="btn ghost sm" id="restore-draft" type="button">${I.pen}Restore previous script</button>` : ""}
      <div class="list">
        <div class="item"><span class="chip accent">1</span><div class="grow"><b>Draft script</b><small>The AI writes it, the Script Doctor scores and improves it, and you edit any line before rendering.</small></div></div>
        <div class="item"><span class="chip accent">2</span><div class="grow"><b>Create video</b><small>Voice, footage, word-synced captions, music and render in one go — about a minute.</small></div></div>
        <div class="item"><span class="chip accent">3</span><div class="grow"><b>Publish</b><small>Upload or schedule from the Library, or turn on upload here.</small></div></div>
      </div></section>`;
    const restore = $("#restore-draft");
    if (restore) restore.onclick = restorePreviousDraft;
    return;
  }
  const multi = MULTI.has(d.style) || d.scenes.some(s => s.speaker === "B");
  const isProduct = d.style === "product";
  const hasLinks = isProduct || (d.product_links && d.product_links.length);
  const total = d.scenes.reduce((n, s) => n + words(s.narration), 0);
  const target = Math.round((f.duration || 40) * 2.6);
  box.innerHTML = `<section class="card">
    <div class="actions"><h2>Script</h2><span class="chip">${esc(d.style)}</span><span class="chip">${esc(d.language)}</span>
      <span class="wc" id="wc">${total} words · ~${Math.round(total / 2.6)}s</span>
      ${S.previousDraft ? `<button class="btn ghost sm" id="restore-draft" type="button">Restore previous script</button>` : ""}
      <button class="btn ghost sm" id="discard" type="button">${I.trash}Discard</button></div>
    ${d.score != null ? `<div class="score"><div class="ring" data-p="${d.score}"><b>${d.score}</b></div><div><b>Retention score</b>${d.review && d.review.length ? `<ul>${d.review.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="hint">No issues found.</p>`}</div></div>` : ""}
    <div class="field"><label>Title</label><input type="text" data-k="title" value="${esc(d.title)}" maxlength="90"></div>
    <div class="field"><label>On-screen hook</label><input type="text" data-k="hook_text" value="${esc(d.hook_text)}" maxlength="48"></div>
    ${multi ? `<div class="grid2"><div class="field"><label>Speaker A</label><input type="text" data-cast="0" value="${esc((d.cast || [])[0] || "")}"></div>
      <div class="field"><label>Speaker B</label><input type="text" data-cast="1" value="${esc((d.cast || [])[1] || "")}"></div></div>` : ""}
    <div class="field"><label>Scenes <span class="hint">· target about ${target} words</span></label>
    <div class="scenes">${d.scenes.map((s, n) => `
      <div class="scene ${s.speaker === "B" ? "b" : "a"}${multi ? " multi" : ""}">
        <span class="num">${multi ? esc(s.speaker || "A") : n + 1}</span>
        <div class="field">
          <textarea data-i="${n}" data-s="narration" aria-label="Scene ${n + 1} narration">${esc(s.narration)}</textarea>
          <div class="row">
            ${multi ? `<button class="btn ghost sm" type="button" data-act="speaker" data-i="${n}" title="Switch speaker">A/B</button>` : ""}
            ${isProduct ? `<input type="text" data-i="${n}" data-s="product" value="${esc(s.product || "")}" placeholder="product name (not shown on screen)" aria-label="Product name (not shown on screen)">` : ""}
            <input type="text" data-i="${n}" data-s="search_query" value="${esc(s.search_query)}" placeholder="footage search" aria-label="Footage search">
            <span class="tools">
              <button class="btn ghost sm" type="button" data-act="up" data-i="${n}" aria-label="Move up">${I.up}</button>
              <button class="btn ghost sm" type="button" data-act="down" data-i="${n}" aria-label="Move down">${I.down}</button>
              <button class="btn ghost sm" type="button" data-act="del" data-i="${n}" aria-label="Delete scene">${I.trash}</button>
            </span>
          </div>
        </div>
      </div>`).join("")}</div>
    <div class="actions"><button class="btn ghost sm" type="button" data-act="add">${I.plus}Add scene</button></div></div>
    <div class="field"><label>Description</label><textarea data-k="description">${esc(d.description)}</textarea></div>
    ${hasLinks ? `<div class="field"><label>Product / Affiliate links <span class="hint">· added to YouTube description (Produto 1: link)</span></label><textarea data-plinks placeholder="Produto 1: https://...&#10;Produto 2: https://...">${esc((d.product_links || []).join("\n"))}</textarea></div>` : ""}
    <div class="field"><label>Hashtags</label><input type="text" data-tags value="${esc((d.hashtags || []).join(" "))}"></div>
    <div class="go-row"><span></span><button class="btn primary" id="render-btn" type="button">${I.play}Render this script</button></div>
  </section>`;
  paint(box);
  box.oninput = e => {
    const el = e.target;
    if (el.dataset.k) d[el.dataset.k] = el.value;
    else if (el.dataset.s) d.scenes[+el.dataset.i][el.dataset.s] = el.value;
    else if (el.dataset.cast) { d.cast = d.cast || ["", ""]; d.cast[+el.dataset.cast] = el.value; }
    else if (el.hasAttribute("data-plinks")) d.product_links = el.value.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
    else if (el.hasAttribute("data-tags")) d.hashtags = el.value.split(/\s+/).filter(Boolean);
    const t = d.scenes.reduce((n, s) => n + words(s.narration), 0);
    $("#wc").textContent = `${t} words · ~${Math.round(t / 2.6)}s`;
    saveDraft();
  };
  box.onclick = e => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const n = +b.dataset.i, sc = d.scenes;
    if (b.dataset.act === "del" && sc.length > 1) sc.splice(n, 1);
    if (b.dataset.act === "up" && n > 0) [sc[n - 1], sc[n]] = [sc[n], sc[n - 1]];
    if (b.dataset.act === "down" && n < sc.length - 1) [sc[n + 1], sc[n]] = [sc[n], sc[n + 1]];
    if (b.dataset.act === "speaker") sc[n].speaker = sc[n].speaker === "B" ? "A" : "B";
    if (b.dataset.act === "add") sc.push({ narration: "", search_query: "", image_prompt: "", product: "", speaker: sc.length && sc[sc.length - 1].speaker === "A" && multi ? "B" : "A" });
    saveDraft();
    drawEditor();
  };
  const restore = $("#restore-draft");
  if (restore) restore.onclick = restorePreviousDraft;
  $("#discard").onclick = () => { if (confirm("Discard this script?")) { replaceDraft(null); drawEditor(); } };
  $("#render-btn").onclick = () => {
    const clean = Object.assign({}, d, { scenes: d.scenes.filter(s => s.narration.trim()) });
    if (!clean.scenes.length) return toast("The script has no narration.", "bad");
    startMake({ script: clean, topic: "", url: "", source: "" });
  };
}

// ------------------------------------------------------------------ LIBRARY
function viewLibrary() {
  $("#main").innerHTML = `
  <div class="page-head"><div><h1>Library</h1><p>Everything you've made. Click a video to watch, edit, upload or delete it.</p></div></div>
  <div class="toolbar">${seg("lib", [["", "All"], ["rendered", "Ready"], ["scheduled", "Scheduled"], ["uploaded", "Uploaded"], ["queued", "Queued"], ["failed", "Failed"], ["upload-unknown", "Check upload"]], S.lib.status)}
    <input type="search" id="lib-q" placeholder="Search titles" value="${esc(S.lib.q)}" aria-label="Search"></div>
  <div class="lib" id="lib"></div>`;
  $(".toolbar").addEventListener("click", e => {
    const b = e.target.closest("[data-seg]");
    if (!b) return;
    S.lib.status = b.dataset.v;
    $$("[data-seg=lib]").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.v === S.lib.status)));
    drawLibrary();
  });
  let t;
  $("#lib-q").oninput = e => { clearTimeout(t); t = setTimeout(() => { S.lib.q = e.target.value; drawLibrary(); }, 200); };
  drawLibrary();
}

async function drawLibrary() {
  const box = $("#lib");
  if (!box) return;
  let vs;
  try { vs = await get(`/api/videos?status=${encodeURIComponent(S.lib.status)}&q=${encodeURIComponent(S.lib.q)}`); } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  if (!vs.length) {
    box.innerHTML = `<div class="empty"><b>${S.lib.status || S.lib.q ? "Nothing matches" : "No videos yet"}</b>${S.lib.status || S.lib.q ? "Try another filter." : `<a href="#create">Create your first one</a>.`}</div>`;
    return;
  }
  box.innerHTML = vs.map(v => `
    <button class="vcard" type="button" data-open="${v.id}">
      <div class="thumb">${v.has_cover ? `<img src="/files/${v.id}/cover.jpg" alt="" loading="lazy">` : `<div class="ph">${v.status === "failed" ? "failed" : "no preview"}</div>`}
        <div class="tl"><span class="chip ${STATUS_CHIP[v.status] || ""}">${esc(v.status)}</span>${v.score != null ? `<span class="chip">${v.score}</span>` : ""}</div>
        ${v.duration ? `<span class="dur">${fmtSec(v.duration)}</span>` : ""}</div>
      <div class="meta"><b>${esc(shortTitle(v.title) || "(untitled)")}</b>
        <span class="sub">${esc(v.style || "")}${v.language ? ` · ${esc(v.language)}` : ""}${v.parent_id ? " · translation" : ""}${v.views != null ? ` · ${fmtNum(v.views)} views` : ""}</span>
        <span class="sub">${ago(v.created)}</span></div>
    </button>`).join("");
}

async function openVideo(id) {
  const opener = document.activeElement;
  let v;
  try { v = await get("/api/videos/" + id); } catch (e) { return toast(esc(e.message), "bad"); }
  const m = v.metadata || {}, sc = v.script;
  const panel = $("#drawer-panel");
  const review = m.review || [];
  panel.innerHTML = `
    <button class="btn ghost close" type="button" data-close aria-label="Close">${I.x}</button>
    <div class="player">${v.video ? `<video src="/files/${id}/${esc(v.video)}" controls playsinline preload="metadata"${v.has_cover ? ` poster="/files/${id}/cover.jpg"` : ""}></video>`
      : v.has_cover ? `<img src="/files/${id}/cover.jpg" alt="" class="thumb">` : `<div class="empty">The video file is gone${v.youtube_id ? " — it lives on YouTube now" : ""}.</div>`}
      <div class="actions">${v.video ? `<a class="btn sm" href="/files/${id}/${esc(v.video)}?download=1">${I.dl}MP4</a>` : ""}${v.has_srt ? `<a class="btn sm" href="/files/${id}/captions.srt?download=1">${I.dl}Captions</a>` : ""}</div>
    </div>
    <div>
      <div class="chips"><span class="chip ${STATUS_CHIP[v.status] || ""}">${esc(v.status)}</span>${v.style ? `<span class="chip">${esc(v.style)}</span>` : ""}${v.language ? `<span class="chip">${esc(v.language)}</span>` : ""}${v.parent_id ? `<span class="chip" data-open="${v.parent_id}">translation of #${v.parent_id}</span>` : ""}</div>
      <h2>${esc(v.title)}</h2>
      ${v.youtube_id ? `<p><a class="btn sm" href="https://youtube.com/shorts/${esc(v.youtube_id)}" target="_blank" rel="noopener">${I.yt}Open on YouTube</a>${v.publish_at ? ` <span class="muted">goes public ${esc(new Date(v.publish_at).toLocaleString())}</span>` : ""}</p>` : ""}
      ${v.error ? `<div class="banner">${I.info}<p>${esc(v.error)}</p></div>` : ""}
      <div class="actions">
        ${v.video && !v.youtube_id && !["unknown", "reserved", "uploading"].includes(v.upload_state) ? `<button class="btn primary sm" type="button" id="d-up">${I.upload}Upload</button>` : ""}
        ${sc ? `<button class="btn sm" type="button" id="d-edit">${I.pen}Edit & re-render</button>` : ""}
        <button class="btn sm danger" type="button" id="d-del">${I.trash}Delete</button>
      </div>
      ${v.upload_state === "unknown" ? `<p class="hint">Check your YouTube channel before trying again. Link the existing video, or confirm that no upload exists.</p>
        <div class="actions"><a class="btn sm" href="https://studio.youtube.com" target="_blank" rel="noopener">${I.yt}Check YouTube Studio</a>
          <button class="btn sm" type="button" id="d-link-upload">Link published video</button>
          <button class="btn sm" type="button" id="d-reset-upload">Confirm not uploaded</button></div>` : ""}
      ${v.score != null ? `<div class="score"><div class="ring" data-p="${v.score}"><b>${v.score}</b></div><div><b>Retention score</b>${review.length ? `<ul>${review.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div></div>` : ""}
      <dl class="kv">
        <dt>Length</dt><dd>${fmtSec(v.duration)}</dd>
        ${m.resolution ? `<dt>Size</dt><dd>${esc(m.resolution)}</dd>` : ""}
        <dt>Voice</dt><dd>${esc(v.voice || m.voice || "")}</dd>
        <dt>Script by</dt><dd>${esc(v.llm || "")}</dd>
        ${v.topic ? `<dt>Topic</dt><dd>${esc(v.topic)}</dd>` : ""}
        ${v.views != null ? `<dt>Views</dt><dd>${fmtNum(v.views)} · ${fmtNum(v.likes)} likes · ${fmtNum(v.comments)} comments</dd>` : ""}
        <dt>Made</dt><dd>${esc(new Date(v.created_at).toLocaleString())}</dd>
        <dt>Folder</dt><dd class="mono">${esc(v.folder || "")}</dd>
      </dl>
      <section id="video-costs" class="video-costs" aria-live="polite"><p class="hint">Loading resource usage…</p></section>
      ${v.description ? `<div class="desc">${esc(v.description)}</div>` : ""}
      ${v.tags && v.tags.length ? `<div class="chips">${v.tags.map(t => `<span class="chip">${esc(t)}</span>`).join("")}</div>` : ""}
    </div>`;
  paint(panel);
  loadVideoCosts(id, $("#video-costs", panel));
  showDrawer(opener);
  const up = $("#d-up");
  if (up) up.onclick = async () => { up.disabled = true; try { await post("/api/upload/" + id); toast("Upload queued — follow it in Queue.", "info"); tick(); } catch (e) { toast(esc(e.message), "bad"); } };
  const resolveUpload = async (button, body) => {
    button.disabled = true;
    try {
      await post(`/api/videos/${id}/resolve-upload`, body);
      toast("Upload resolved. No new upload was started.", "ok");
      await openVideo(id);
      drawLibrary();
    } catch (e) { toast(esc(e.message), "bad"); }
    finally { button.disabled = false; }
  };
  const linkUpload = $("#d-link-upload"), resetUpload = $("#d-reset-upload");
  if (linkUpload) linkUpload.onclick = () => {
    const youtubeId = prompt("Enter the existing YouTube video ID after checking that it is this video (not the URL):");
    if (youtubeId?.trim()) resolveUpload(linkUpload, { youtube_id: youtubeId.trim() });
  };
  if (resetUpload) resetUpload.onclick = () => {
    if (confirm("Have you checked YouTube and confirmed that this video was not uploaded? Allow another attempt only if no copy exists.")) {
      resolveUpload(resetUpload, { not_uploaded: true });
    }
  };
  const ed = $("#d-edit");
  if (ed) ed.onclick = () => {
    replaceDraft(Object.assign({}, sc, { title: (sc.title || "").replace(/\s*#shorts$/i, "") }), { source_video_id: id });
    if (sc.language) S.form.language = sc.language;
    if (sc.style) S.form.style = sc.style;
    S.form.speed = m.video_speed || 1;
    saveForm();
    closeDrawer();
    location.hash = "#create";
    if (S.view === "create") route();
  };
  $("#d-del").onclick = async () => {
    if (!confirm("Delete this video and its folder from your computer? (Nothing is removed from YouTube.)")) return;
    try { await post(`/api/videos/${id}/delete`); closeDrawer(); toast("Deleted.", "ok"); drawLibrary(); } catch (e) { toast(esc(e.message), "bad"); }
  };
}
let drawerOpener = null;
let drawerOpenerSelector = "";
function showDrawer(opener = document.activeElement) {
  const drawer = $("#drawer");
  if (drawer.hidden) {
    drawerOpener = opener;
    drawerOpenerSelector = opener.id ? "#" + CSS.escape(opener.id)
      : opener.dataset.costVideo ? `[data-cost-video="${CSS.escape(opener.dataset.costVideo)}"]`
      : opener.dataset.open ? `[data-open="${CSS.escape(opener.dataset.open)}"]` : "";
  }
  drawer.hidden = false;
  $(".app").inert = true;
  document.body.style.overflow = "hidden";
  $("#drawer-panel [data-close]")?.focus();
}
function closeDrawer() {
  const d = $("#drawer");
  if (d.hidden) return;
  $$("video", d).forEach(v => v.pause());
  d.hidden = true;
  $(".app").inert = false;
  document.body.style.overflow = "";
  const replacement = drawerOpenerSelector ? document.querySelector(drawerOpenerSelector) : null;
  (drawerOpener?.isConnected ? drawerOpener : replacement || $("#main"))?.focus({ preventScroll: true });
}

// ------------------------------------------------------------------ QUEUE
const openLogs = new Set();
function viewQueue() {
  $("#main").innerHTML = `<div class="page-head"><div><h1>Queue</h1><p>Jobs run one at a time, in order. Each shows its live stage and log.</p></div></div><div class="jobs" id="jobs"></div>`;
  drawJobs();
}
function drawJobs() {
  const box = $("#jobs");
  if (!box) return;
  if (!S.jobs.length) { box.innerHTML = `<div class="empty"><b>Nothing running</b>Jobs you start from Create, Ideas or Clip show up here.</div>`; return; }
  const scroll = {};
  $$(".log", box).forEach(l => { scroll[l.dataset.id] = l.scrollHeight - l.scrollTop - l.clientHeight < 30; });
  box.innerHTML = S.jobs.map(j => {
    const r = j.result || {};
    const running = j.status === "running";
    const open = running || openLogs.has(j.id);
    const took = j.started ? Math.round(((j.finished || Date.now() / 1000) - j.started)) : null;
    const stage = (STAGES.find(([k]) => k === j.stage) || [0, j.stage])[1];
    return `<div class="job ${j.status}">
      <div class="job-top"><span class="kind">${KIND_ICON[j.kind] || I.film}</span>
        <div class="t"><b>${esc(r.title || j.label)}</b><small><span class="status-pill ${j.status}">${j.status}</span>${running && stage ? ` · ${esc(stage)}` : ""}${running && j.message ? ` · ${esc(j.message)}` : ""}${took != null ? ` · ${fmtSec(took)}` : ""}</small></div>
        ${j.status === "queued" ? `<button class="btn ghost sm" type="button" data-cancel="${j.id}">Cancel</button>` : ""}
        ${j.status === "done" && r.id ? `<button class="btn sm" type="button" data-open="${r.id}">${I.play}Watch</button>` : ""}
        ${j.status === "done" && j.kind === "draft" ? `<a class="btn sm" href="#create">${I.pen}Edit</a>` : ""}
        <button class="btn ghost sm" type="button" data-log="${j.id}">${open ? "Hide log" : "Log"}</button>
      </div>
      ${j.status !== "cancelled" ? `<div class="pbar"><i data-w="${j.status === "failed" ? 100 : j.pct}"></i></div>` : ""}
      ${r.error ? `<div class="err">${esc(r.error)}</div>` : ""}
      ${r.clips ? `<div class="chips">${r.clips.map(c => `<span class="chip ${c.ok ? "ok" : "bad"}"${c.id ? ` data-open="${c.id}"` : ""}>${esc(c.title || "clip")}</span>`).join("")}</div>` : ""}
      ${open ? `<pre class="log" data-id="${j.id}">${esc(j.log.join("\n")) || "…"}</pre>` : ""}
    </div>`;
  }).join("");
  paint(box);
  $$(".log", box).forEach(l => { if (scroll[l.dataset.id] !== false) l.scrollTop = l.scrollHeight; });
  box.onclick = async e => {
    const lg = e.target.closest("[data-log]");
    if (lg) { const id = +lg.dataset.log; openLogs.has(id) ? openLogs.delete(id) : openLogs.add(id); drawJobs(); }
    const c = e.target.closest("[data-cancel]");
    if (c) { await post(`/api/jobs/${c.dataset.cancel}/cancel`).catch(() => {}); tick(); }
  };
}

// ------------------------------------------------------------------ IDEAS
async function viewIdeas() {
  const main = $("#main");
  let data;
  try { data = await get("/api/ideas"); } catch (e) { main.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  if (S.view !== "ideas") return;
  const styles = [["", "Any format"], ...FORMATS.filter(([k]) => k !== "auto").map(([k, n]) => [k, n])];
  main.innerHTML = `
  <div class="page-head"><div><h1>Ideas</h1><p>Plan a week of videos in one go. The autopilot and Create → Idea queue always use these first, oldest first.</p></div></div>
  <div class="grid2">
    <section class="card"><h2>Plan with AI</h2>
      <div class="field"><label>Niche (optional)</label><input type="text" id="plan-niche" placeholder="e.g. space and the universe — blank uses your NICHES"></div>
      <div class="field"><label>How many</label><div class="range-row"><input type="range" id="plan-n" min="3" max="30" value="10"><output id="plan-out">10</output></div></div>
      <div class="actions end"><button class="btn primary" id="plan-go" type="button">${I.spark}Plan ideas</button></div>
    </section>
    <section class="card"><h2>Add your own</h2>
      <div class="field"><label>Idea</label><input type="text" id="idea-s" placeholder="e.g. The man who survived two atomic bombs"></div>
      <div class="field"><label>Format</label><select id="idea-f">${styles.map(([k, n]) => `<option value="${k}">${n}</option>`).join("")}</select></div>
      <div class="actions end"><button class="btn" id="idea-add" type="button">${I.plus}Add to queue</button></div>
    </section>
  </div>
  <section class="card"><h2>Queue · ${data.pending.length}</h2>
    ${data.pending.length ? `<div class="list">${data.pending.map(i => `
      <div class="item"><span class="chip ${i.style ? "accent" : ""}">${esc(i.style || "auto")}</span>
        <div class="grow"><b>${esc(i.subject)}</b>${i.notes ? `<small>${esc(i.notes)}</small>` : ""}</div>
        <button class="btn sm" type="button" data-make="${i.id}">${I.play}Make now</button>
        <button class="btn ghost sm" type="button" data-del="${i.id}" aria-label="Remove">${I.trash}</button></div>`).join("")}</div>`
      : `<div class="empty"><b>The queue is empty</b>Plan some ideas with AI, or add your own.</div>`}
  </section>
  ${data.used.length ? `<section class="card"><h2>Recently made</h2><div class="list">${data.used.map(i => `
      <div class="item"><span class="chip">${esc(i.style || "auto")}</span><div class="grow"><b>${esc(i.subject)}</b><small>${ago(i.used_at)}</small></div>
      ${i.video_id ? `<button class="btn ghost sm" type="button" data-open="${i.video_id}">${I.play}Watch</button>` : ""}</div>`).join("")}</div></section>` : ""}`;
  $("#plan-n").oninput = e => { $("#plan-out").textContent = e.target.value; };
  $("#plan-go").onclick = async () => {
    try { await post("/api/plan", { count: +$("#plan-n").value, niche: $("#plan-niche").value,
      provider: S.form.provider, model: S.form.model, ...modelPayload() }); toast("Planning ideas… (see Queue)", "info"); tick(); }
    catch (e) { toast(esc(e.message), "bad"); }
  };
  $("#idea-add").onclick = async () => {
    const s = $("#idea-s").value.trim();
    if (!s) return;
    try { await post("/api/ideas", { subject: s, style: $("#idea-f").value }); viewIdeas(); refreshInfo(); } catch (e) { toast(esc(e.message), "bad"); }
  };
  main.onclick = async e => {
    const d = e.target.closest("[data-del]"), m = e.target.closest("[data-make]");
    if (d) { await post(`/api/ideas/${d.dataset.del}/delete`).catch(() => {}); viewIdeas(); refreshInfo(); }
    if (m) {
      const idea = data.pending.find(i => i.id === +m.dataset.make);
      try { await post("/api/make", payload({ idea_id: idea.id, topic: "", url: "", source: "queue", style: idea.style || "" })); toast("Making it now — see Queue.", "info"); tick(); viewIdeas(); refreshInfo(); }
      catch (err) { toast(esc(err.message), "bad"); }
    }
  };
}
async function refreshInfo() { try { S.info = await get("/api/info"); status(); } catch { /* ignore */ } }

// ------------------------------------------------------------------ PRODUCTS (GARIMPO)
const PLAT_CHIP = { shopify: "ok", nuvemshop: "blue", woocommerce: "accent" };

async function viewProducts() {
  const main = $("#main");
  const pr = S.prod;
  let data;
  try {
    const q = new URLSearchParams({ platform: pr.platform, sort: pr.sort, q: pr.q, starred: pr.starred ? "1" : "" });
    data = await get("/api/products?" + q.toString());
  } catch (e) { main.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  if (S.view !== "products") return;
  S.prodData = data;
  const stores = data.stores || [];
  main.innerHTML = `
  <div class="page-head"><div><h1>Products · Garimpo Viral</h1><p>Descubra os produtos mais vendidos em lojas Shopify, Nuvemshop e WooCommerce com dossiê criativo de IA e links de afiliado prontos para postar.</p></div></div>
  <div class="grid2">
    <section class="card" id="scout-card"></section>
    <section class="card">
      <h2>Lojas Favoritas · ${stores.length}</h2>
      <div class="store-list" id="store-list">
        ${stores.length ? stores.map(st => `
          <div class="item">
            <span class="chip ${PLAT_CHIP[st.platform] || ""}">${esc(st.platform)}</span>
            <div class="grow">
              <b><a href="${esc(st.url)}" target="_blank" rel="noopener">${esc(st.name)}</a></b>
              <small>${esc(st.niche || st.url)}${st.last_scouted_at ? ` · garimpada ${ago(st.last_scouted_at)}` : ""}</small>
            </div>
            <button class="btn sm" type="button" data-scout-store="${st.id}">${I.spark}Garimpar</button>
            <button class="btn ghost sm" type="button" data-del-store="${st.id}" aria-label="Remover loja">${I.trash}</button>
          </div>`).join("") : `<div class="empty">Nenhuma loja cadastrada.</div>`}
      </div>
      <details class="more">
        <summary>Adicionar loja (Shopify, Nuvemshop ou WooCommerce)</summary>
        <div class="grid2">
          <div class="field"><label>URL da loja</label><input type="url" id="st-url" placeholder="https://sualoja.com.br"></div>
          <div class="field"><label>Nome (opcional)</label><input type="text" id="st-name" placeholder="Ex: Achadinhos Casa"></div>
        </div>
        <div class="grid2">
          <div class="field"><label>Plataforma</label><select id="st-plat"><option value="">Auto-detectar</option><option value="shopify">Shopify</option><option value="nuvemshop">Nuvemshop</option><option value="woocommerce">WooCommerce</option></select></div>
          <div class="field"><label>Nicho</label><input type="text" id="st-niche" placeholder="Ex: casa & cozinha"></div>
        </div>
        <div class="actions end"><button class="btn sm" id="st-add" type="button">${I.plus}Salvar loja</button></div>
      </details>
    </section>
  </div>
  <div id="psel-bar"></div>
  <div class="toolbar" id="ptoolbar">
    ${seg("p-plat", [["", "Todas"], ["shopify", "Shopify"], ["nuvemshop", "Nuvemshop"], ["woocommerce", "WooCommerce"]], pr.platform)}
    ${seg("p-sort", [["viral", "Maior Viral Score"], ["rank", "Mais Vendidos (#Rank)"], ["discount", "Maior Desconto"], ["recent", "Recentes"]], pr.sort)}
    <button class="btn sm${pr.starred ? " primary" : ""}" id="p-star-btn" type="button" aria-pressed="${pr.starred}">${I.star}Favoritos</button>
    <input type="search" id="p-q" placeholder="Buscar produto, dor ou gancho…" value="${esc(pr.q)}" aria-label="Buscar produtos">
  </div>
  <div class="pgrid" id="pgrid"></div>`;
  drawScoutCard(stores);
  drawProductSelectionBar();
  drawProductsGrid(data.products || []);
  bindProductsView();
}

function drawScoutCard(stores) {
  const box = $("#scout-card");
  if (!box) return;
  const pr = S.prod;
  const storeOpts = [["", "Todas as lojas favoritas (Top Best-Sellers)"], ...stores.map(s => [String(s.id), `${s.name} (${s.platform})`])];
  box.innerHTML = `
    <h2>Garimpar produtos com IA</h2>
    <div class="src-tabs">${seg("scout-mode", [["stores", "Lojas Virais"], ["search", "Buscar Nicho"], ["url", "URL Direta"]], pr.mode)}</div>
    ${pr.mode === "stores" ? `
      <div class="field"><label>Fonte</label><select id="ps-store">${storeOpts.map(([v, l]) => `<option value="${esc(v)}"${String(v) === String(pr.store_id) ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>
        <p class="hint">Extrai o ranking de mais vendidos (<span class="mono">best-selling</span> / popularidade), fotos, vídeos e cria o dossiê de roteiro.</p></div>
      <div class="field"><label>Quantos produtos</label><div class="range-row"><input type="range" id="ps-limit" min="3" max="16" value="${pr.limit}"><output id="ps-limit-out">${pr.limit}</output></div></div>`
    : pr.mode === "search" ? `
      <div class="grid2">
        <div class="field"><label>Nicho ou palavra-chave</label><input type="text" id="ps-query" value="${esc(pr.query)}" placeholder="ex: gadgets cozinha, pet, limpeza"></div>
        <div class="field"><label>Plataforma</label><select id="ps-plat"><option value="">Todas (Shopify + Nuvemshop + Woo)</option><option value="shopify"${pr.scout_plat === "shopify" ? " selected" : ""}>Shopify</option><option value="nuvemshop"${pr.scout_plat === "nuvemshop" ? " selected" : ""}>Nuvemshop</option><option value="woocommerce"${pr.scout_plat === "woocommerce" ? " selected" : ""}>WooCommerce</option></select></div>
      </div>
      <div class="field"><label>Quantos produtos</label><div class="range-row"><input type="range" id="ps-limit" min="3" max="16" value="${pr.limit}"><output id="ps-limit-out">${pr.limit}</output></div></div>`
    : `
      <div class="field"><label>URL de produto ou loja</label><input type="url" id="ps-url" value="${esc(pr.url)}" placeholder="https://… página de produto ou loja Shopify / Nuvemshop / WooCommerce">
        <p class="hint">Se for link de loja, garimpa os mais vendidos; se for link de produto, extrai fotos, vídeo MP4, preço e dossiê.</p></div>`}
    <div class="actions end"><button class="btn primary" id="ps-go" type="button">${I.spark}Garimpar agora</button></div>`;
  box.onclick = e => {
    const b = e.target.closest("[data-seg=scout-mode]");
    if (b) { pr.mode = b.dataset.v; drawScoutCard(stores); }
  };
  const lim = $("#ps-limit", box);
  if (lim) lim.oninput = e => { pr.limit = +e.target.value; $("#ps-limit-out", box).textContent = pr.limit; };
  const st = $("#ps-store", box);
  if (st) st.onchange = e => { pr.store_id = e.target.value; };
  const q = $("#ps-query", box);
  if (q) q.oninput = e => { pr.query = e.target.value; };
  const pl = $("#ps-plat", box);
  if (pl) pl.onchange = e => { pr.scout_plat = e.target.value; };
  const u = $("#ps-url", box);
  if (u) u.oninput = e => { pr.url = e.target.value; };
  $("#ps-go", box).onclick = async e => {
    const btn = e.currentTarget;
    if (btn.disabled) return;
    if (pr.mode === "search" && !pr.query.trim()) return toast("Digite um nicho ou palavra-chave para buscar.", "bad");
    if (pr.mode === "url" && !pr.url.trim()) return toast("Cole a URL do produto ou da loja.", "bad");
    btn.disabled = true;
    try {
      await post("/api/products/scout", {
        mode: pr.mode, store_id: pr.store_id, query: pr.query, platform: pr.scout_plat, url: pr.url, limit: pr.limit,
        provider: S.form.provider, model: S.form.model, ...modelPayload(),
      });
      toast("Garimpando produtos e gerando dossiê viral… acompanhe em Queue.", "info");
      tick();
    } catch (err) { toast(esc(err.message), "bad"); }
    finally { btn.disabled = false; }
  };
}

function drawProductSelectionBar() {
  const bar = $("#psel-bar");
  if (!bar) return;
  const sel = S.prod.selected;
  if (!sel.length) { bar.innerHTML = ""; return; }
  const all = (S.prodData && S.prodData.products) || [];
  const items = sel.map((id, i) => {
    const p = all.find(x => x.id === id);
    return `<span class="chip accent">${i + 1}. ${esc(p ? (p.short_name || p.title.slice(0, 20)) : "#" + id)}</span>`;
  }).join("");
  bar.innerHTML = `<section class="card psel-bar">
    <div class="grow">
      <b>${sel.length === 1 ? "1 produto selecionado (Review único)" : `${sel.length} produtos selecionados (Vídeo compilado “Top Achadinhos”)`}</b>
      <div class="chips">${items}</div>
    </div>
    <div class="actions">
      <button class="btn sm" type="button" id="psel-draft">${I.pen}Draft script (${sel.length})</button>
      <button class="btn sm primary" type="button" id="psel-make">${I.play}Create video (${sel.length})</button>
      <button class="btn sm" type="button" id="psel-queue">${I.plus}Add to Idea Queue</button>
      <button class="btn sm ghost" type="button" id="psel-clear">${I.x}Limpar</button>
    </div>
  </section>`;
  $("#psel-draft", bar).onclick = () => startProductVideo([...sel], true);
  $("#psel-make", bar).onclick = () => startProductVideo([...sel], false);
  $("#psel-queue", bar).onclick = () => queueProductIdea([...sel]);
  $("#psel-clear", bar).onclick = () => { S.prod.selected = []; drawProductSelectionBar(); drawProductsGrid((S.prodData && S.prodData.products) || []); };
}

function drawProductsGrid(products) {
  const box = $("#pgrid");
  if (!box) return;
  if (!products.length) {
    box.innerHTML = `<div class="empty"><b>Nenhum produto encontrado</b>Clique em <b>Garimpar agora</b> acima para buscar os produtos mais vendidos das lojas Shopify, Nuvemshop e WooCommerce.</div>`;
    return;
  }
  const sel = S.prod.selected;
  box.innerHTML = products.map(p => {
    const img = (p.images && p.images[0]) || "";
    const selIdx = sel.indexOf(p.id);
    const vscore = p.viral_score || 0;
    return `<article class="pcard${selIdx >= 0 ? " selected" : ""}">
      <div class="pthumb">
        ${img ? `<img src="${esc(img)}" alt="" loading="lazy">` : `<div class="ph">Sem imagem</div>`}
        <div class="tl">
          <button type="button" class="psel-btn${selIdx >= 0 ? " on" : ""}" data-psel="${p.id}" title="Selecionar para vídeo (1 a 5 produtos)">${selIdx >= 0 ? selIdx + 1 : "+"}</button>
          <span class="chip ${PLAT_CHIP[p.platform] || ""}">${esc(p.platform || "web")}</span>
          ${p.best_seller_rank ? `<span class="chip accent">#${p.best_seller_rank} Top</span>` : ""}
          ${p.discount_pct > 0 ? `<span class="chip ok">-${p.discount_pct}%</span>` : ""}
          ${p.videos && p.videos.length ? `<span class="chip blue">MP4</span>` : ""}
        </div>
        <button type="button" class="pstar${p.starred ? " on" : ""}" data-pstar="${p.id}" aria-label="Favoritar">${I.star}</button>
        <div class="br"><span class="chip ${vscore >= 75 ? "ok" : vscore >= 55 ? "accent" : ""}">Viral ${vscore}</span></div>
      </div>
      <div class="pbody">
        <div class="phead">
          <span class="chip accent" title="Nome curto no badge do topo">${esc(p.short_name || p.title.slice(0, 22))}</span>
          <span class="sub">${esc(p.store_name || "")}</span>
        </div>
        <a class="ptitle" href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a>
        <div class="pprice">
          <b>${esc(p.price || "Consultar")}</b>
          ${p.compare_price ? `<del>${esc(p.compare_price)}</del>` : ""}
          ${p.rating ? `<span class="sub">★ ${p.rating}${p.reviews_count ? ` (${fmtNum(p.reviews_count)})` : ""}</span>` : ""}
        </div>
        <div class="pdossier">
          ${p.pain_point ? `<div class="pd-row"><b>Dor:</b> <span>${esc(p.pain_point)}</span></div>` : ""}
          ${p.hook_idea ? `<div class="pd-row"><b>Gancho 2s:</b> <span>“${esc(p.hook_idea)}”</span></div>` : ""}
          ${p.visual_angle ? `<div class="pd-row"><b>Cena:</b> <span>${esc(p.visual_angle)}</span></div>` : ""}
          ${p.benefits && p.benefits.length ? `<div class="chips">${p.benefits.slice(0, 3).map(b => `<span class="chip">${esc(b)}</span>`).join("")}</div>` : ""}
        </div>
        <div class="paff">
          <label>${I.link}<span>Link de afiliado (descrição do vídeo)</span></label>
          <div class="paff-row">
            <input type="url" data-paff="${p.id}" value="${esc(S.affiliateDrafts[p.id] ?? p.affiliate_url ?? "")}" placeholder="https://s.shopee.com.br/... ou link de afiliado">
            <button class="btn ghost sm" type="button" data-paff-save="${p.id}">Salvar</button>
          </div>
        </div>
        <div class="pactions">
          <button class="btn sm" type="button" data-pdraft="${p.id}">${I.pen}Draft</button>
          <button class="btn sm primary" type="button" data-pmake="${p.id}">${I.play}Make video</button>
          <button class="btn ghost sm" type="button" data-pqueue="${p.id}" title="Enviar para a fila Ideas">${I.plus}Queue</button>
          ${p.video_id ? `<button class="btn ghost sm" type="button" data-open="${p.video_id}" title="Assistir vídeo gerado">${I.film}</button>` : ""}
          <button class="btn ghost sm" type="button" data-pdel="${p.id}" aria-label="Excluir">${I.trash}</button>
        </div>
      </div>
    </article>`;
  }).join("");
}

async function refreshProductsList() {
  const pr = S.prod;
  try {
    const q = new URLSearchParams({ platform: pr.platform, sort: pr.sort, q: pr.q, starred: pr.starred ? "1" : "" });
    S.prodData = await get("/api/products?" + q.toString());
    drawProductsGrid(S.prodData.products || []);
    drawProductSelectionBar();
  } catch (e) { toast(esc(e.message), "bad"); }
}

function bindProductsView() {
  const main = $("#main");
  const pr = S.prod;
  let searchTimer;
  const pq = $("#p-q");
  if (pq) pq.oninput = e => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { pr.q = e.target.value; refreshProductsList(); }, 200); };
  const starBtn = $("#p-star-btn");
  if (starBtn) starBtn.onclick = () => {
    pr.starred = !pr.starred;
    starBtn.classList.toggle("primary", pr.starred);
    starBtn.setAttribute("aria-pressed", String(pr.starred));
    refreshProductsList();
  };
  const stAdd = $("#st-add");
  if (stAdd) stAdd.onclick = async () => {
    const url = ($("#st-url")?.value || "").trim();
    if (!url) return toast("Informe a URL da loja.", "bad");
    try {
      await post("/api/products/stores", {
        url, name: ($("#st-name")?.value || "").trim(),
        platform: $("#st-plat")?.value || "", niche: ($("#st-niche")?.value || "").trim(),
      });
      toast("Loja adicionada!", "ok");
      viewProducts();
    } catch (e) { toast(esc(e.message), "bad"); }
  };
  main.oninput = e => {
    const aff = e.target.closest("[data-paff]");
    if (aff) {
      S.affiliateDrafts[aff.dataset.paff] = aff.value;
      store.set("affiliateDrafts", S.affiliateDrafts);
    }
  };
  main.onchange = async e => {
    const aff = e.target.closest("[data-paff]");
    if (aff) {
      const id = +aff.dataset.paff;
      const val = aff.value.trim();
      try {
        await saveAffiliate(id, val);
        toast("Link de afiliado salvo.", "ok", 2200);
      } catch (err) { toast(esc(err.message), "bad"); }
    }
  };
  main.onclick = async e => {
    const segBtn = e.target.closest("[data-seg]");
    if (segBtn && (segBtn.dataset.seg === "p-plat" || segBtn.dataset.seg === "p-sort")) {
      const k = segBtn.dataset.seg === "p-plat" ? "platform" : "sort";
      pr[k] = segBtn.dataset.v;
      $$(`[data-seg="${segBtn.dataset.seg}"]`, main).forEach(x => x.setAttribute("aria-pressed", String(x.dataset.v === pr[k])));
      refreshProductsList();
      return;
    }
    const scStore = e.target.closest("[data-scout-store]");
    if (scStore) {
      if (scStore.disabled) return;
      scStore.disabled = true;
      try {
        await post("/api/products/scout", { mode: "stores", store_id: +scStore.dataset.scoutStore, limit: pr.limit,
          provider: S.form.provider, model: S.form.model, ...modelPayload() });
        toast("Garimpando loja… acompanhe em Queue.", "info");
        tick();
      } catch (err) { toast(esc(err.message), "bad"); }
      finally { scStore.disabled = false; }
      return;
    }
    const delStore = e.target.closest("[data-del-store]");
    if (delStore) {
      await post(`/api/products/stores/${delStore.dataset.delStore}/delete`).catch(() => {});
      viewProducts();
      return;
    }
    const selBtn = e.target.closest("[data-psel]");
    if (selBtn) {
      const id = +selBtn.dataset.psel;
      const idx = pr.selected.indexOf(id);
      if (idx >= 0) pr.selected.splice(idx, 1);
      else if (pr.selected.length >= 5) return toast("Selecione no máximo 5 produtos para um Short compilado.", "bad");
      else pr.selected.push(id);
      drawProductSelectionBar();
      drawProductsGrid((S.prodData && S.prodData.products) || []);
      return;
    }
    const star = e.target.closest("[data-pstar]");
    if (star) {
      const id = +star.dataset.pstar;
      try {
        const { starred } = await post(`/api/products/${id}/star`);
        const item = (S.prodData?.products || []).find(x => x.id === id);
        if (item) item.starred = starred;
        drawProductsGrid((S.prodData && S.prodData.products) || []);
      } catch (err) { toast(esc(err.message), "bad"); }
      return;
    }
    const affSave = e.target.closest("[data-paff-save]");
    if (affSave) {
      const id = +affSave.dataset.paffSave;
      const input = $(`[data-paff="${id}"]`, main);
      if (input) {
        const val = input.value.trim();
        try {
          await saveAffiliate(id, val);
          toast("Link de afiliado salvo.", "ok", 2200);
        } catch (err) { toast(esc(err.message), "bad"); }
      }
      return;
    }
    const pdraft = e.target.closest("[data-pdraft]");
    if (pdraft) { startProductVideo([+pdraft.dataset.pdraft], true); return; }
    const pmake = e.target.closest("[data-pmake]");
    if (pmake) { startProductVideo([+pmake.dataset.pmake], false); return; }
    const pqueue = e.target.closest("[data-pqueue]");
    if (pqueue) { queueProductIdea([+pqueue.dataset.pqueue]); return; }
    const pdel = e.target.closest("[data-pdel]");
    if (pdel) {
      const id = +pdel.dataset.pdel;
      await post(`/api/products/${id}/delete`).catch(() => {});
      pr.selected = pr.selected.filter(x => x !== id);
      refreshProductsList();
      refreshInfo();
    }
  };
}

const affiliateSaves = new Map();
function saveAffiliate(id, value) {
  const pending = affiliateSaves.get(id);
  if (pending?.value === value) return pending.promise;
  const promise = (pending?.promise || Promise.resolve()).catch(() => {}).then(async () => {
    await post(`/api/products/${id}/affiliate`, { affiliate_url: value });
    const item = (S.prodData?.products || []).find(x => x.id === id);
    if (item) item.affiliate_url = value;
    if (S.affiliateDrafts[id]?.trim() === value) {
      delete S.affiliateDrafts[id];
      store.set("affiliateDrafts", S.affiliateDrafts);
    }
  });
  affiliateSaves.set(id, { value, promise });
  const clear = () => { if (affiliateSaves.get(id)?.promise === promise) affiliateSaves.delete(id); };
  promise.then(clear, clear);
  return promise;
}

async function flushAffiliateInputs(ids) {
  const main = $("#main");
  if (!main) return;
  const products = (S.prodData && S.prodData.products) || [];
  for (const id of ids) {
    const input = $(`[data-paff="${id}"]`, main);
    const raw = input ? input.value : S.affiliateDrafts[id];
    if (raw == null) {
      if (affiliateSaves.has(id)) await affiliateSaves.get(id).promise;
      continue;
    }
    const val = raw.trim();
    const item = products.find(x => x.id === id);
    if (affiliateSaves.has(id) || !item || (item.affiliate_url || "") !== val) {
      try {
        await saveAffiliate(id, val);
      } catch (e) {
        input?.focus();
        throw new Error(`O link de afiliado não foi salvo. Corrija ou tente novamente antes de produzir. ${e.message}`);
      }
    }
  }
}

async function startProductVideo(ids, draftOnly = false) {
  if (_jobLaunchBusy) return;
  _jobLaunchBusy = true;
  try {
    await flushAffiliateInputs(ids);
    S.form.style = "product";
    saveForm();
    if (location.hash !== "#create") location.hash = "#create";
    if (S.view !== "create") route();
  } catch (e) { toast(esc(e.message), "bad"); return; }
  finally { _jobLaunchBusy = false; }
  const extra = { product_ids: ids, style: "product", topic: "", url: "", source: "" };
  if (draftOnly) await startDraft(extra);
  else await startMake(extra);
}

async function queueProductIdea(ids) {
  if (_jobLaunchBusy) return;
  _jobLaunchBusy = true;
  try {
    await flushAffiliateInputs(ids);
    await post("/api/ideas", { product_ids: ids, style: "product" });
    toast("Produto(s) adicionado(s) na fila de Ideas!", "ok");
    refreshInfo();
  } catch (e) { toast(esc(e.message), "bad"); }
  finally { _jobLaunchBusy = false; }
}

// ------------------------------------------------------------------ CLIP
function viewClip() {
  const c = Object.assign({ source: "", count: 3, crop: "center", upload: false,
    speed: S.info.speed || 1,
    model: S.info.llm_models?.clip || "", transcription_model: S.info.clip_transcription_model || "" }, store.get("clip", {}));
  $("#main").innerHTML = `
  <div class="page-head"><div><h1>Clip a long video</h1><p>Turn a podcast, interview, talk or stream into Shorts of its best moments.</p></div></div>
  <div class="create">
    <section class="card"><h2>Source</h2>
      <div class="field"><label>Video file or URL</label><input type="text" id="c-src" value="${esc(c.source)}" placeholder="/Users/me/Videos/podcast.mp4  or  https://…"><p class="hint">Local files work out of the box. URLs need <span class="mono">pip install yt-dlp</span>. Only clip videos you own or may reuse.</p></div>
      <div class="grid2">
        <div class="field"><label>Clips</label><div class="range-row"><input type="range" id="c-n" min="1" max="10" value="${c.count}"><output id="c-out">${c.count}</output></div></div>
        <div class="field"><label>Framing</label>${seg("crop", [["center", "Fill (crop)"], ["blur", "Fit + blur"]], c.crop)}</div>
      </div>
      <div class="field"><label for="c-speed">Final video speed</label><div class="range-row"><input type="range" id="c-speed" min="0.5" max="2" step="0.05" value="${c.speed}" aria-describedby="c-speed-hint"><output id="c-speed-out">${+Number(c.speed).toFixed(2)}×</output></div><p class="hint" id="c-speed-hint">Applied after selecting moments. Audio keeps its pitch and captions stay synchronized.</p></div>
      <div class="field"><label>Model for choosing clips</label><input type="text" id="c-model" value="${esc(c.model)}" placeholder="inherit default"></div>
      <div class="field"><label>OpenRouter transcription model (optional)</label><input type="text" id="c-transcription-model" value="${esc(c.transcription_model)}" placeholder="e.g. elevenlabs/scribe-v2"><p class="hint">Requires word-level timestamps. Blank uses faster-whisper or OpenAI.</p></div>
      <div class="field"><label class="switch"><input type="checkbox" id="c-up"${c.upload ? " checked" : ""}${S.info.upload ? "" : " disabled"}><span>Upload the clips when done</span></label></div>
      <div class="actions end"><button class="btn primary" id="c-go" type="button">${I.scissors}Find the best moments</button></div>
    </section>
    <section class="card"><h2>How it works</h2><div class="list">
      <div class="item"><span class="chip accent">1</span><div class="grow"><b>Transcribe</b><small>Word-level timing with faster-whisper, OpenAI, or the optional OpenRouter model.</small></div></div>
      <div class="item"><span class="chip accent">2</span><div class="grow"><b>AI picks the moments</b><small>Self-contained, 20–58 s, a hook in the first line and a payoff at the end. Each gets a title and a retention score.</small></div></div>
      <div class="item"><span class="chip accent">3</span><div class="grow"><b>Vertical, captioned, loud enough</b><small>9:16 crop or blurred fit, word-by-word captions, hook title, loudness to −14 LUFS.</small></div></div>
    </div></section>
  </div>`;
  const save = () => store.set("clip", c);
  $("#c-n").oninput = e => { c.count = +e.target.value; $("#c-out").textContent = c.count; save(); };
  $("#c-speed").oninput = e => { c.speed = +e.target.value; $("#c-speed-out").textContent = `${+c.speed.toFixed(2)}×`; save(); };
  $("#c-src").oninput = e => { c.source = e.target.value; save(); };
  $("#c-model").oninput = e => { c.model = e.target.value; save(); };
  $("#c-transcription-model").oninput = e => { c.transcription_model = e.target.value; save(); };
  $("#c-up").onchange = e => { c.upload = e.target.checked; save(); };
  $("#main").onclick = e => {
    const b = e.target.closest("[data-seg=crop]");
    if (b) { c.crop = b.dataset.v; $$("[data-seg=crop]").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.v === c.crop))); save(); }
  };
  $("#c-go").onclick = async () => {
    if (!c.source.trim()) return toast("Give a video file path or URL.", "bad");
    try { await post("/api/clip", { source: c.source.trim(), count: c.count, crop: c.crop, upload: c.upload, speed: c.speed,
      provider: S.form.provider, model: S.form.model, ...modelPayload(),
      model_clip: c.model, clip_transcription_model: c.transcription_model }); toast("Clipping… follow it in Queue.", "info"); tick(); }
    catch (e) { toast(esc(e.message), "bad"); }
  };
}

// ------------------------------------------------------------------ CHANNEL
async function viewChannel() {
  const main = $("#main");
  let ch;
  try { [ch, S.info] = await Promise.all([get("/api/channel"), get("/api/info")]); } catch (e) { main.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  if (S.view !== "channel") return;
  const i = S.info, cnt = i.counts || {};
  const live = (cnt.uploaded || 0) + (cnt.scheduled || 0);
  const top = Math.max(1, ...ch.by_style.map(s => s.avg_views));
  main.innerHTML = `
  <div class="page-head"><div><h1>Channel</h1><p>How your uploads are doing${ch.synced ? ` · stats from ${ago(ch.synced)}` : ""}.</p></div>
    <button class="btn" id="sync" type="button">${I.refresh}Refresh stats</button></div>
  ${i.learn_from_stats ? "" : `<div class="banner">${I.spark}<p>Set <span class="mono">LEARN_FROM_STATS=true</span> in .env and new scripts will learn from what performs best here. Add <span class="mono">YOUTUBE_API_KEY</span> (or run <span class="mono">purffle-shorts auth</span> again) so stats can be read.</p></div>`}
  <div class="kpis">
    <div class="kpi"><small>Videos made</small><b>${fmtNum(i.total)}</b></div>
    <div class="kpi"><small>On YouTube</small><b>${fmtNum(live)}</b></div>
    <div class="kpi"><small>Total views</small><b>${fmtNum(i.views)}</b></div>
    <div class="kpi"><small>Ideas queued</small><b>${fmtNum(i.ideas)}</b></div>
  </div>
  ${ch.videos.length ? `<div class="grid2">
    <section class="card"><h2>Average views by format</h2>${ch.by_style.map(s => `<div class="hbar"><span>${esc(s.style)}</span><span class="track"><i data-w="${100 * s.avg_views / top}"></i></span><span class="num">${fmtNum(s.avg_views)}</span></div>`).join("")}</section>
    <section class="card"><h2>Best performer</h2>${(() => { const v = ch.videos[0]; return `<h3>${esc(v.title)}</h3><p class="muted">${fmtNum(v.views)} views · ${fmtNum(v.likes)} likes · ${esc(v.style || "")}</p><button class="btn sm" type="button" data-open="${v.id}">${I.play}Open</button>`; })()}</section>
  </div>
  <section class="card"><h2>Videos</h2><table><thead><tr><th>Title</th><th>Format</th><th class="num">Score</th><th class="num">Views</th><th class="num">Likes</th></tr></thead>
    <tbody>${ch.videos.map(v => `<tr><td><a href="#library" data-open="${v.id}">${esc(v.title)}</a></td><td>${esc(v.style || "")}</td><td class="num">${v.score ?? "–"}</td><td class="num">${fmtNum(v.views)}</td><td class="num">${fmtNum(v.likes)}</td></tr>`).join("")}</tbody></table></section>`
    : `<section class="card"><div class="empty"><b>No stats yet</b>Upload some videos, then refresh. View counts need a day or two to mean something.</div></section>`}`;
  paint(main);
  $("#sync").onclick = async () => { try { await post("/api/stats"); toast("Refreshing stats…", "info"); tick(); } catch (e) { toast(esc(e.message), "bad"); } };
}

// ------------------------------------------------------------------ SYSTEM
async function viewSystem() {
  const main = $("#main");
  main.innerHTML = `<div class="page-head"><div><h1>System</h1><p>Setup checks, settings and ways to drive PurffleShorts from other tools.</p></div></div><div id="sys"><div class="empty">Checking your setup…</div></div>`;
  let checks;
  try { checks = await get("/api/doctor"); } catch (e) { $("#sys").innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  if (S.view !== "system") return;
  const bad = checks.filter(c => c.ok === false).length;
  const mcp = JSON.stringify({ mcpServers: { "purffle-shorts": { command: "purffle-shorts", args: ["mcp"], env: { PURFFLE_HOME: "/path/to/your/purffle/folder" } } } }, null, 2);
  $("#sys").innerHTML = `
  <section class="card"><h2>Setup · ${bad ? `<span class="chip bad">${bad} to fix</span>` : `<span class="chip ok">all good</span>`}</h2>
    <div class="checks">${checks.map(c => `<div class="check"><span class="m ${c.ok === true ? "ok" : c.ok === false ? "bad" : "info"}">${c.ok === true ? "✔" : c.ok === false ? "✘" : "•"}</span><span>${esc(c.label)}</span><span>${esc(c.detail)}</span></div>`).join("")}</div>
    <p class="hint">Settings live in <span class="mono">.env</span> next to where you started the Studio. Restart it after editing.</p></section>
  <div class="grid2">
    <section class="card"><h2>Use from Claude & other AI apps (MCP)</h2>
      <p class="muted">Add this to Claude Desktop, Claude Code, Cursor or any MCP client, then ask: “make a 30-second Short about why cats purr”.</p>
      <pre class="code" id="mcp">${esc(mcp)}</pre><div class="actions end"><button class="btn sm" id="copy" type="button">${I.copy}Copy</button></div></section>
    <section class="card"><h2>Command line</h2><pre class="code">purffle-shorts run                 # autopilot
purffle-shorts make --style chat   # one video
purffle-shorts make --url https://…
purffle-shorts clip talk.mp4 --count 3
purffle-shorts plan --count 14
purffle-shorts stats
purffle-shorts doctor</pre></section>
  </div>
  <p class="hint">PurffleShorts ${esc(S.info.version)} · <a href="https://github.com/Chamanrajragu/purffle-shorts" target="_blank" rel="noopener">GitHub</a></p>`;
  $("#copy").onclick = async () => { try { await navigator.clipboard.writeText(mcp); toast("Copied.", "ok", 2000); } catch { toast("Select the text and copy it.", "info"); } };
}

boot();
