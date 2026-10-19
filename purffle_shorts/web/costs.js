/* Cost ledger: integer accounting lives on the server; decimal values here are for display. */
"use strict";

const COST = { tab: "models", view: "events", page: 1, filters: {}, data: null, edit: null, request: 0 };
const COST_ALERTS = new Set();
const COST_LABELS = { confirmed: "Confirmed", estimated: "Estimated", pending: "Pending",
  unknown: "Not reported", free: "No API charge" };

function costMoney(value, brl = true) {
  if (value == null) return '<span class="muted">Not reported</span>';
  const n = Number(value);
  const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD",
    minimumFractionDigits: 2, maximumFractionDigits: Math.abs(n) < .01 ? 9 : 4 }).format(n);
  const fx = COST.data?.settings?.brl_per_usd;
  return `<span class="cost-money">${usd}${brl && fx ? `<small>≈ ${new Intl.NumberFormat("pt-BR",
    { style: "currency", currency: "BRL", maximumFractionDigits: 4 }).format(n * Number(fx))}</small>` : ""}</span>`;
}
const costBytes = value => value >= 1048576 ? (value / 1048576).toFixed(1) + " MB" : (value / 1024).toFixed(1) + " KB";
const costCount = value => value == null ? "—" : new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
const costBadge = value => `<span class="chip ${value === "unknown" || value === "pending" ? "" : value === "estimated" ? "blue" : "ok"}">${COST_LABELS[value] || esc(value)}</span>`;
const costQuery = () => new URLSearchParams(Object.entries(COST.filters).filter(([, v]) => v)).toString();

function rememberCostFocus() {
  const active = document.activeElement;
  if (!active?.closest("#main")) return () => {};
  const attrs = [...active.attributes].filter(a => a.name.startsWith("data-"));
  const selector = active.id ? "#" + CSS.escape(active.id)
    : attrs.map(a => `[${a.name}="${CSS.escape(a.value)}"]`).join("");
  return () => {
    if (selector && !active.isConnected && document.activeElement === document.body) {
      $("#main").querySelector(selector)?.focus({ preventScroll: true });
    }
  };
}

function showCostAlerts(data) {
  if (!data) return;
  const badge = $("#costbadge");
  const over = data.rows.filter(row => row.percent >= 80);
  if (badge) { badge.hidden = !over.length; badge.textContent = over.length; }
  const fresh = data.alerts.filter(a => !COST_ALERTS.has(JSON.stringify([a.month, a.scope, a.threshold])));
  if (!fresh.length) return;
  const highest = new Map();
  for (const a of fresh) {
    COST_ALERTS.add(JSON.stringify([a.month, a.scope, a.threshold]));
    if (!highest.has(a.scope) || highest.get(a.scope).threshold < a.threshold) highest.set(a.scope, a);
  }
  for (const a of highest.values()) toast(`<b>${esc(a.label)}: ${a.threshold}% budget alert</b><br>
    ${costMoney(a.spent_usd, false)} recorded this month. <a href="#costs">Review costs</a>`, "info", 10000);
  post("/api/costs/alerts", { alerts: fresh }).catch(() => {});
}

function costFilter(key, label, options) {
  return `<label class="field">${label}<select data-cf="${key}"><option value="">All</option>
    ${options.map(v => `<option value="${esc(v)}"${COST.filters[key] === v ? " selected" : ""}>${esc(COST_LABELS[v] || v)}</option>`).join("")}</select></label>`;
}

