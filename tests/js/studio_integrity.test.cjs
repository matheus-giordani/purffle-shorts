"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../purffle_shorts/web/app.js"), "utf8");
const costsSource = fs.readFileSync(path.join(__dirname, "../../purffle_shorts/web/costs.js"), "utf8");
const plain = value => JSON.parse(JSON.stringify(value));
const settle = () => new Promise(resolve => setImmediate(resolve));
const script = title => ({ title, language: "pt", style: "product", scenes: [{ narration: "Product narration", speaker: "A" }] });

function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

function studio(saved = {}) {
  const values = new Map(Object.entries(saved).map(([key, value]) => ["purffle." + key, JSON.stringify(value)]));
  const inputs = new Map(), notices = [], failKeys = new Set();
  const nodes = new Map();
  function query(selector) {
    const match = selector.match(/^\[data-paff="(\d+)"\]$/);
    if (match) return inputs.get(+match[1]) || null;
    return nodes.get(selector) || null;
  }
  const node = () => {
    let html = "";
    const children = new Map();
    return {
      get innerHTML() { return html; },
      set innerHTML(value) {
        for (const [id, child] of children) if (nodes.get(id) === child) nodes.delete(id);
        children.clear();
        html = value;
        // Expose only controls actually present in the rendered markup.
        for (const match of value.matchAll(/\bid="([^"]+)"/g)) {
          const child = node(), id = "#" + match[1];
          child.id = match[1];
          children.set(id, child);
          nodes.set(id, child);
        }
      },
      hidden: true, style: {}, querySelector: query, querySelectorAll: () => [],
      addEventListener() {}, append() {}, focus() {}, remove() {},
      dataset: {}, classList: { add() {}, remove() {}, toggle() {} },
    };
  };
  for (const name of ["#main", "#drawer", "#drawer-panel", "#toasts", ".app"]) nodes.set(name, node());
  nodes.set('meta[name="studio-token"]', { content: "unit-token" });
  const context = vm.createContext({
    document: { querySelector: query, querySelectorAll: () => [], addEventListener() {}, createElement: node,
      body: node(), activeElement: node() },
    localStorage: {
      getItem: key => values.has(key) ? values.get(key) : null,
      setItem(key, value) {
        if (failKeys.has(key)) throw new Error("Storage unavailable");
        values.set(key, value);
      },
    },
    window: { addEventListener() {}, scrollTo() {} }, location: { hash: "#create" },
    navigator: {}, CSS: { escape: value => value }, URLSearchParams,
    confirm: () => true, prompt: () => null,
    setTimeout() {}, clearTimeout() {}, setInterval() {}, clearInterval() {},
    // boot() remains pending. The complete production source is loaded unchanged; no network is possible.
    fetch: () => new Promise(() => {}),
  });
  vm.runInContext(costsSource, context, { filename: "costs.js" });
  vm.runInContext(source, context, { filename: "app.js" });
  const state = vm.runInContext("S", context), actualDrawEditor = context.drawEditor;
  Object.assign(state, { info: { upload: false }, view: "create", prodData: { products: [] } });
  Object.assign(state.form, { mode: "topic", topic: "Topic", url: "", language: "pt", style: "product",
    duration: 40, upload: false, offline: false, visuals: [] });
  context.toast = (html, kind) => notices.push({ html, kind });
  context.get = () => new Promise(() => {});
  context.drawSide = context.drawForm = context.drawEditor = context.drawLibrary = () => {};
  context.tick = context.refreshInfo = () => {};
  context.route = () => { state.view = context.location.hash.slice(1); };
  return {
    context, state, values, inputs, notices, failKeys, nodes, node,
    drawEditor: () => actualDrawEditor(),
    run: code => vm.runInContext(code, context),
    input(id, value) {
      const input = { value, focused: false, focus() { this.focused = true; } };
      inputs.set(id, input);
      return input;
    },
    stored: key => JSON.parse(values.get("purffle." + key)),
    persisted: () => Object.fromEntries([...values].map(([key, value]) => [key.slice(8), JSON.parse(value)])),
  };
}

test("legacy draft and source are loaded together", () => {
  const h = studio({ draft: script("Old"), draftSource: { usage_run_id: "old-run" } });
  assert.equal(h.state.draft.title, "Old");
  assert.equal(h.state.draftSource.usage_run_id, "old-run");
});

