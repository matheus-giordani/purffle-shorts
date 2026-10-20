"""Persistent resource accounting. Recording failures must never stop video production."""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction
from functools import wraps
from pathlib import Path

from .utils import http, raise_for_status, redact

log = logging.getLogger("purffle")
NANO = 1_000_000_000
SHARED_STAGES = {"planner", "script", "review", "footage", "image", "video", "transcription", "clip", "product-analysis"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_runs (
    id TEXT PRIMARY KEY, parent_id TEXT, source_run_id TEXT, source_video_id INTEGER, idea_id INTEGER,
    kind TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
    finished_at TEXT, elapsed_ms INTEGER, stages TEXT NOT NULL DEFAULT '{}',
    error TEXT, telemetry_complete INTEGER NOT NULL DEFAULT 1, claimed_by TEXT, owner_pid INTEGER
);
CREATE TABLE IF NOT EXISTS usage_events (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, created_at TEXT NOT NULL,
    stage TEXT NOT NULL, shared INTEGER NOT NULL DEFAULT 0,
    provider TEXT NOT NULL, requested_model TEXT NOT NULL, model TEXT NOT NULL, served_provider TEXT,
    request_id TEXT, job_id TEXT, status TEXT NOT NULL, elapsed_ms INTEGER NOT NULL DEFAULT 0,
    units TEXT NOT NULL DEFAULT '{}', actual_nusd INTEGER, estimated_nusd INTEGER,
    cost_source TEXT NOT NULL DEFAULT 'unknown', price_snapshot TEXT,
    error TEXT, sync_attempts INTEGER NOT NULL DEFAULT 0, sync_after REAL NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS usage_external_id ON usage_events(provider, request_id)
    WHERE request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS usage_event_time ON usage_events(created_at);
CREATE INDEX IF NOT EXISTS usage_event_run ON usage_events(run_id);
CREATE INDEX IF NOT EXISTS usage_event_model ON usage_events(provider, model);
CREATE TABLE IF NOT EXISTS usage_outputs (
    video_id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, title TEXT NOT NULL,
    duration REAL NOT NULL, file_bytes INTEGER NOT NULL, artifact_bytes INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_allocations (
    id INTEGER PRIMARY KEY, event_id TEXT NOT NULL, target_type TEXT NOT NULL, target_id INTEGER NOT NULL,
    title TEXT NOT NULL, numerator INTEGER NOT NULL, denominator INTEGER NOT NULL,
    shared INTEGER NOT NULL, UNIQUE(event_id, target_type, target_id)
);
CREATE TABLE IF NOT EXISTS usage_run_products (
    run_id TEXT NOT NULL, product_id INTEGER NOT NULL, PRIMARY KEY(run_id, product_id)
);
CREATE TABLE IF NOT EXISTS cost_settings (
    id INTEGER PRIMARY KEY CHECK(id = 1), value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cost_alerts (
    month TEXT NOT NULL, scope TEXT NOT NULL, threshold INTEGER NOT NULL, seen_at TEXT NOT NULL,
    PRIMARY KEY(month, scope, threshold)
);
"""
DEFAULT_SETTINGS = {"monthly_budget_usd": "", "model_budgets": [], "prices": [],
                    "brl_per_usd": "", "exchange_updated_at": None}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def error_label(exc) -> str:
    """The ledger stores error categories, never provider bodies that could echo user content."""
    status = re.search(r"HTTP (\d{3})", str(exc))
    return type(exc).__name__ + (f" (HTTP {status[1]})" if status else "")


def nano(value) -> int:
    """Convert decimal dollars without losing sub-cent amounts or accepting invalid money."""
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0:
            raise ValueError("USD values must be finite and nonnegative")
        result = int((number * NANO).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if result > 9_000_000_000_000_000_000:
            raise ValueError("USD value is too large")
        return result
    except (InvalidOperation, TypeError) as e:
        raise ValueError("Invalid USD value") from e


def dollars(value: int | None) -> str | None:
    return format(Decimal(value) / NANO, ".9f") if value is not None else None


def cost_status(event: dict) -> str:
    if event["cost_source"] == "free":
        return "free"
    if event["actual_nusd"] is not None:
        return "confirmed"
    if event["estimated_nusd"] is not None:
        return "estimated"
    if event["provider"] == "openrouter" and (event.get("request_id") or event.get("job_id")):
        return "pending"
    return "unknown"


def amount(event: dict) -> int | None:
    return event["actual_nusd"] if event["actual_nusd"] is not None else event["estimated_nusd"]


def estimate(units: dict, price: dict | None) -> int | None:
    if not price:
        return None
    billing = price["billing"]
    if billing == "tokens":
        if not {"input_tokens", "output_tokens"} <= units.keys():
            return None
        cached, written = units.get("cached_tokens", 0), units.get("cache_write_tokens", 0)
        uncached = max(0, units["input_tokens"] - cached - written)
        total = Decimal(uncached) * Decimal(price["input"])
        total += Decimal(units["output_tokens"]) * Decimal(price["output"])
        total += Decimal(cached) * Decimal(price.get("cache_read") or price["input"])
        total += Decimal(written) * Decimal(price.get("cache_write") or price["input"])
        return nano(total / 1_000_000)
    unit = {"characters": "characters", "images": "images", "audio_seconds": "audio_seconds",
            "video_seconds": "video_seconds"}[billing]
    if unit not in units:
        return None
    divisor = 1_000_000 if billing == "characters" else 1
    return nano(Decimal(str(units[unit])) * Decimal(price["rate"]) / divisor)


class Store:
    def __init__(self, history):
        self.history = history

    def settings(self) -> dict:
        rows = self.history._all("SELECT value FROM cost_settings WHERE id = 1")
        return {**DEFAULT_SETTINGS, **(json.loads(rows[0]["value"]) if rows else {})}

    def price(self, provider: str, model: str) -> dict | None:
        return next((p for p in self.settings()["prices"]
                     if p["provider"] == provider and p["model"] == model), None)

    def recover_interrupted(self) -> None:
        for run in self.history._all("SELECT id,owner_pid FROM usage_runs WHERE status='running' AND owner_pid IS NOT NULL"):
            try:
                os.kill(run["owner_pid"], 0)
            except ProcessLookupError:
                with self.history._db() as db:
                    db.execute("UPDATE usage_runs SET status='failed',finished_at=?,telemetry_complete=0,"
                               "error='Interrupted execution' WHERE id=?", (now(), run["id"]))
                    db.execute("UPDATE usage_events SET status='failed',error='Interrupted execution' "
                               "WHERE run_id=? AND status='running'", (run["id"],))
                self.finalize_allocations(run["id"])
            except PermissionError:
                pass  # A process owned by another user is still active.

    def update_event(self, event: dict) -> None:
        # External IDs identify charges, not polling attempts or replayed responses.
        fields = {k: v for k, v in event.items() if k != "id"}
        columns = ", ".join(f"{key} = ?" for key in fields)
        with self.history._db() as db:
            try:
                db.execute(f"UPDATE usage_events SET {columns} WHERE id = ?", (*fields.values(), event["id"]))
            except sqlite3.IntegrityError:
                existing = db.execute("SELECT * FROM usage_events WHERE provider = ? AND request_id = ?",
                                      (event["provider"], event["request_id"])).fetchone()
                if not existing:
                    raise
                if event.get("actual_nusd") is not None:
                    db.execute("UPDATE usage_events SET actual_nusd=?,cost_source=?,model=?,served_provider=? "
                               "WHERE id=?", (event["actual_nusd"], event["cost_source"], event["model"],
                                              event.get("served_provider"), existing["id"]))
                db.execute("DELETE FROM usage_events WHERE id = ?", (event["id"],))

    def allocate(self, db, events: list, targets: list[tuple[str, int, str]], shared: bool) -> None:
        if not targets:
            return
        for event in events:
            for kind, target_id, title in targets:
                db.execute(
                    "INSERT OR IGNORE INTO usage_allocations "
                    "(event_id, target_type, target_id, title, numerator, denominator, shared) VALUES (?,?,?,?,1,?,?)",
                    (event["id"], kind, target_id, title, len(targets), int(shared or len(targets) > 1)))

    def finalize_allocations(self, run_id: str) -> None:
        with self.history._db() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute("SELECT * FROM usage_runs WHERE id = ?", (run_id,)).fetchone()
            own = db.execute("SELECT * FROM usage_outputs WHERE run_id = ? ORDER BY video_id", (run_id,)).fetchall()
            children = db.execute(
                "SELECT o.* FROM usage_outputs o JOIN usage_runs r ON o.run_id = r.id "
                "WHERE r.parent_id = ? AND r.kind = 'translation' ORDER BY o.video_id", (run_id,)).fetchall()
            all_outputs = sorted([*own, *children], key=lambda o: o["video_id"])
            shared_targets = [("video", o["video_id"], o["title"]) for o in all_outputs]
            own_targets = [("video", o["video_id"], o["title"]) for o in own]
            events = db.execute("SELECT id, shared FROM usage_events WHERE run_id = ?", (run_id,)).fetchall()
            self.allocate(db, [e for e in events if e["shared"]], shared_targets, True)
            self.allocate(db, [e for e in events if not e["shared"]], own_targets, False)
            if not all_outputs:
                return
            idea_id = run["idea_id"]
            if run["source_run_id"]:
                source = db.execute("SELECT * FROM usage_runs WHERE id = ?", (run["source_run_id"],)).fetchone()
                if source and source["kind"] == "draft" and not source["claimed_by"]:
                    db.execute("UPDATE usage_runs SET claimed_by = ? WHERE id = ?", (run_id, source["id"]))
                    draft_events = db.execute("SELECT id FROM usage_events WHERE run_id = ?", (source["id"],)).fetchall()
                    self.allocate(db, draft_events, shared_targets, True)
                    idea_id = idea_id or source["idea_id"]
                    if idea_id and own:
                        db.execute("UPDATE ideas SET video_id=? WHERE id=? AND video_id IS NULL",
                                   (own[0]["video_id"], idea_id))
            if idea_id:
                shares = db.execute("SELECT * FROM usage_allocations WHERE target_type = 'idea' AND target_id = ?",
                                    (idea_id,)).fetchall()
                for share in shares:
                    for _, video_id, title in shared_targets:
                        db.execute(
                            "INSERT OR IGNORE INTO usage_allocations "
                            "(event_id,target_type,target_id,title,numerator,denominator,shared) VALUES (?,?,?,?,?,?,1)",
                            (share["event_id"], "video", video_id, title, share["numerator"],
                             share["denominator"] * len(shared_targets)))
                    db.execute("DELETE FROM usage_allocations WHERE id = ?", (share["id"],))
            product_ids = [r[0] for r in db.execute(
                "SELECT product_id FROM usage_run_products WHERE run_id=? OR run_id=?",
                (run_id, run["source_run_id"]))]
            if product_ids:
                marks = ",".join("?" for _ in product_ids)
                shares = db.execute("SELECT * FROM usage_allocations WHERE target_type='product' "
                                    f"AND target_id IN ({marks})", product_ids).fetchall()
                # Several selected products can carry fractions of the same research call.
                by_event: dict[str, Fraction] = {}
                for share in shares:
                    by_event[share["event_id"]] = by_event.get(share["event_id"], Fraction()) + Fraction(
                        share["numerator"], share["denominator"])
                for event_id, fraction in by_event.items():
                    for _, video_id, title in shared_targets:
                        previous = db.execute("SELECT numerator,denominator FROM usage_allocations "
                                              "WHERE event_id=? AND target_type='video' AND target_id=?",
                                              (event_id, video_id)).fetchone()
                        assigned = fraction / len(shared_targets)
                        if previous:
                            assigned += Fraction(previous["numerator"], previous["denominator"])
                        db.execute("INSERT INTO usage_allocations "
                                   "(event_id,target_type,target_id,title,numerator,denominator,shared) "
                                   "VALUES (?,'video',?,?,?,?,1) ON CONFLICT(event_id,target_type,target_id) "
                                   "DO UPDATE SET numerator=excluded.numerator,denominator=excluded.denominator,shared=1",
                                   (event_id, video_id, title, assigned.numerator, assigned.denominator))
                for share in shares:
                    db.execute("DELETE FROM usage_allocations WHERE id=?", (share["id"],))

    def allocate_ideas(self, run_id: str, ideas: list[dict]) -> None:
        with self.history._db() as db:
            events = db.execute("SELECT id FROM usage_events WHERE run_id = ?", (run_id,)).fetchall()
            self.allocate(db, events, [("idea", i["id"], i["subject"]) for i in ideas], True)

    def allocate_products(self, run_id: str, products: list[dict]) -> None:
        with self.history._db() as db:
            events = db.execute("SELECT id FROM usage_events WHERE run_id=?", (run_id,)).fetchall()
            self.allocate(db, events, [("product", p["id"], p["title"]) for p in products], True)

    def splits(self, events: list[dict]) -> dict[str, list[dict]]:
        """Largest-remainder allocation preserves every nanodollar, including delayed charges."""
        wanted = {e["id"]: e for e in events}
        shares: dict[str, list[dict]] = {}
        for row in self.history._all("SELECT * FROM usage_allocations ORDER BY id"):
            if row["event_id"] in wanted:
                shares.setdefault(row["event_id"], []).append(row)
        for event_id, rows in shares.items():
            value = amount(wanted[event_id])
            for row in rows:
                exact = Fraction((value or 0) * row["numerator"], row["denominator"])
                row["amount_nusd"] = int(exact) if value is not None else None
                row["_remainder"] = exact - int(exact)
            if value is not None:
                remainder = value - sum(row["amount_nusd"] for row in rows)
                for row in sorted(rows, key=lambda x: (-x["_remainder"], x["id"]))[:remainder]:
                    row["amount_nusd"] += 1
            for row in rows:
                row.pop("_remainder")
        return shares

    def reconcile(self, settings, *, force: bool = False, limit: int = 20) -> dict:
        self.recover_interrupted()
        if not settings.openrouter_api_key:
            return {"updated": 0, "error": "OPENROUTER_API_KEY is not configured"}
        events = self.history._all(
            "SELECT * FROM usage_events WHERE provider = 'openrouter' AND actual_nusd IS NULL "
            "AND (request_id IS NOT NULL OR job_id IS NOT NULL) AND status != 'running' "
            + ("" if force else "AND sync_after <= ? AND sync_attempts < 8 ")
            + "ORDER BY created_at LIMIT ?", (limit,) if force else (time.time(), limit))
        updated, error = 0, ""
        for event in events:
            try:
                headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
                if event["job_id"]:
                    r = http().get(f"https://openrouter.ai/api/v1/videos/{event['job_id']}",
                                   headers=headers, timeout=10)
                else:
                    r = http().get("https://openrouter.ai/api/v1/generation",
                                   params={"id": event["request_id"]}, headers=headers, timeout=10)
                raise_for_status(r, "OpenRouter cost sync")
                data = r.json()
                data = data.get("data", data)
                cost = (data.get("usage") or {}).get("cost") if isinstance(data.get("usage"), dict) else None
                if cost is None:
                    cost = data.get("total_cost")
                if event["job_id"] and data.get("generation_id"):
                    event["request_id"] = data["generation_id"]
                    if cost is None:
                        response = http().get("https://openrouter.ai/api/v1/generation",
                                              params={"id": event["request_id"]}, headers=headers, timeout=10)
                        raise_for_status(response, "OpenRouter cost sync")
                        billing = response.json().get("data") or {}
                        cost = billing.get("total_cost")
                        data = {**data, **billing}
                if cost is not None:
                    event["actual_nusd"], event["cost_source"] = nano(cost), "reconciled"
                    event["model"] = data.get("model") or event["model"]
                    event["served_provider"] = data.get("provider_name") or event["served_provider"]
                    updated += 1
                units = json.loads(event["units"])
                for source, target in (("native_tokens_prompt", "input_tokens"),
                                       ("native_tokens_completion", "output_tokens"),
                                       ("native_tokens_cached", "cached_tokens"),
                                       ("native_tokens_reasoning", "reasoning_tokens")):
                    if data.get(source) is not None:
                        units[target] = data[source]
                event["units"] = json.dumps(units)
                if event["job_id"] and data.get("generation_id"):
                    event["request_id"] = data["generation_id"]
                if event["job_id"] and data.get("status") in ("failed", "cancelled", "expired"):
                    event["status"] = "failed"
            except Exception as exc:
                error = error_label(exc)
                # Authentication errors are actionable; don't retry every generation in the same batch.
                if "HTTP 401" in error or "HTTP 403" in error:
                    break
            event["sync_attempts"] += 1
            event["sync_after"] = time.time() + min(3600, 5 * 2 ** event["sync_attempts"])
            self.update_event(event)
        return {"updated": updated, "error": error}


@dataclass
class Run:
    store: Store
    id: str
    stages: dict[str, int] = field(default_factory=dict)
    failed: bool = False
    complete: bool = True
    step_name: str = ""
    step_started: float = field(default_factory=time.perf_counter)

    def safe(self, action, *args, **kwargs):
        try:
            return action(*args, **kwargs)
        except Exception as exc:
            self.complete = False
            log.warning("Resource accounting incomplete: %s", redact(exc)[:200])
            return None

    def finish_step(self):
        if self.step_name:
            self.stages[self.step_name] = self.stages.get(self.step_name, 0) + round(
                (time.perf_counter() - self.step_started) * 1000)
        self.step_started = time.perf_counter()


@dataclass(frozen=True)
class Context:
    run: Run
    stage: str = ""
    shared: bool = False


_context: contextvars.ContextVar[Context | None] = contextvars.ContextVar("resource_usage", default=None)
_last_request: contextvars.ContextVar[Request | None] = contextvars.ContextVar("last_resource_request", default=None)


@contextmanager
def operation(history, kind: str, title: str = "", *, child: bool = False, source_run_id: str | None = None,
              source_video_id: int | None = None):
    parent = _context.get()
    if parent and not child:
        yield parent.run
        return
    run = Run(Store(history), uuid.uuid4().hex, step_name=kind)
    run.safe(history._exec, "INSERT INTO usage_runs "
             "(id,parent_id,source_run_id,source_video_id,kind,title,status,started_at,owner_pid) "
             "VALUES (?,?,?,?,?,?,'running',?,?)",
             (run.id, parent.run.id if parent else None, source_run_id, source_video_id, kind, title[:300], now(), os.getpid()))
    token = _context.set(Context(run, kind, kind in SHARED_STAGES))
    started = time.perf_counter()
    error = ""
    try:
        yield run
    except BaseException as exc:
        run.failed, error = True, error_label(exc)
        raise
    finally:
        run.finish_step()
        run.safe(run.store.finalize_allocations, run.id)
        run.safe(history._exec, "UPDATE usage_runs SET status=?, finished_at=?, elapsed_ms=?, stages=?, "
                 "error=?, telemetry_complete=? WHERE id=?",
                 ("failed" if run.failed else "done", now(), round((time.perf_counter() - started) * 1000),
                  json.dumps(run.stages), error, int(run.complete), run.id))
        _context.reset(token)


def tracked(kind: str, *, child: bool = False):
    """Wrap official pipeline entrypoints while retaining their existing return contracts."""
    def decorate(fn):
        @wraps(fn)
        def wrapped(owner, *args, **kwargs):
            title = args[0] if args and isinstance(args[0], str) else kwargs.get("topic") or kind
            with operation(owner.history, kind, title, child=child,
                           source_run_id=kwargs.get("usage_run_id") or getattr(kwargs.get("script"), "_usage_run_id", None),
                           source_video_id=kwargs.get("source_video_id")) as run:
                result = fn(owner, *args, **kwargs)
                outputs = result if isinstance(result, list) else [result]
                for output in outputs:
                    if hasattr(output, "ok"):
                        output.usage_run_id = run.id
                        if not output.ok:
                            run.failed = True
                    elif isinstance(output, tuple) and output and hasattr(output[0], "to_dict"):
                        output[0]._usage_run_id = run.id
                        if getattr(output[1], "idea_id", None):
                            annotate(idea_id=output[1].idea_id)
                return result
        return wrapped
    return decorate


def annotate(**fields):
    ctx = _context.get()
    allowed = {"idea_id", "title"}
    if ctx and fields and fields.keys() <= allowed:
        ctx.run.safe(ctx.run.store.history._exec,
                     "UPDATE usage_runs SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
                     (*fields.values(), ctx.run.id))


def use_products(product_ids: list[int]):
    ctx = _context.get()
    if ctx and product_ids:
        def save():
            with ctx.run.store.history._db() as db:
                db.executemany("INSERT OR IGNORE INTO usage_run_products (run_id,product_id) VALUES (?,?)",
                               [(ctx.run.id, pid) for pid in set(product_ids)])
        ctx.run.safe(save)


def step(name: str):
    ctx = _context.get()
    if ctx:
        ctx.run.finish_step()
        ctx.run.step_name = name
        _context.set(replace(ctx, stage=name, shared=name in SHARED_STAGES))


@contextmanager
def phase(name: str, *, shared: bool | None = None):
    ctx = _context.get()
    if not ctx:
        yield
        return
    token = _context.set(replace(ctx, stage=name, shared=name in SHARED_STAGES if shared is None else shared))
    try:
        yield
    finally:
        _context.reset(token)


def stage(name: str, *, shared: bool | None = None):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with phase(name, shared=shared):
                return fn(*args, **kwargs)
        return wrapped
    return decorate


def free_call(provider: str, model: str):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with request(provider, model, free=True):
                return fn(*args, **kwargs)
        return wrapped
    return decorate


def last_units(**units):
    call, ctx = _last_request.get(), _context.get()
    if call and ctx and call.ctx and call.ctx.run.id == ctx.run.id:
        call.add_units(**units)
        call.__exit__(None, None, None)


def invalid_reply(exc):
    call, ctx = _last_request.get(), _context.get()
    if call and ctx and call.ctx and call.ctx.run.id == ctx.run.id:
        call.__exit__(type(exc), exc, None)


def submit(executor, fn, *args, **kwargs):
    return executor.submit(contextvars.copy_context().run, fn, *args, **kwargs)


def record_video(video_id: int, title: str, path: Path, duration: float):
    ctx = _context.get()
    if not ctx:
        return

    def save():
        kept = sum(p.stat().st_size for p in path.parent.iterdir() if p.is_file())
        ctx.run.store.history._exec(
            "INSERT OR REPLACE INTO usage_outputs (video_id,run_id,title,duration,file_bytes,artifact_bytes) "
            "VALUES (?,?,?,?,?,?)", (video_id, ctx.run.id, title, duration, path.stat().st_size, kept))
    ctx.run.safe(save)


class Request:
    def __init__(self, provider: str, model: str, *, free: bool = False, **units):
        self.ctx, self.started = _context.get(), time.perf_counter()
        self.event = {
            "id": uuid.uuid4().hex, "run_id": self.ctx.run.id if self.ctx else "",
            "created_at": now(), "stage": self.ctx.stage if self.ctx else "", "shared": int(self.ctx.shared) if self.ctx else 0,
            "provider": provider, "requested_model": model, "model": model, "served_provider": None,
            "request_id": None, "job_id": None, "status": "running", "elapsed_ms": 0,
            "units": "{}", "actual_nusd": 0 if free else None, "estimated_nusd": None,
            "cost_source": "free" if free else "unknown", "price_snapshot": None, "error": None,
        }
        self.units = {k: v for k, v in units.items() if v is not None}

    def __enter__(self):
        if self.ctx:
            e = self.event
            price = self.ctx.run.safe(self.ctx.run.store.price, e["provider"], e["model"])
            e["price_snapshot"] = json.dumps(price) if price else None
            self.ctx.run.safe(self.ctx.run.store.history._exec,
                              f"INSERT INTO usage_events ({','.join(e)}) VALUES ({','.join('?' for _ in e)})",
                              tuple(e.values()))
        return self

    def add_units(self, **units):
        self.units.update({k: v for k, v in units.items() if v is not None})

    def capture(self, response=None, data=None):
        if not self.ctx:
            return
        try:
            headers = getattr(response, "headers", {}) or {}
            if data is None:
                try:
                    data = response.json() if response is not None else {}
                except (ValueError, AttributeError, TypeError):
                    data = {}
            if not isinstance(data, dict):
                data = {}
            e = self.event
            e["request_id"] = (data.get("generation_id") or headers.get("X-Generation-Id")
                               or e["request_id"] or data.get("id")) or None
            e["model"] = str(data.get("model") or e["model"])
            e["served_provider"] = str(data.get("provider") or "") or e["served_provider"]
            u = data.get("usage") or {}
            if not isinstance(u, dict):
                u = {}
            if e["provider"] == "openrouter" and u.get("cost") is not None:
                e["actual_nusd"], e["cost_source"] = nano(u["cost"]), "reported"
            inputs, outputs = u.get("prompt_tokens", u.get("input_tokens")), u.get("completion_tokens", u.get("output_tokens"))
            cached = (u.get("prompt_tokens_details") or u.get("input_tokens_details") or {}).get("cached_tokens")
            written = (u.get("prompt_tokens_details") or {}).get("cache_write_tokens")
            if e["provider"] == "anthropic":
                cached, written = u.get("cache_read_input_tokens", 0), u.get("cache_creation_input_tokens", 0)
                if inputs is not None:
                    inputs += cached + written
            reasoning = (u.get("completion_tokens_details") or u.get("output_tokens_details") or {}).get("reasoning_tokens")
            self.add_units(input_tokens=inputs, output_tokens=outputs, cached_tokens=cached,
                           cache_write_tokens=written, reasoning_tokens=reasoning)
            duration = u.get("seconds", data.get("duration"))
            if duration is not None:
                self.add_units(**{"video_seconds" if e["stage"] == "video" else "audio_seconds": duration})
            self.checkpoint()
        except Exception as exc:
            self.ctx.run.complete = False
            log.warning("Could not read resource usage: %s", redact(exc)[:200])

    def checkpoint(self):
        if self.ctx:
            self.event["units"] = json.dumps(self.units)
            self.ctx.run.safe(self.ctx.run.store.update_event, self.event)

    def __exit__(self, exc_type, exc, tb):
        if self.ctx:
            e = self.event
            e["status"] = "failed" if exc is not None else "done"
            e["elapsed_ms"] = round((time.perf_counter() - self.started) * 1000)
            e["error"] = error_label(exc) if exc is not None else None
            if e["actual_nusd"] is None:
                price = json.loads(e["price_snapshot"]) if e["price_snapshot"] else None
                if price and (price["provider"] != e["provider"] or price["model"] != e["model"]):
                    price = None
                e["estimated_nusd"] = self.ctx.run.safe(estimate, self.units, price)
                e["price_snapshot"] = json.dumps(price) if price else None
                if e["estimated_nusd"] is not None:
                    e["cost_source"] = "configured_price"
            self.checkpoint()
        _last_request.set(self)
        return False


def request(provider: str, model: str, *, free: bool = False, **units) -> Request:
    return Request(provider, model, free=free, **units)