async function viewCosts() {
  $("#main").innerHTML = `
    <div class="page-head"><div><h1>Costs</h1><p>Follow every model call from first draft to finished video.</p></div>
      <div class="actions"><button class="btn sm" type="button" data-cost-sync>Refresh charges</button>
        <button class="btn sm" type="button" data-cost-settings>Budgets & prices</button>
        <a class="btn sm" id="cost-export">Export CSV</a></div></div>
    <div id="cost-error" role="alert"></div>
    <section class="cost-filters" aria-label="Cost filters">
      <label class="field">From<input type="date" data-cf="from" value="${esc(COST.filters.from || "")}"></label>
      <label class="field">Through<input type="date" data-cf="to" value="${esc(COST.filters.to || "")}"></label>
      <button class="btn sm" type="button" data-cost-all-time>All history</button>
      <div id="cost-extra-filters" class="cost-filter-extra"></div>
    </section>
    <div id="cost-summary" aria-live="polite"><p class="hint">Loading recorded costs…</p></div>
    <div id="cost-budget-state"></div>
    <section class="card cost-chart-section"><h2>Daily spend</h2>
      <p class="hint">Confirmed charges and estimates. Choose a day to inspect its calls.</p>
      <div id="cost-chart"></div></section>
    <section class="card cost-ledger-section"><div class="cost-ledger-head">
      <div class="seg" role="group" aria-label="Cost breakdown">${[["models", "Models"], ["videos", "Videos"], ["events", "Calls & runs"]]
        .map(([key, label]) => `<button type="button" data-cost-tab="${key}" aria-pressed="${COST.tab === key}">${label}</button>`).join("")}</div>
      <span id="cost-ledger-count" class="hint"></span></div>
      <div id="cost-run-toggle" class="actions"></div><div id="cost-ledger" aria-live="polite"></div><div id="cost-pagination" class="actions end"></div>
    </section>
    <div id="cost-settings"></div>`;
  const root = $("#main");
  root.onchange = e => {
    if (e.target.dataset.cf) {
      COST.filters[e.target.dataset.cf] = e.target.value; delete COST.filters.run_id; COST.page = 1; refreshCosts();
      if (["from", "to"].includes(e.target.dataset.cf)) delete COST.filters.all_time;
    }
    if (e.target.dataset.costKey === "billing") drawCostSettings(true);
  };
  root.oninput = e => {
    const el = e.target;
    if (el.dataset.costSetting) COST.edit[el.dataset.costSetting] = el.value;
    if (el.dataset.costGroup) COST.edit[el.dataset.costGroup][+el.dataset.costIndex][el.dataset.costKey] = el.value;
  };
  root.onsubmit = async e => {
    if (e.target.id !== "cost-settings-form") return;
    e.preventDefault();
    const button = e.target.querySelector('[type="submit"]');
    button.disabled = true;
    try {
      COST.edit = await post("/api/costs/settings", COST.edit);
      toast("Budgets, prices and currency saved. Prices apply to new calls.", "ok");
      await refreshCosts(); drawCostSettings(true); refreshInfo();
    } catch (err) { toast(esc(err.message), "bad"); }
    finally { if (button.isConnected) button.disabled = false; }
  };
  root.onclick = async e => {
    const t = e.target.closest("button, a");
    if (!t) return;
    if (t.dataset.costTab) { COST.tab = t.dataset.costTab; COST.page = 1; refreshCosts(); }
    if (t.hasAttribute("data-cost-all-time")) {
      COST.filters.from = COST.filters.to = ""; COST.filters.all_time = "1"; COST.page = 1; refreshCosts();
    }
    if (t.dataset.costView) { COST.view = t.dataset.costView; COST.page = 1; refreshCosts(); }
    if (t.dataset.costPage) { COST.page = +t.dataset.costPage; refreshCosts(); }
    if (t.dataset.costDay) {
      COST.filters.from = COST.filters.to = t.dataset.costDay; COST.tab = "events"; COST.view = "events";
      COST.page = 1; refreshCosts();
    }
    if (t.dataset.costModel) {
      COST.filters.provider = t.dataset.costProvider; COST.filters.model = t.dataset.costModel;
      COST.tab = "events"; COST.page = 1; refreshCosts();
    }
    if (t.dataset.costRun) {
      COST.filters.run_id = t.dataset.costRun; COST.tab = "events"; COST.view = "events"; COST.page = 1; refreshCosts();
    }
    if (t.dataset.costVideo) openCostVideo(+t.dataset.costVideo);
    if (t.hasAttribute("data-cost-sync")) {
      t.disabled = true;
      try { const state = await post("/api/costs/sync"); toast(state.error ? esc(state.error) : "Refreshing pending charges in the background.", state.error ? "bad" : "info"); }
      catch (err) { toast(esc(err.message), "bad"); }
      finally { t.disabled = false; }
    }
    if (t.hasAttribute("data-cost-settings")) {
      if (!$("#cost-settings-details")) return;
      $("#cost-settings-details").open = true;
      $("#cost-settings").scrollIntoView({ behavior: "smooth", block: "start" });
    }
    if (t.dataset.costAdd) {
      const first = COST.data.models[0] || { provider: "openrouter", model: "" };
      COST.edit[t.dataset.costAdd].push(t.dataset.costAdd === "prices"
        ? { provider: first.provider, model: "", billing: "tokens", input: "", output: "", cache_read: "", cache_write: "" }
        : { provider: first.provider, model: "", budget_usd: "" });
      drawCostSettings(true);
    }
    if (t.dataset.costRemove) {
      COST.edit[t.dataset.costRemove].splice(+t.dataset.costIndex, 1); drawCostSettings(true);
    }
  };
  await refreshCosts();
}