test("atomic draft takes precedence over mismatched legacy keys", () => {
  const h = studio({ draftState: { script: script("Atomic"), source: { usage_run_id: "atomic-run" } },
    draft: script("Stale"), draftSource: { usage_run_id: "stale-run" } });
  assert.equal(h.state.draft.title, "Atomic");
  assert.equal(h.state.draftSource.usage_run_id, "atomic-run");
});

test("saved draft survives reload with its billing identity", () => {
  const h = studio();
  h.context.replaceDraft(script("Saved"), { usage_run_id: "run-1", product_ids: [1, 2] });
  const reloaded = studio(h.persisted());
  assert.equal(reloaded.state.draft.title, "Saved");
  assert.deepEqual(plain(reloaded.state.draftSource), { usage_run_id: "run-1", product_ids: [1, 2] });
});

test("failed atomic save preserves the old persisted script and source", () => {
  const h = studio();
  h.context.replaceDraft(script("Old"), { usage_run_id: "old-run" });
  h.failKeys.add("purffle.draftState");
  h.context.replaceDraft(script("Unsaved"), { usage_run_id: "new-run" });
  assert.equal(h.stored("draft").title, "Old");
  assert.equal(h.stored("draftSource").usage_run_id, "old-run");
  const reloaded = studio(h.persisted());
  assert.equal(reloaded.state.draft.title, "Old");
  assert.equal(reloaded.state.draftSource.usage_run_id, "old-run");
  assert.equal(h.notices[0].kind, "bad");
});

test("partial legacy save cannot mismatch the authoritative draft bundle", () => {
  const h = studio({ draft: script("Old"), draftSource: { usage_run_id: "old-run" } });
  h.failKeys.add("purffle.draftSource");
  h.context.replaceDraft(script("New"), { usage_run_id: "new-run" });
  const reloaded = studio(h.persisted());
  assert.equal(reloaded.state.draft.title, "New");
  assert.equal(reloaded.state.draftSource.usage_run_id, "new-run");
});

test("storage failure warning is shown once until saving recovers", () => {
  const h = studio();
  h.failKeys.add("purffle.draftState");
  assert.equal(h.context.saveDraft(), false);
  assert.equal(h.context.saveDraft(), false);
  assert.equal(h.notices.length, 1);
  h.failKeys.clear();
  assert.equal(h.context.saveDraft(), true);
  h.failKeys.add("purffle.draftState");
  h.context.saveDraft();
  assert.equal(h.notices.length, 2);
});

test("previous revision survives edits to the replacement", () => {
  const h = studio();
  h.context.replaceDraft(script("Old"), { usage_run_id: "old-run" });
  h.context.replaceDraft(script("New"), { usage_run_id: "new-run" });
  h.state.draft.title = "Edited new";
  assert.equal(h.state.previousDraft.script.title, "Old");
  assert.equal(h.stored("previousDraft").source.usage_run_id, "old-run");
});

test("restore swaps revisions with their source and form settings", () => {
  const h = studio();
  h.context.replaceDraft(script("Old"), { usage_run_id: "old-run" });
  h.context.replaceDraft({ ...script("New"), language: "en", style: "facts" }, { usage_run_id: "new-run" });
  h.context.restorePreviousDraft();
  assert.equal(h.state.draft.title, "Old");
  assert.equal(h.state.draftSource.usage_run_id, "old-run");
  assert.equal(h.state.previousDraft.script.title, "New");
  assert.equal(h.state.form.language, "pt");
  assert.equal(h.state.form.style, "product");
});

test("cancelling restore preserves both revisions", () => {
  const h = studio();
  h.context.replaceDraft(script("Old"));
  h.context.replaceDraft(script("New"));
  h.context.confirm = () => false;
  h.context.restorePreviousDraft();
  assert.equal(h.state.draft.title, "New");
  assert.equal(h.state.previousDraft.script.title, "Old");
});

test("discarded revision can be restored without aliasing the backup", () => {
  const h = studio();
  h.context.replaceDraft(script("Original"), { usage_run_id: "old-run" });
  h.context.replaceDraft(null);
  assert.equal(h.state.draft, null);
  h.context.restorePreviousDraft();
  h.state.draft.title = "New edit";
  assert.equal(h.state.previousDraft.script.title, "Original");
  assert.equal(h.state.draftSource.usage_run_id, "old-run");
});

