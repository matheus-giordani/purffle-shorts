"""Queries and configuration for the Studio's cost ledger."""

from __future__ import annotations

import csv
import io
import json
import os
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .usage import DEFAULT_SETTINGS, Store, amount, cost_status, dollars, nano, now


def local_zone(settings):
    name = settings.timezone or os.getenv("TZ", "")
    if not name:
        resolved = str(Path("/etc/localtime").resolve())
        if "/zoneinfo/" in resolved:
            name = resolved.split("/zoneinfo/", 1)[1]
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return datetime.now().astimezone().tzinfo


def totals(events: list[dict]) -> dict:
    confirmed = estimated = unknown = failed = 0
    units = defaultdict(float)
    for event in events:
        confirmed += event["actual_nusd"] or 0
        if event["actual_nusd"] is None:
            estimated += event["estimated_nusd"] or 0
        unknown += amount(event) is None
        failed += event["status"] == "failed"
        for key, value in json.loads(event["units"]).items():
            if isinstance(value, (int, float)):
                units[key] += value
    return {"confirmed_usd": dollars(confirmed), "estimated_usd": dollars(estimated),
            "known_usd": dollars(confirmed + estimated), "unknown_calls": unknown,
            "calls": len(events), "failed_calls": failed,
            "pending_calls": sum(cost_status(e) == "pending" for e in events), "units": dict(units)}