async function refreshCosts() {
  if (S.view !== "costs") return;
  const ticket = ++COST.request;
  let restoreFocus = () => {};
  try {
    const data = await get("/api/costs?" + costQuery());
    if (S.view !== "costs" || ticket !== COST.request) return;
    COST.data = data;
    restoreFocus = rememberCostFocus();
    if (!COST.filters.all_time && !COST.filters.from && !COST.filters.to) Object.assign(COST.filters, data.period);
    $$(".cost-filters [data-cf]").forEach(el => { el.value = COST.filters[el.dataset.cf] || ""; });
    $("#cost-extra-filters").innerHTML = costFilter("provider", "Provider", data.options.provider)
      + costFilter("model", "Model", data.options.model) + costFilter("stage", "Stage", data.options.stage)
      + costFilter("status", "Result", ["done", "failed", "running"])
      + costFilter("cost_status", "Cost information", ["confirmed", "estimated", "pending", "unknown", "free"]);
    $("#cost-export").href = "/api/costs/export.csv?" + costQuery();
    $("#cost-error").innerHTML = "";
    const total = data.totals;
    $("#cost-summary").innerHTML = `<dl class="cost-summary">
      <div><dt>Confirmed</dt><dd>${costMoney(total.confirmed_usd)}</dd></div>
      <div><dt>Estimated</dt><dd>${costMoney(total.estimated_usd)}</dd></div>
      <div><dt>Calls without a price</dt><dd>${costCount(total.unknown_calls)}<small>of ${costCount(total.calls)} calls · ${costCount(total.failed_calls)} failed</small></dd></div>
      <div><dt>Not assigned to a video</dt><dd>${costMoney(total.unassigned_usd)}</dd></div></dl>
      <p class="hint">Period follows call dates in ${esc(data.timezone)}. Unknown charges are excluded from known spend.
        ${data.settings.brl_per_usd ? `BRL is estimated at R$${esc(data.settings.brl_per_usd)}/USD, set ${esc(new Date(data.settings.exchange_updated_at).toLocaleDateString())}.` : "Charges and budgets are recorded in USD."}</p>
      ${data.incomplete_runs.length ? '<div class="banner"><p>Some runs have incomplete telemetry. Recorded spend may be partial.</p></div>' : ""}`;
    const budgets = data.budgets;
    $("#cost-budget-state").innerHTML = `<section class="cost-budgets" aria-label="Monthly budgets">
      <h2>Monthly budgets <span class="hint">${esc(budgets.month)} · current month</span></h2>
      ${budgets.rows.length ? budgets.rows.map(b => `<div class="cost-budget">
        <div><b>${esc(b.label)}</b><span>${costMoney(b.spent_usd, false)} / ${costMoney(b.budget_usd, false)}
          · ${costCount(b.percent)}%${b.unknown_calls ? ` · ${b.unknown_calls} unpriced calls` : ""}</span></div>
        <progress max="100" value="${Math.min(100, b.percent)}" aria-label="${esc(b.label)} monthly budget"></progress></div>`).join("")
      : '<p class="hint">No monthly budget set. Add one in Budgets & prices.</p>'}</section>`;
    drawCostChart(data.daily);
    showCostAlerts(budgets);
    $$("[data-cost-tab]").forEach(el => el.setAttribute("aria-pressed", String(el.dataset.costTab === COST.tab)));
    $("#cost-run-toggle").innerHTML = COST.tab === "events" ? `<div class="seg" role="group" aria-label="Activity detail">
      ${[["events", "Calls"], ["runs", "Executions"]].map(([key, label]) => `<button type="button" data-cost-view="${key}" aria-pressed="${key === COST.view}">${label}</button>`).join("")}</div>
      ${COST.filters.run_id ? `<button class="btn ghost sm" type="button" id="cost-clear-run">Clear execution filter</button>` : ""}` : "";
    if ($("#cost-clear-run")) $("#cost-clear-run").onclick = () => { delete COST.filters.run_id; refreshCosts(); };
    if (!COST.edit) COST.edit = JSON.parse(JSON.stringify(data.settings));
    if (!$("#cost-settings-details")) drawCostSettings();
    if (COST.tab === "models") {
      $("#cost-ledger").innerHTML = costModels(data.models);
      $("#cost-ledger-count").textContent = data.models.length + " models";
      $("#cost-pagination").innerHTML = "";
    } else {
      const url = COST.tab === "videos" ? "/api/costs/videos" : "/api/costs/events";
      const page = await get(`${url}?${costQuery()}&page=${COST.page}&view=${COST.view}`);
      if (S.view !== "costs" || ticket !== COST.request) return;
      $("#cost-ledger").innerHTML = COST.tab === "videos" ? costVideos(page.rows)
        : COST.view === "runs" ? costRuns(page.rows) : costEvents(page.rows);
      $("#cost-ledger-count").textContent = page.total + " records";
      const pages = Math.max(1, Math.ceil(page.total / page.page_size));
      $("#cost-pagination").innerHTML = `<button type="button" class="btn sm" data-cost-page="${Math.max(1, page.page - 1)}"${page.page <= 1 ? " disabled" : ""}>Previous</button>
        <span class="hint">Page ${page.page} of ${pages}</span>
        <button type="button" class="btn sm" data-cost-page="${page.page + 1}"${page.page >= pages ? " disabled" : ""}>Next</button>`;
    }
  } catch (err) {
    if (S.view === "costs" && ticket === COST.request) $("#cost-error").innerHTML = `<div class="banner"><p>${esc(err.message)}. Refresh or adjust filters.</p></div>`;
  } finally { restoreFocus(); }
}