test("failed draft HTTP request preserves edits and source", async () => {
  const h = studio();
  h.context.replaceDraft(script("Edited"), { usage_run_id: "old-run" });
  h.context.fetch = async () => ({ ok: false, statusText: "Unavailable", json: async () => ({ error: "503" }) });
  await h.context.startDraft({ product_ids: [2] });
  assert.equal(h.state.draft.title, "Edited");
  assert.equal(h.stored("draftState").source.usage_run_id, "old-run");
  assert.equal(h.state.createJob, null);
  assert.equal(h.run("_jobLaunchBusy"), false);
});

test("failed make request preserves draft and permits retry", async () => {
  const h = studio();
  h.context.replaceDraft(script("Edited"), { usage_run_id: "old-run" });
  h.context.post = async () => { throw new Error("Network failed"); };
  await h.context.startMake();
  assert.equal(h.stored("draftState").script.title, "Edited");
  h.context.post = async () => ({ job: 7 });
  await h.context.startMake();
  assert.equal(h.state.createJob.id, 7);
  assert.equal(h.state.draftSource.usage_run_id, "old-run");
});

test("accepted draft preserves old script until the worker succeeds", async () => {
  const h = studio();
  h.context.replaceDraft(script("Old"), { usage_run_id: "old-run" });
  h.context.post = async () => ({ job: 7 });
  await h.context.startDraft();
  assert.equal(h.state.draft.title, "Old");
  h.state.draft.title = "Late edit";
  h.context.saveDraft();
  const job = { id: 7, kind: "draft", status: "done", result: { script: script("New"), usage_run_id: "new-run",
    product_ids: [1], images: ["image.jpg"], videos: ["video.mp4"] } };
  h.state.jobs = [job];
  h.context.finished(job);
  assert.equal(h.state.draft.title, "New");
  assert.equal(h.state.previousDraft.script.title, "Late edit");
  assert.deepEqual(plain(h.state.draftSource), { usage_run_id: "new-run", product_ids: [1],
    images: ["image.jpg"], videos: ["video.mp4"] });
  h.context.finished(job);
  assert.equal(h.state.previousDraft.script.title, "Late edit");
});

test("failed worker leaves the persisted draft intact", async () => {
  const h = studio();
  h.context.replaceDraft(script("Old"), { usage_run_id: "old-run" });
  h.context.post = async () => ({ job: 7 });
  await h.context.startDraft();
  h.context.finished({ id: 7, kind: "draft", status: "failed", label: "Draft", result: { error: "Provider failed" } });
  assert.equal(h.stored("draftState").script.title, "Old");
  assert.equal(h.stored("draftState").source.usage_run_id, "old-run");
});

test("unrelated draft completion never replaces current work", () => {
  const h = studio();
  h.context.replaceDraft(script("Current"));
  h.state.createJob = { id: 7, kind: "draft", session: "unit-token" };
  const other = { id: 8, kind: "draft", status: "done", result: { script: script("Other") } };
  h.state.jobs = [other];
  h.context.finished(other);
  assert.equal(h.state.draft.title, "Current");
});

test("render request carries the preserved draft billing identity", async () => {
  const h = studio();
  const requests = [];
  h.context.replaceDraft(script("Current"), { usage_run_id: "draft-run", product_ids: [1] });
  h.context.post = async (url, body) => { requests.push({ url, body }); return { job: 7 }; };
  await h.context.startMake({ script: h.state.draft });
  assert.equal(requests[0].body.usage_run_id, "draft-run");
  assert.deepEqual(plain(requests[0].body.product_ids), [1]);
});

test("pending submission prevents a second model request", async () => {
  const h = studio(), reply = deferred();
  let calls = 0;
  h.context.post = () => { calls++; return reply.promise; };
  const first = h.context.startDraft();
  await h.context.startDraft();
  assert.equal(calls, 1);
  reply.resolve({ job: 7 });
  await first;
  assert.equal(h.run("_jobLaunchBusy"), false);
});

test("affiliate save failure prevents video production", async () => {
  const h = studio(), input = h.input(1, "https://example.invalid/new");
  let makes = 0;
  h.state.view = "products";
  h.state.prodData.products = [{ id: 1, affiliate_url: "https://example.invalid/old" }];
  h.state.affiliateDrafts[1] = input.value;
  h.context.post = async () => { throw new Error("503"); };
  h.context.startMake = async () => { makes++; };
  await h.context.startProductVideo([1]);
  assert.equal(makes, 0);
  assert.equal(h.state.view, "products");
  assert.equal(input.value, "https://example.invalid/new");
  assert.equal(h.state.affiliateDrafts[1], input.value);
  assert.ok(input.focused);
  assert.equal(h.run("_jobLaunchBusy"), false);
});