class Costs(Store):
    def __init__(self, history, settings):
        super().__init__(history)
        self.zone = local_zone(settings)

    def save_settings(self, data: dict) -> dict:
        if not isinstance(data, dict) or set(data) - set(DEFAULT_SETTINGS):
            raise ValueError("Invalid cost settings")
        current = self.settings()
        value = {**current, **data}

        def money(raw, optional=False):
            if raw is None or str(raw).strip() == "":
                if optional:
                    return ""
                raise ValueError("Enter a nonnegative USD price")
            return dollars(nano(raw))

        value["monthly_budget_usd"] = money(value["monthly_budget_usd"], True)
        fx = value["brl_per_usd"]
        if fx is None or str(fx).strip() == "":
            value["brl_per_usd"] = ""
        else:
            number = Decimal(str(fx))
            if not number.is_finite() or number <= 0 or number > 1_000_000:
                raise ValueError("BRL per USD must be a positive finite number")
            value["brl_per_usd"] = str(number)
        if value["brl_per_usd"] != current["brl_per_usd"]:
            value["exchange_updated_at"] = now()
        else:
            value["exchange_updated_at"] = current["exchange_updated_at"]
        for group in ("model_budgets", "prices"):
            rows, seen = value[group], set()
            if not isinstance(rows, list) or len(rows) > 1000:
                raise ValueError(f"Invalid {group}")
            clean = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError(f"Invalid {group} row")
                provider, model = str(row.get("provider") or "").strip(), str(row.get("model") or "").strip()
                if not provider or (not model and group == "prices") or len(provider) > 80 or len(model) > 200:
                    raise ValueError("Every price needs a provider and model; provider budgets may omit the model")
                if (provider, model) in seen:
                    raise ValueError("A provider/model can appear only once in each table")
                seen.add((provider, model))
                item = {"provider": provider, "model": model}
                if group == "model_budgets":
                    item["budget_usd"] = money(row.get("budget_usd"))
                else:
                    billing = row.get("billing")
                    if billing not in ("tokens", "characters", "images", "audio_seconds", "video_seconds"):
                        raise ValueError("Invalid billing unit")
                    item["billing"] = billing
                    fields = ("input", "output", "cache_read", "cache_write") if billing == "tokens" else ("rate",)
                    for field in fields:
                        item[field] = money(row.get(field), field.startswith("cache_"))
                clean.append(item)
            value[group] = clean
        self.history._exec("INSERT INTO cost_settings(id,value) VALUES(1,?) "
                           "ON CONFLICT(id) DO UPDATE SET value=excluded.value", (json.dumps(value),))
        return value

    def events(self, params: dict | None = None) -> list[dict]:
        params = params or {}
        if params.get("from") and params.get("to") and params["from"] > params["to"]:
            raise ValueError("The start date must not be after the end date")
        clauses, args = [], []
        for field in ("provider", "model", "stage", "status", "run_id"):
            if params.get(field):
                clauses.append(f"e.{field} = ?")
                args.append(str(params[field]))
        for field, operator, offset in (("from", ">=", 0), ("to", "<", 1)):
            if params.get(field):
                try:
                    day = date.fromisoformat(str(params[field])) + timedelta(days=offset)
                except ValueError as exc:
                    raise ValueError("Dates must use YYYY-MM-DD") from exc
                stamp = datetime.combine(day, time.min, self.zone).astimezone(timezone.utc).isoformat()
                clauses.append(f"e.created_at {operator} ?")
                args.append(stamp)
        query = ("SELECT e.*, r.title AS run_title, r.kind, r.status AS run_status, r.telemetry_complete "
                 "FROM usage_events e JOIN usage_runs r ON r.id=e.run_id")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        events = self.history._all(query + " ORDER BY e.created_at DESC, e.id", tuple(args))
        if params.get("cost_status"):
            events = [e for e in events if cost_status(e) == params["cost_status"]]
        return events

    def public_event(self, event: dict) -> dict:
        result = {k: event.get(k) for k in (
            "id", "run_id", "created_at", "stage", "provider", "requested_model", "model", "served_provider",
            "request_id", "job_id", "status", "elapsed_ms", "cost_source", "error", "run_title", "run_status",
            "kind", "telemetry_complete", "sync_attempts")}
        result.update(units=json.loads(event["units"]), cost_status=cost_status(event),
                      cost_usd=dollars(amount(event)), actual_usd=dollars(event["actual_nusd"]),
                      estimated_usd=dollars(event["estimated_nusd"]),
                      price_snapshot=json.loads(event["price_snapshot"]) if event["price_snapshot"] else None)
        return result

    @staticmethod
    def page(rows: list[dict], params: dict) -> dict:
        try:
            page = max(1, int(params.get("page") or 1))
            size = max(1, min(100, int(params.get("page_size") or 25)))
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid pagination") from exc
        start = (page - 1) * size
        return {"rows": rows[start:start + size], "total": len(rows), "page": page, "page_size": size}

    def event_page(self, params: dict) -> dict:
        event_params = {k: v for k, v in params.items() if k != "status"} if params.get("view") == "runs" else params
        events = self.events(event_params)
        if params.get("view") == "runs":
            grouped = defaultdict(list)
            for event in events:
                grouped[event["run_id"]].append(event)
            selected = any(params.get(k) for k in ("provider", "model", "stage", "cost_status", "run_id"))
            rows = []
            for run in self.history._all("SELECT * FROM usage_runs ORDER BY started_at DESC"):
                local_day = datetime.fromisoformat(run["started_at"]).astimezone(self.zone).date().isoformat()
                if selected and run["id"] not in grouped:
                    continue
                if params.get("status") and run["status"] != params["status"]:
                    continue
                if (params.get("from") and local_day < params["from"]) or (
                        params.get("to") and local_day > params["to"]):
                    continue
                run["stages"] = json.loads(run["stages"])
                run["totals"] = totals(grouped[run["id"]])
                rows.append(run)
            return self.page(rows, params)
        return self.page([self.public_event(e) for e in events], params)

    def budgets(self, at: datetime | None = None) -> dict:
        self.recover_interrupted()
        at = (at or datetime.now(timezone.utc)).astimezone(self.zone)
        first = at.date().replace(day=1)
        end = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        events = self.events({"from": first.isoformat(), "to": end.isoformat()})
        settings = self.settings()
        rows, alerts = [], []
        seen = {(r["scope"], r["threshold"]) for r in self.history._all(
            "SELECT scope, threshold FROM cost_alerts WHERE month=?", (first.strftime("%Y-%m"),))}
        entries = [("all", "All models", settings["monthly_budget_usd"], events)]
        for b in settings["model_budgets"]:
            entries.append((json.dumps([b["provider"], b["model"]]),
                            f"{b['provider']} / {b['model']}" if b["model"] else b["provider"],
                            b["budget_usd"], [e for e in events if e["provider"] == b["provider"]
                                             and (not b["model"] or e["model"] == b["model"])]))
        for scope, label, limit, selected in entries:
            if limit == "":
                continue
            limit_nusd = nano(limit)
            summary = totals(selected)
            spent = nano(summary["known_usd"])
            percent = round(spent * 100 / limit_nusd, 1) if limit_nusd else (100 if spent else 0)
            row = {"scope": scope, "label": label, "budget_usd": limit,
                   "spent_usd": dollars(spent), "remaining_usd": dollars(max(0, limit_nusd - spent)),
                   "percent": percent, "unknown_calls": summary["unknown_calls"]}
            rows.append(row)
            for threshold in (80, 100):
                if spent and (spent * 100 >= limit_nusd * threshold) and (scope, threshold) not in seen:
                    alerts.append({**row, "threshold": threshold, "month": first.strftime("%Y-%m")})
        return {"month": first.strftime("%Y-%m"), "rows": rows, "alerts": alerts,
                "known_usd": totals(events)["known_usd"], "unknown_calls": totals(events)["unknown_calls"]}

    def acknowledge(self, alerts: list[dict]) -> None:
        valid = {(a["month"], a["scope"], a["threshold"]) for a in self.budgets()["alerts"]}
        with self.history._db() as db:
            for alert in alerts[:200]:
                key = (alert.get("month"), alert.get("scope"), alert.get("threshold"))
                if key in valid:
                    db.execute("INSERT OR IGNORE INTO cost_alerts(month,scope,threshold,seen_at) VALUES(?,?,?,?)",
                               (*key, now()))

    def overview(self, params: dict) -> dict:
        params = dict(params)
        if not params.get("all_time") and not params.get("from") and not params.get("to"):
            today = datetime.now(timezone.utc).astimezone(self.zone).date()
            params.update({"from": today.replace(day=1).isoformat(), "to": today.isoformat()})
        events = self.events(params)
        models, days = defaultdict(list), defaultdict(list)
        for event in events:
            models[(event["provider"], event["model"])].append(event)
            day = datetime.fromisoformat(event["created_at"]).astimezone(self.zone).date().isoformat()
            days[day].append(event)
        model_rows = []
        for (provider, model), grouped in models.items():
            model_rows.append({"provider": provider, "model": model, **totals(grouped),
                               "elapsed_ms": sum(e["elapsed_ms"] for e in grouped),
                               "stages": sorted({e["stage"] for e in grouped})})
        model_rows.sort(key=lambda x: Decimal(x["known_usd"]), reverse=True)
        splits = self.splits(events)
        assigned = sum(s["amount_nusd"] or 0 for values in splits.values() for s in values if s["target_type"] == "video")
        summary = totals(events)
        summary["unassigned_usd"] = dollars(nano(summary["known_usd"]) - assigned)
        options = self.history._all("SELECT DISTINCT provider, model, stage FROM usage_events ORDER BY provider,model")
        return {"totals": summary, "models": model_rows, "period": {k: params.get(k, "") for k in ("from", "to")},
                "daily": [{"date": day, **totals(grouped)} for day, grouped in sorted(days.items())],
                "budgets": self.budgets(), "settings": self.settings(),
                "options": {key: sorted({e[key] for e in options}) for key in ("provider", "model", "stage")},
                "timezone": str(self.zone),
                "incomplete_runs": self.history._all(
                    "SELECT id,title FROM usage_runs WHERE telemetry_complete=0 ORDER BY started_at DESC LIMIT 20")}

    def video_details(self, video_id: int, events: list[dict] | None = None, splits: dict | None = None) -> dict | None:
        output_rows = self.history._all(
            "SELECT o.*, r.stages, r.elapsed_ms, r.source_video_id, r.source_run_id, r.telemetry_complete,"
            "v.id AS present FROM usage_outputs o JOIN usage_runs r ON r.id=o.run_id "
            "LEFT JOIN videos v ON v.id=o.video_id WHERE o.video_id=?", (video_id,))
        if not output_rows:
            legacy = self.history.get(video_id)
            return {"video_id": video_id, "title": legacy["title"], "tracked": False} if legacy else None
        output = output_rows[0]
        events = self.events() if events is None else events
        splits = self.splits(events) if splits is None else splits
        selected, direct, shared, unknown = [], 0, 0, 0
        stages, units = defaultdict(lambda: {"direct": 0, "shared": 0, "calls": 0, "unknown": 0}), defaultdict(float)
        for event in events:
            share = next((s for s in splits.get(event["id"], [])
                          if s["target_type"] == "video" and s["target_id"] == video_id), None)
            if not share:
                continue
            value = share["amount_nusd"]
            key = "shared" if share["shared"] else "direct"
            if key == "shared":
                shared += value or 0
            else:
                direct += value or 0
            unknown += value is None
            stages[event["stage"]][key] += value or 0
            stages[event["stage"]]["calls"] += 1
            stages[event["stage"]]["unknown"] += value is None
            row = self.public_event(event)
            row.update(allocated_usd=dollars(value), shared=bool(share["shared"]),
                       fraction=f"{share['numerator']}/{share['denominator']}")
            selected.append(row)
            for unit, quantity in json.loads(event["units"]).items():
                if isinstance(quantity, (int, float)):
                    units[unit] += quantity * share["numerator"] / share["denominator"]
        return {"video_id": video_id, "title": output["title"], "tracked": True, "deleted": not output["present"],
                "run_id": output["run_id"], "source_run_id": output["source_run_id"],
                "source_video_id": output["source_video_id"],
                "direct_usd": dollars(direct), "shared_usd": dollars(shared), "known_usd": dollars(direct + shared),
                "unknown_calls": unknown, "telemetry_complete": bool(output["telemetry_complete"]),
                "duration": output["duration"], "file_bytes": output["file_bytes"],
                "artifact_bytes": output["artifact_bytes"], "elapsed_ms": output["elapsed_ms"],
                "stage_ms": json.loads(output["stages"]), "units": dict(units), "events": selected,
                "stages": [{"stage": stage, "direct_usd": dollars(value["direct"]),
                            "shared_usd": dollars(value["shared"]), "calls": value["calls"],
                            "unknown_calls": value["unknown"]} for stage, value in stages.items()]}

    def video_page(self, params: dict) -> dict:
        events = self.events(params)
        splits = self.splits(events)
        by_video = defaultdict(list)
        for event in events:
            for share in splits.get(event["id"], []):
                if share["target_type"] == "video":
                    by_video[share["target_id"]].append(event)
        filtered = any(params.get(k) for k in (
            "from", "to", "provider", "model", "stage", "status", "cost_status", "run_id"))
        outputs = self.history._all("SELECT video_id FROM usage_outputs ORDER BY video_id DESC")
        page = self.page([o for o in outputs if not filtered or o["video_id"] in by_video], params)
        rows = []
        for output in page["rows"]:
            detail = self.video_details(output["video_id"], by_video[output["video_id"]], splits)
            detail["calls"] = len(detail.pop("events"))
            rows.append(detail)
        return {**page, "rows": rows}

    def export(self, params: dict) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        fields = ("created_at", "run_id", "run_title", "kind", "run_status", "stage", "provider",
                  "requested_model", "model", "served_provider", "status", "cost_status", "cost_source",
                  "actual_usd", "estimated_usd", "cost_usd", "elapsed_ms", "request_id", "job_id", "units",
                  "price_snapshot")
        writer.writerow(fields)
        for event in self.events(params):
            public = self.public_event(event)
            row = []
            for key in fields:
                value = public[key]
                text = json.dumps(value) if isinstance(value, dict) else str(value if value is not None else "")
                if text.lstrip().startswith(("=", "+", "-", "@")):
                    text = "'" + text
                row.append(text)
            writer.writerow(row)
        return buf.getvalue()