function costTable(headings, rows) {
  if (!rows.length) return '<div class="empty"><b>No recorded activity in this selection</b>Generate content or adjust filters. Earlier videos do not have historical usage records.</div>';
  return `<div class="cost-table-scroll"><table class="cost-table"><thead><tr>${headings.map(h => `<th scope="col">${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}
function costModels(rows) {
  return costTable(["Model / provider", "Known spend", "Calls / failed", "Tokens in / out", "Other resources", "Mean call time"],
    rows.map(m => `<tr><td><button type="button" class="cost-link" data-cost-model="${esc(m.model)}" data-cost-provider="${esc(m.provider)}">${esc(m.model)}</button>
      <small>${esc(m.provider)} · ${esc(m.stages.join(", "))}</small></td><td>${costMoney(m.unknown_calls === m.calls ? null : m.known_usd)}
      <small>${m.unknown_calls ? m.unknown_calls + " unpriced" : "All calls priced"}${Number(m.estimated_usd) ? " · includes estimates" : ""}</small></td>
      <td>${m.calls} / ${m.failed_calls}</td><td>${costCount(m.units.input_tokens)} / ${costCount(m.units.output_tokens)}</td>
      <td>${costResources(m.units)}</td><td>${fmtSec(m.elapsed_ms / 1000 / Math.max(1, m.calls))}</td></tr>`));
}
function costResources(u) {
  return [["images", "images"], ["audio_seconds", "audio s"], ["video_seconds", "video s"], ["characters", "characters"],
    ["cached_tokens", "cached tokens"], ["reasoning_tokens", "reasoning tokens"]]
    .filter(([key]) => u[key] != null).map(([key, label]) => `<small class="cost-resource">${costCount(u[key])} ${label}</small>`).join("") || '<span class="muted">—</span>';
}
function costVideos(rows) {
  return costTable(["Video", "Direct", "Shared", "Known total", "Output", "Execution"],
    rows.map(v => `<tr><td><button class="cost-link" type="button" data-cost-video="${v.video_id}">${esc(v.title)}</button>
      <small>#${v.video_id}${v.deleted ? " · file deleted" : ""}${v.unknown_calls ? ` · ${v.unknown_calls} unpriced calls` : ""}</small></td>
      <td>${costMoney(v.direct_usd)}</td><td>${costMoney(v.shared_usd)}</td><td>${costMoney(v.known_usd)}</td>
      <td>${fmtSec(v.duration)}<small>${costBytes(v.file_bytes)}</small></td><td>${fmtSec(v.elapsed_ms / 1000)}<small>${v.calls} calls</small></td></tr>`));
}
function costEvents(rows) {
  return costTable(["Call / stage", "Model", "Charge", "Cost information", "Usage", "Result / time"],
    rows.map(e => `<tr><td><button type="button" class="cost-link" data-cost-run="${esc(e.run_id)}">${esc(e.run_title)}</button>
      <small>${esc(e.stage)} · ${esc(new Date(e.created_at).toLocaleString())}</small></td>
      <td>${esc(e.model)}<small>${esc(e.provider)}${e.requested_model !== e.model ? ` · requested ${esc(e.requested_model)}` : ""}</small></td>
      <td>${costMoney(e.cost_usd)}</td><td>${costBadge(e.cost_status)}</td>
      <td>${e.units.input_tokens != null ? `${costCount(e.units.input_tokens)} in / ${costCount(e.units.output_tokens)} out` : ""}${costResources(e.units)}</td>
      <td>${esc(e.status)}<small>${fmtSec(e.elapsed_ms / 1000)}</small>${e.error ? `<details><summary>Error</summary><p class="hint">${esc(e.error)}</p></details>` : ""}</td></tr>`));
}
function costRuns(rows) {
  return costTable(["Execution", "Known spend", "Calls / failed", "Status", "Time", "Related source"],
    rows.map(r => `<tr><td><button type="button" class="cost-link" data-cost-run="${esc(r.id)}">${esc(r.title)}</button><small>${esc(r.kind)} · ${esc(new Date(r.started_at).toLocaleString())}</small></td>
      <td>${costMoney(r.totals.known_usd)}<small>${r.totals.unknown_calls} unpriced calls</small></td>
      <td>${r.totals.calls} / ${r.totals.failed_calls}</td><td>${esc(r.status)}${!r.telemetry_complete ? "<small>Incomplete telemetry</small>" : ""}</td>
      <td>${r.elapsed_ms == null ? "Unfinished" : fmtSec(r.elapsed_ms / 1000)}</td>
      <td>${r.source_video_id ? `Video #${r.source_video_id}` : r.source_run_id ? "Reused draft" : r.parent_id ? "Translation" : "Original"}
      ${r.error ? `<small>${esc(r.error)}</small>` : ""}</td></tr>`));
}

function drawCostChart(days) {
  const max = Math.max(...days.map(d => Number(d.known_usd)), .000000001);
  $("#cost-chart").innerHTML = days.length ? `<div class="cost-chart" role="group" aria-label="Daily recorded spend">
    ${days.map(d => `<button class="cost-bar" type="button" data-cost-day="${d.date}" aria-label="${d.date}: confirmed $${d.confirmed_usd}, estimated $${d.estimated_usd}" title="${d.date}: $${d.known_usd}">
      <span class="cost-bar-track"><span class="cost-bar-estimated" data-cost-height="${Number(d.estimated_usd) / max * 100}"></span><span class="cost-bar-confirmed" data-cost-height="${Number(d.confirmed_usd) / max * 100}"></span></span><small>${d.date.slice(5)}</small></button>`).join("")}</div>
      <p class="hint"><span class="cost-key confirmed"></span> Confirmed <span class="cost-key estimated"></span> Estimated</p>
      <details class="more"><summary>Daily values</summary>${costTable(["Date", "Confirmed", "Estimated", "Unpriced calls"],
        days.map(d => `<tr><th scope="row">${d.date}</th><td>${costMoney(d.confirmed_usd)}</td><td>${costMoney(d.estimated_usd)}</td><td>${d.unknown_calls}</td></tr>`))}</details>`
    : '<p class="hint">Daily spend appears after the first recorded call.</p>';
  $$("[data-cost-height]").forEach(el => { el.style.height = el.dataset.costHeight + "%"; });
}

function costInput(key, label, value, group = "", index = 0, numeric = false) {
  const attrs = group ? `data-cost-group="${group}" data-cost-index="${index}" data-cost-key="${key}"` : `data-cost-setting="${key}"`;
  return `<label class="field">${label}<input ${attrs} type="${numeric ? "number" : "text"}" ${numeric ? 'min="0" step="any"' : ""} value="${esc(value || "")}"></label>`;
}
function drawCostSettings(open = false) {
  const settings = COST.edit;
  $("#cost-settings").innerHTML = `<details class="card" id="cost-settings-details"${open ? " open" : ""}>
    <summary>Budgets, model prices and currency</summary><form id="cost-settings-form">
    <div class="grid2">${costInput("monthly_budget_usd", "Monthly budget · USD (blank = no budget)", settings.monthly_budget_usd, "", 0, true)}
      ${costInput("brl_per_usd", "BRL per USD · optional estimate", settings.brl_per_usd, "", 0, true)}</div>
    <h3>Monthly budgets by provider or model</h3>
    <div>${settings.model_budgets.map((b, i) => `<div class="cost-setting-row">
      ${costInput("provider", "Provider", b.provider, "model_budgets", i)}${costInput("model", "Model (blank = all provider models)", b.model, "model_budgets", i)}
      ${costInput("budget_usd", "Monthly USD", b.budget_usd, "model_budgets", i, true)}
      <button class="btn ghost sm" type="button" data-cost-remove="model_budgets" data-cost-index="${i}" aria-label="Remove model budget">Remove</button></div>`).join("")}</div>
    <button class="btn sm" type="button" data-cost-add="model_budgets">Add provider or model budget</button>
    <h3>Prices for estimates</h3><p class="hint">Use the exact provider and model shown in the ledger. Reported charges take priority. Price changes apply to new calls.</p>
    ${settings.prices.map((p, i) => `<fieldset class="cost-price-row"><legend>Price ${i + 1}</legend><div class="cost-setting-row">
      ${costInput("provider", "Provider", p.provider, "prices", i)}${costInput("model", "Model", p.model, "prices", i)}
      <label class="field">Billing unit<select data-cost-group="prices" data-cost-index="${i}" data-cost-key="billing">
      ${[["tokens", "Per million tokens"], ["characters", "Per million characters"], ["images", "Per image"],
        ["audio_seconds", "Per audio second"], ["video_seconds", "Per video second"]].map(([k, label]) => `<option value="${k}"${p.billing === k ? " selected" : ""}>${label}</option>`).join("")}</select></label>
      <button class="btn ghost sm" type="button" data-cost-remove="prices" data-cost-index="${i}" aria-label="Remove model price">Remove</button></div>
      <div class="cost-price-fields">${p.billing === "tokens" ? [["input", "Input USD / 1M"], ["output", "Output USD / 1M"],
        ["cache_read", "Cached input USD / 1M (optional)"], ["cache_write", "Cache write USD / 1M (optional)"]]
        .map(([k, label]) => costInput(k, label, p[k], "prices", i, true)).join("")
        : costInput("rate", "USD per billing unit", p.rate, "prices", i, true)}</div></fieldset>`).join("")}
    <button class="btn sm" type="button" data-cost-add="prices">Add model price</button>
    <p class="hint">Alerts appear at 80% and 100%. Budgets do not interrupt generation. Local resources show API charges only.</p>
    <div class="actions end"><button class="btn primary" type="submit">Save budgets & prices</button></div></form></details>`;
}

function costDetailMarkup(d) {
  if (!d.tracked) return '<h3>Costs & resources</h3><p class="hint">Not recorded. This video predates usage tracking.</p>';
  const u = d.units;
  return `<h3>Costs & resources</h3><dl class="cost-detail-summary">
    <div><dt>Direct</dt><dd>${costMoney(d.direct_usd)}</dd></div><div><dt>Shared</dt><dd>${costMoney(d.shared_usd)}</dd></div>
    <div><dt>Known total</dt><dd>${costMoney(d.known_usd)}</dd></div></dl>
    <p class="hint">${d.unknown_calls ? `${d.unknown_calls} calls have no known price. Total is partial. ` : ""}
      ${!d.telemetry_complete ? "Telemetry is incomplete. " : ""}Shared resources are allocated once across outputs; reused scripts are not charged twice.</p>
    <dl class="kv"><dt>Tokens in / out</dt><dd>${costCount(u.input_tokens)} / ${costCount(u.output_tokens)}</dd>
      <dt>Resources allocated</dt><dd>${costResources(u)}</dd><dt>MP4 / kept artifacts</dt><dd>${costBytes(d.file_bytes)} / ${costBytes(d.artifact_bytes)}</dd>
      <dt>Execution time</dt><dd>${fmtSec(d.elapsed_ms / 1000)}</dd>
      ${d.source_video_id ? `<dt>Reused source</dt><dd>Video #${d.source_video_id}</dd>` : ""}
      ${d.source_run_id ? '<dt>Script source</dt><dd>Previously generated draft</dd>' : ""}</dl>
    ${costTable(["Stage", "Direct", "Shared", "Calls"], d.stages.map(s => `<tr><th scope="row">${esc(s.stage)}</th><td>${costMoney(s.direct_usd)}</td><td>${costMoney(s.shared_usd)}</td><td>${s.calls}${s.unknown_calls ? ` (${s.unknown_calls} unpriced)` : ""}</td></tr>`))}
    <details class="more"><summary>Stage times & individual calls</summary>
      <dl class="kv">${Object.entries(d.stage_ms).map(([stage, ms]) => `<dt>${esc(stage)}</dt><dd>${fmtSec(ms / 1000)}</dd>`).join("")}</dl>
      <p class="hint">Each call shows the amount assigned to this video and its share of the original charge.</p>
      ${d.events.map(e => `<div class="cost-event-detail"><b>${esc(e.stage)} · ${esc(e.model)}</b>
        <span>${costMoney(e.allocated_usd)} assigned (${esc(e.fraction)}) · ${costBadge(e.cost_status)}</span>
        <small>${esc(e.provider)} · ${esc(e.status)} · ${fmtSec(e.elapsed_ms / 1000)}
          ${e.requested_model !== e.model ? ` · requested ${esc(e.requested_model)}` : ""}</small>
        ${e.request_id ? `<small class="mono">${esc(e.request_id)}</small>` : ""}
        ${e.error ? `<p class="hint">${esc(e.error)}</p>` : ""}</div>`).join("")}
    </details>`;
}
async function loadVideoCosts(id, root) {
  if (!root) return;
  try {
    const d = await get(`/api/videos/${id}/costs`);
    if (root.isConnected) root.innerHTML = costDetailMarkup(d);
  } catch { if (root.isConnected) root.innerHTML = '<p class="hint">Could not load resource usage. Reopen video details to retry.</p>'; }
}
async function openCostVideo(id) {
  const opener = document.activeElement;
  try {
    const d = await get(`/api/videos/${id}/costs`);
    $("#drawer-panel").innerHTML = `<button class="btn ghost close" type="button" data-close aria-label="Close">${I.x}</button><div class="cost-only-details">
      <h2>${esc(d.title)}</h2><p class="hint">Lifetime usage · video #${id}${d.deleted ? " · deleted" : ""}</p>
      ${!d.deleted ? `<button class="btn sm" type="button" data-open="${id}">Open video</button>` : ""}${costDetailMarkup(d)}</div>`;
    showDrawer(opener);
  } catch (e) { toast(esc(e.message), "bad"); }
}

setInterval(() => { if (S.view === "costs") refreshCosts(); }, 15000);