test("affiliate save failure prevents draft production", async () => {
  const h = studio();
  h.input(1, "https://example.invalid/new");
  let drafts = 0;
  h.context.post = async () => { throw new Error("503"); };
  h.context.startDraft = async () => { drafts++; };
  await h.context.startProductVideo([1], true);
  assert.equal(drafts, 0);
});

test("affiliate save failure prevents adding a product idea", async () => {
  const h = studio(), calls = [];
  h.input(1, "https://example.invalid/new");
  h.context.post = async url => { calls.push(url); throw new Error("503"); };
  await h.context.queueProductIdea([1]);
  assert.deepEqual(calls, ["/api/products/1/affiliate"]);
  assert.equal(h.run("_jobLaunchBusy"), false);
});

test("production waits for affiliate persistence before changing route", async () => {
  const h = studio(), reply = deferred(), events = [];
  h.input(1, "https://example.invalid/new");
  h.state.view = "products";
  h.context.location.hash = "#products";
  h.context.post = async () => { events.push("save"); await reply.promise; events.push("saved"); };
  h.context.route = () => { events.push("route"); h.inputs.clear(); h.state.view = "create"; };
  h.context.startMake = async () => { events.push("make"); };
  const request = h.context.startProductVideo([1]);
  await settle();
  assert.deepEqual(events, ["save"]);
  reply.resolve({});
  await request;
  assert.deepEqual(events, ["save", "saved", "route", "make"]);
});

test("duplicate product clicks cannot launch concurrent productions", async () => {
  const h = studio(), reply = deferred();
  let saves = 0, makes = 0;
  h.input(1, "https://example.invalid/new");
  h.context.post = async () => { saves++; await reply.promise; };
  h.context.startMake = async () => { makes++; };
  const first = h.context.startProductVideo([1]);
  await h.context.startProductVideo([1]);
  await settle();
  assert.equal(saves, 1);
  reply.resolve({});
  await first;
  assert.equal(makes, 1);
});

test("identical pending affiliate saves share one request", async () => {
  const h = studio(), reply = deferred();
  let calls = 0;
  h.context.post = () => { calls++; return reply.promise; };
  const first = h.context.saveAffiliate(1, "https://example.invalid/new");
  const second = h.context.saveAffiliate(1, "https://example.invalid/new");
  assert.equal(first, second);
  await settle();
  assert.equal(calls, 1);
  reply.resolve({});
  await first;
});

test("different affiliate values are written in order per product", async () => {
  const h = studio(), firstReply = deferred(), secondReply = deferred(), calls = [];
  h.state.prodData.products = [{ id: 1, affiliate_url: "old" }];
  h.state.affiliateDrafts[1] = "second";
  h.context.post = (url, body) => {
    calls.push(body.affiliate_url);
    return calls.length === 1 ? firstReply.promise : secondReply.promise;
  };
  const first = h.context.saveAffiliate(1, "first"), second = h.context.saveAffiliate(1, "second");
  await settle();
  assert.deepEqual(calls, ["first"]);
  firstReply.resolve({});
  await first;
  assert.equal(h.state.affiliateDrafts[1], "second");
  await settle();
  assert.deepEqual(calls, ["first", "second"]);
  secondReply.resolve({});
  await second;
  assert.equal(h.state.prodData.products[0].affiliate_url, "second");
  assert.equal(h.state.affiliateDrafts[1], undefined);
});

test("failed affiliate request does not poison subsequent retry", async () => {
  const h = studio(), reply = deferred();
  let calls = 0;
  h.context.post = () => ++calls === 1 ? reply.promise : Promise.resolve({});
  const first = h.context.saveAffiliate(1, "first");
  const rejected = assert.rejects(first, /503/);
  const second = h.context.saveAffiliate(1, "second");
  reply.reject(new Error("503"));
  await rejected;
  await second;
  assert.equal(calls, 2);
});

test("different products may save independently", async () => {
  const h = studio(), one = deferred(), two = deferred(), urls = [];
  h.context.post = url => { urls.push(url); return url.includes("/1/") ? one.promise : two.promise; };
  const first = h.context.saveAffiliate(1, "first"), second = h.context.saveAffiliate(2, "second");
  await settle();
  assert.equal(urls.length, 2);
  two.resolve({});
  await second;
  one.resolve({});
  await first;
});

test("hidden selected product uses its unsaved local affiliate draft", async () => {
  const h = studio(), saved = [];
  h.state.affiliateDrafts[1] = "https://example.invalid/new";
  h.state.prodData.products = [{ id: 1, affiliate_url: "old" }];
  h.context.post = async (url, body) => { saved.push(body.affiliate_url); };
  await h.context.flushAffiliateInputs([1]);
  assert.deepEqual(saved, ["https://example.invalid/new"]);
  assert.equal(h.state.affiliateDrafts[1], undefined);
});

test("flush waits for an older save even when input matches the loaded value", async () => {
  const h = studio(), firstReply = deferred(), calls = [];
  h.state.prodData.products = [{ id: 1, affiliate_url: "desired" }];
  h.input(1, "desired");
  h.context.post = (url, body) => {
    calls.push(body.affiliate_url);
    return calls.length === 1 ? firstReply.promise : Promise.resolve({});
  };
  const older = h.context.saveAffiliate(1, "older");
  const flush = h.context.flushAffiliateInputs([1]);
  await settle();
  firstReply.resolve({});
  await Promise.all([older, flush]);
  assert.deepEqual(calls, ["older", "desired"]);
  assert.equal(h.state.prodData.products[0].affiliate_url, "desired");
});

test("uncertain publication produces an actionable completion warning", () => {
  const h = studio();
  h.context.finished({ id: 1, kind: "make", status: "done", label: "Video",
    result: { id: 8, title: "Video", status: "upload-unknown" } });
  assert.equal(h.notices[0].kind, "bad");
  assert.match(h.notices[0].html, /uploads need attention/);
  assert.match(h.notices[0].html, /data-open="8"/);
});

test("partial clip publication failure is not announced as complete success", () => {
  const h = studio();
  h.context.finished({ id: 1, kind: "clip", status: "done", label: "Clips",
    result: { clips: [{ id: 8, ok: true, status: "uploaded" }, { id: 9, ok: true, status: "upload-unknown" }] } });
  assert.equal(h.notices[0].kind, "bad");
});

test("draft completion from an earlier server session is ignored", () => {
  const h = studio();
  h.context.replaceDraft(script("Current"));
  h.state.createJob = { id: 7, kind: "draft", session: "old-token" };
  const job = { id: 7, kind: "draft", status: "done", result: { script: script("Other session") } };
  h.state.jobs = [job];
  h.context.finished(job);
  assert.equal(h.state.draft.title, "Current");
});

test("discard control keeps a recoverable copy with its billing identity", () => {
  const h = studio();
  h.nodes.set("#editor", h.node());
  h.context.replaceDraft(script("Edited"), { usage_run_id: "old-run" });
  h.drawEditor();
  h.nodes.get("#discard").onclick();
  assert.equal(h.state.draft, null);
  assert.equal(h.stored("previousDraft").script.title, "Edited");
  assert.equal(h.stored("previousDraft").source.usage_run_id, "old-run");
});

test("render control rejects empty narration without erasing the draft", () => {
  const h = studio();
  h.nodes.set("#editor", h.node());
  h.context.replaceDraft({ ...script("Empty"), scenes: [{ narration: "   " }] });
  let calls = 0;
  h.context.startMake = () => { calls++; };
  h.drawEditor();
  h.nodes.get("#render-btn").onclick();
  assert.equal(calls, 0);
  assert.equal(h.state.draft.title, "Empty");
  assert.equal(h.notices[0].kind, "bad");
});

function videoDrawer(h, state = "unknown") {
  const record = { id: 12, title: "Video", status: "upload-unknown", upload_state: state, video: "short.mp4",
    created_at: "2026-10-19T15:00:00Z", tags: [], metadata: {}, error: "Lost response" };
  h.context.get = async () => record;
  h.context.loadVideoCosts = () => {};
  return record;
}

test("unknown upload offers review actions instead of another upload button", async () => {
  const h = studio();
  videoDrawer(h);
  await h.context.openVideo(12);
  const html = h.nodes.get("#drawer-panel").innerHTML;
  assert.match(html, /Link published video/);
  assert.match(html, /Confirm not uploaded/);
  assert.doesNotMatch(html, /id="d-up"/);
});

test("linking an existing upload only posts the local resolution", async () => {
  const h = studio(), record = videoDrawer(h), requests = [];
  h.context.prompt = () => "existing-id";
  h.context.post = async (url, body) => {
    requests.push({ url, body: plain(body) });
    Object.assign(record, { upload_state: "done", status: "uploaded", youtube_id: "existing-id" });
  };
  await h.context.openVideo(12);
  h.nodes.get("#d-link-upload").onclick();
  await settle();
  assert.deepEqual(requests, [{ url: "/api/videos/12/resolve-upload", body: { youtube_id: "existing-id" } }]);
});

test("cancelled remote ID prompt does not change publication state", async () => {
  const h = studio();
  videoDrawer(h);
  let calls = 0;
  h.context.post = async () => { calls++; };
  await h.context.openVideo(12);
  h.nodes.get("#d-link-upload").onclick();
  await settle();
  assert.equal(calls, 0);
});

test("resetting uncertain upload requires confirmation and does not upload", async () => {
  const h = studio(), record = videoDrawer(h), requests = [];
  h.context.post = async (url, body) => {
    requests.push({ url, body: plain(body) });
    Object.assign(record, { upload_state: "failed", status: "rendered" });
  };
  await h.context.openVideo(12);
  h.context.confirm = () => false;
  h.nodes.get("#d-reset-upload").onclick();
  assert.equal(requests.length, 0);
  h.context.confirm = () => true;
  h.nodes.get("#d-reset-upload").onclick();
  await settle();
  assert.deepEqual(requests, [{ url: "/api/videos/12/resolve-upload", body: { not_uploaded: true } }]);
});

test("failed upload resolution keeps the review action available", async () => {
  const h = studio();
  videoDrawer(h);
  h.context.post = async () => { throw new Error("503"); };
  await h.context.openVideo(12);
  const button = h.nodes.get("#d-reset-upload");
  button.onclick();
  await settle();
  assert.equal(button.disabled, false);
  assert.equal(h.notices.at(-1).kind, "bad");
});

test("failed affiliate autosave survives reload and product grid redraw", async () => {
  const h = studio(), input = h.input(1, "https://example.invalid/new");
  input.dataset = { paff: "1" };
  input.closest = selector => selector === "[data-paff]" ? input : null;
  h.context.bindProductsView();
  const main = h.nodes.get("#main");
  main.oninput({ target: input });
  h.context.post = async () => { throw new Error("503"); };
  await main.onchange({ target: input });
  const reloaded = studio(h.persisted());
  reloaded.nodes.set("#pgrid", reloaded.node());
  reloaded.context.drawProductsGrid([{ id: 1, title: "Product", affiliate_url: "https://example.invalid/old" }]);
  assert.match(reloaded.nodes.get("#pgrid").innerHTML, /value="https:\/\/example.invalid\/new"/);
  assert.equal(reloaded.state.affiliateDrafts[1], input.value);
});

test("successful affiliate autosave clears its persisted draft", async () => {
  const h = studio(), input = h.input(1, "https://example.invalid/new");
  input.dataset = { paff: "1" };
  input.closest = selector => selector === "[data-paff]" ? input : null;
  h.state.prodData.products = [{ id: 1, affiliate_url: "https://example.invalid/old" }];
  h.context.bindProductsView();
  const main = h.nodes.get("#main");
  main.oninput({ target: input });
  h.context.post = async () => ({});
  await main.onchange({ target: input });
  assert.equal(h.state.prodData.products[0].affiliate_url, input.value);
  assert.deepEqual(h.stored("affiliateDrafts"), {});
});

test("clearing an affiliate link saves an empty value", async () => {
  const h = studio(), calls = [];
  h.input(1, "");
  h.state.prodData.products = [{ id: 1, affiliate_url: "old" }];
  h.state.affiliateDrafts[1] = "";
  h.context.post = async (url, body) => { calls.push(body.affiliate_url); };
  await h.context.flushAffiliateInputs([1]);
  assert.deepEqual(calls, [""]);
  assert.equal(h.state.prodData.products[0].affiliate_url, "");
  assert.equal(h.state.affiliateDrafts[1], undefined);
});

test("active upload cannot be restarted from the drawer", async () => {
  for (const state of ["reserved", "uploading"]) {
    const h = studio();
    videoDrawer(h, state);
    await h.context.openVideo(12);
    const html = h.nodes.get("#drawer-panel").innerHTML;
    assert.doesNotMatch(html, /id="d-up"/);
    assert.doesNotMatch(html, /id="d-reset-upload"/);
  }
});
