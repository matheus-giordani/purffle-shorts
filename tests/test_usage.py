"""Accounting invariants with simulated responses; no model credentials or paid calls."""

import base64
import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from purffle_shorts import llm, media, tts, usage
from purffle_shorts.costs import Costs
from purffle_shorts.history import History


@pytest.fixture
def ledger(settings):
    return Costs(History(settings.data_path / "history.db"), settings.with_overrides(timezone="America/Maceio"))


def charge(cost=None, *, provider="openrouter", model="test/model", request_id=None, **units):
    with usage.request(provider, model, **units) as call:
        call.capture(data={"id": request_id, "usage": {"cost": cost} if cost is not None else {}})
    return call


def output(ledger, settings, name):
    path = settings.out_path / name / "short.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"fake video")
    vid = ledger.history.add_video(title=name, status="rendered", video_path=str(path), duration=12)
    usage.record_video(vid, name, path, 12)
    return vid


def test_zero_tiny_missing_and_free_are_distinct(ledger):
    with usage.operation(ledger.history, "make"):
        charge("0")
        charge("0.000000001")
        charge()
        charge(provider="local")
        with usage.request("edge", "voice", free=True):
            pass
    events = ledger.events()
    assert sorted(usage.cost_status(e) for e in events) == ["confirmed", "confirmed", "free", "unknown", "unknown"]
    summary = ledger.overview({})["totals"]
    assert summary["confirmed_usd"] == "0.000000001"
    assert summary["unknown_calls"] == 2
    for invalid in ("NaN", "Infinity", "-1"):
        with pytest.raises(ValueError):
            usage.nano(invalid)


def test_token_estimate_cache_and_immutable_price_snapshot(ledger):
    price = {"provider": "openai", "model": "m", "billing": "tokens", "input": "2", "output": "8",
             "cache_read": ".5", "cache_write": "3"}
    ledger.save_settings({"prices": [price]})
    with usage.operation(ledger.history, "make"):
        with usage.request("openai", "m") as call:
            ledger.save_settings({"prices": [{**price, "input": "1000"}]})
            call.capture(data={"usage": {"prompt_tokens": 100, "completion_tokens": 20,
                                       "prompt_tokens_details": {"cached_tokens": 50, "cache_write_tokens": 10},
                                       "completion_tokens_details": {"reasoning_tokens": 10}}})
    event = ledger.events()[0]
    assert event["estimated_nusd"] == usage.nano(".000295")
    assert json.loads(event["price_snapshot"])["input"] == "2.000000000"
    assert json.loads(event["units"])["reasoning_tokens"] == 10


def test_reconciliation_replaces_estimate_and_is_idempotent(ledger, settings, monkeypatch):
    ledger.save_settings({"prices": [{"provider": "openrouter", "model": "m", "billing": "characters", "rate": "5"}]})
    with usage.operation(ledger.history, "make"):
        charge(model="m", request_id="gen-tts", characters=100)
    called = []

    def get(*args, **kwargs):
        called.append(kwargs["params"]["id"])
        return Response({"data": {"total_cost": "0", "native_tokens_prompt": 100, "native_tokens_completion": 22}})
    monkeypatch.setattr(usage, "http", lambda: SimpleNamespace(get=get))
    s = settings.with_overrides(openrouter_api_key="fake")
    assert ledger.reconcile(s)["updated"] == 1
    assert ledger.reconcile(s)["updated"] == 0
    event = ledger.events()[0]
    assert event["actual_nusd"] == 0 and event["estimated_nusd"] == usage.nano(".0005")
    assert json.loads(event["units"])["output_tokens"] == 22
    assert ledger.overview({})["totals"]["estimated_usd"] == "0.000000000"
    assert called == ["gen-tts"]


def test_draft_claimed_once_and_deletion_preserves_spend(ledger, settings):
    with usage.operation(ledger.history, "draft") as draft:
        charge(".2")
    with usage.operation(ledger.history, "make", source_run_id=draft.id):
        charge(".1")
        first = output(ledger, settings, "first")
    with usage.operation(ledger.history, "make", source_run_id=draft.id, source_video_id=first):
        charge(".05")
        second = output(ledger, settings, "second")
    assert ledger.video_details(first)["known_usd"] == "0.300000000"
    assert ledger.video_details(second)["known_usd"] == "0.050000000"
    ledger.history.delete_video(first)
    assert ledger.video_details(first)["deleted"]
    assert ledger.overview({})["totals"]["known_usd"] == "0.350000000"
    assert ledger.video_details(second)["source_video_id"] == first


def test_translations_share_assets_but_keep_their_own_voice(ledger, settings):
    with usage.operation(ledger.history, "make"):
        with usage.phase("image"):
            charge("0.000000005")
        with usage.phase("voice"):
            charge(".1")
        first = output(ledger, settings, "original")
        with usage.operation(ledger.history, "translation", child=True):
            charge(".2")
            second = output(ledger, settings, "translated")
    a, b = ledger.video_details(first), ledger.video_details(second)
    assert a["direct_usd"] == "0.100000000"
    assert b["direct_usd"] == "0.200000000"
    assert usage.nano(a["shared_usd"]) + usage.nano(b["shared_usd"]) == 5
    assert usage.nano(a["known_usd"]) + usage.nano(b["known_usd"]) == usage.nano(".300000005")
    assert ledger.overview({})["totals"]["unassigned_usd"] == "0.000000000"


def test_planner_share_follows_idea_and_unconsumed_share_remains_unassigned(ledger, settings):
    ideas = [{"id": ledger.history.add_idea(name), "subject": name} for name in ("first", "unused")]
    with usage.operation(ledger.history, "planner") as run:
        charge(".3")
        ledger.allocate_ideas(run.id, ideas)
    with usage.operation(ledger.history, "draft") as draft:
        usage.annotate(idea_id=ideas[0]["id"])
        charge(".1")
    with usage.operation(ledger.history, "make", source_run_id=draft.id):
        first = output(ledger, settings, "idea-video")
        with usage.operation(ledger.history, "translation", child=True):
            second = output(ledger, settings, "idea-translation")
    assert ledger.video_details(first)["known_usd"] == "0.125000000"
    assert ledger.video_details(second)["known_usd"] == "0.125000000"
    ledger.history.delete_idea(ideas[1]["id"])
    assert ledger.overview({})["totals"]["unassigned_usd"] == "0.150000000"


def test_failed_and_parallel_runs_keep_their_events(ledger):
    def work(n):
        with usage.operation(ledger.history, "make", str(n)) as run:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [usage.submit(pool, charge, str(n / 100), model=str(n)) for _ in range(2)]
                for future in futures:
                    future.result()
            return run.id
    with ThreadPoolExecutor(max_workers=3) as pool:
        ids = list(pool.map(work, range(1, 4)))
    for index, run_id in enumerate(ids, 1):
        events = ledger.events({"run_id": run_id})
        assert len(events) == 2 and {e["model"] for e in events} == {str(index)}
    with pytest.raises(RuntimeError), usage.operation(ledger.history, "make"):
        charge(".7")
        raise RuntimeError("render failed")
    assert ledger.event_page({"view": "runs", "status": "failed"})["rows"][0]["totals"]["known_usd"] == "0.700000000"


def test_budget_month_timezone_fx_alerts_and_restart(ledger):
    ledger.save_settings({"monthly_budget_usd": "1", "brl_per_usd": "5.2",
                          "model_budgets": [{"provider": "openrouter", "model": "test/model", "budget_usd": "1"}]})
    with usage.operation(ledger.history, "make"):
        charge(".8")
    # 02:59 UTC still belongs to the previous day in Maceio.
    event = ledger.events()[0]
    ledger.history._exec("UPDATE usage_events SET created_at=? WHERE id=?",
                         ("2026-11-01T02:59:00+00:00", event["id"]))
    at = datetime(2026, 10, 31, 18, tzinfo=timezone.utc)
    budget = ledger.budgets(at)
    assert budget["known_usd"] == "0.800000000"
    assert len(budget["alerts"]) == 2 and {a["threshold"] for a in budget["alerts"]} == {80}
    assert ledger.budgets(datetime(2026, 11, 1, 4, tzinfo=timezone.utc))["known_usd"] == "0.000000000"
    with ledger.history._db() as db:
        db.executemany("INSERT INTO cost_alerts VALUES(?,?,?,?)",
                       [(a["month"], a["scope"], a["threshold"], usage.now()) for a in budget["alerts"]])
    reloaded = Costs(History(ledger.history.path), SimpleNamespace(timezone="America/Maceio"))
    assert not reloaded.budgets(at)["alerts"]
    assert reloaded.settings()["brl_per_usd"] == "5.2"


def test_filters_full_history_pagination_csv_and_legacy(ledger):
    with usage.operation(ledger.history, "make", "=danger"):
        charge(".000000001")
    event = ledger.history._all("SELECT * FROM usage_events")[0]
    with ledger.history._db() as db:
        for n in range(1005):
            clone = {**event, "id": f"event-{n}"}
            db.execute(f"INSERT INTO usage_events({','.join(clone)}) VALUES({','.join('?' for _ in clone)})",
                       tuple(clone.values()))
    page = ledger.event_page({"provider": "openrouter", "page": "41", "page_size": "25"})
    assert page["total"] == 1006 and len(page["rows"]) == 6
    assert ledger.overview({})["totals"]["known_usd"] == "0.000001006"
    assert ledger.event_page({"cost_status": "unknown"})["total"] == 0
    exported = list(csv.DictReader(io.StringIO(ledger.export({}))))
    assert exported[0]["run_title"] == "'=danger" and len(exported) == 1006
    vid = ledger.history.add_video(title="old", status="rendered")
    assert not ledger.video_details(vid)["tracked"]
    for params in ({"from": "yesterday"}, {"page": "NaN"}):
        with pytest.raises(ValueError):
            ledger.event_page(params)


class Response:
    def __init__(self, data=None, *, headers=None, content=b"audio", status=200):
        self.data, self.headers, self.content = data or {}, headers or {}, content
        self.status_code, self.text = status, "fake response"

    def json(self):
        return self.data


def test_charged_invalid_json_and_fallback_are_recorded(ledger, settings, monkeypatch):
    responses = iter([
        Response({"id": "gen-invalid", "usage": {"cost": ".01"},
                  "choices": [{"message": {"content": "invalid"}}]}),
        Response({"id": "gen-valid", "usage": {"cost": ".02"},
                  "choices": [{"message": {"content": '{"ok":true}'}}]})
    ])
    monkeypatch.setattr(llm, "http", lambda: SimpleNamespace(post=lambda *a, **kw: next(responses)))
    monkeypatch.setattr("purffle_shorts.utils.time.sleep", lambda n: None)
    model = llm.LLM(settings.with_overrides(llm_provider="openrouter", openrouter_api_key="fake"))
    with usage.operation(ledger.history, "make"):
        assert model.complete_json("system", "input") == {"ok": True}
    assert ledger.overview({})["totals"]["known_usd"] == "0.030000000"
    assert {e["status"] for e in ledger.events()} == {"failed", "done"}


def test_image_and_video_calls_capture_real_cost_once(ledger, settings, monkeypatch, tmp_path):
    image = Response({"data": [{"b64_json": base64.b64encode(b"png").decode()}], "usage": {"cost": ".018"}})
    submit = Response({"id": "job-1", "status": "pending"})
    polling = iter([Response({"id": "job-1", "status": "in_progress"}),
                    Response({"id": "job-1", "generation_id": "gen-video", "status": "completed",
                              "usage": {"cost": ".3"}})])
    monkeypatch.setattr(media, "http", lambda: SimpleNamespace(
        post=lambda url, **kw: image if url.endswith("images") else submit,
        get=lambda *a, **kw: next(polling)))
    monkeypatch.setattr(media.time, "sleep", lambda n: None)
    monkeypatch.setattr(media, "download", lambda url, dest, **kw: dest)
    s = settings.with_overrides(openrouter_api_key="fake")
    with usage.operation(ledger.history, "make"):
        media.openrouter_image("a mountain", tmp_path / "image.png", s)
        media.openrouter_video("clouds", tmp_path / "video.mp4", s, 5)
    events = ledger.events()
    assert len(events) == 2
    assert ledger.overview({})["totals"]["known_usd"] == "0.318000000"
    assert {e["stage"] for e in events} == {"image", "video"}
    assert next(e for e in events if e["stage"] == "video")["job_id"] == "job-1"


def test_tts_header_and_unknown_charge_survive_failure(ledger, settings, monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "http", lambda: SimpleNamespace(
        post=lambda *a, **kw: Response(headers={"X-Generation-Id": "gen-speech"})))
    with usage.operation(ledger.history, "make"):
        tts._openrouter("hello", tmp_path, settings.with_overrides(openrouter_api_key="fake"))
    event = ledger.events()[0]
    assert event["request_id"] == "gen-speech"
    assert usage.cost_status(event) == "pending"
    assert json.loads(event["units"])["characters"] == 5


def test_telemetry_failure_does_not_stop_work(ledger, monkeypatch):
    original = ledger.history._exec

    def fail_event(sql, args=()):
        if "usage_events" in sql:
            raise OSError("disk error")
        return original(sql, args)
    monkeypatch.setattr(ledger.history, "_exec", fail_event)
    with usage.operation(ledger.history, "make"):
        charge(".1")
    run = ledger.history._all("SELECT * FROM usage_runs")[0]
    assert run["status"] == "done" and not run["telemetry_complete"]


def test_replayed_generation_updates_the_original_charge(ledger):
    with usage.operation(ledger.history, "make"):
        charge(request_id="gen-replay")
        charge(".123", request_id="gen-replay")
    assert len(ledger.events()) == 1
    assert ledger.overview({})["totals"]["known_usd"] == "0.123000000"


def test_provider_fallback_tracks_failed_attempt_and_served_model(ledger, settings, monkeypatch):
    requests = []

    def post(url, **kw):
        requests.append(url)
        if "openrouter" in url:
            return Response({"id": "gen-refused", "usage": {"cost": ".01"}}, status=400)
        return Response({"model": "served-model", "usage": {"prompt_tokens": 10, "completion_tokens": 4},
                         "choices": [{"message": {"content": '{"ok":true}'}}]})
    monkeypatch.setattr(llm, "http", lambda: SimpleNamespace(post=post))
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    model = llm.LLM(settings.with_overrides(llm_provider="openrouter", openrouter_api_key="fake",
                                           llm_fallbacks=["openai"], openai_api_key="fake"))
    with usage.operation(ledger.history, "make"):
        assert model.complete_json("system", "user") == {"ok": True}
    assert len(requests) == 2
    events = ledger.events()
    assert {e["provider"] for e in events} == {"openrouter", "openai"}
    assert next(e for e in events if e["provider"] == "openrouter")["status"] == "failed"
    assert next(e for e in events if e["provider"] == "openai")["model"] == "served-model"


def test_interrupted_async_video_is_recovered_and_billed(ledger, settings, monkeypatch):
    with usage.operation(ledger.history, "make") as run:
        call = charge(request_id="job-recover", video_seconds=5)
    ledger.history._exec("UPDATE usage_runs SET status='running',owner_pid=99999999 WHERE id=?", (run.id,))
    ledger.history._exec("UPDATE usage_events SET status='running',job_id='job-recover' WHERE id=?", (call.event["id"],))
    monkeypatch.setattr(usage.os, "kill", lambda *a: (_ for _ in ()).throw(ProcessLookupError()))
    responses = iter([Response({"id": "job-recover", "status": "completed", "generation_id": "gen-recover"}),
                      Response({"data": {"total_cost": ".6"}})])
    monkeypatch.setattr(usage, "http", lambda: SimpleNamespace(get=lambda *a, **kw: next(responses)))
    s = settings.with_overrides(openrouter_api_key="fake")
    assert ledger.reconcile(s)["updated"] == 1
    assert ledger.reconcile(s, force=True)["updated"] == 0
    event = ledger.events()[0]
    assert event["actual_nusd"] == usage.nano(".6") and event["status"] == "failed"
    assert event["error"] == "Interrupted execution"
    assert event["request_id"] == "gen-recover"


def test_partial_batch_only_allocates_to_completed_outputs(ledger, settings):
    with usage.operation(ledger.history, "clip") as run:
        charge(".3")
        first = output(ledger, settings, "only-completed-clip")
        run.failed = True  # A later clip failed before producing an output.
    assert ledger.video_details(first)["shared_usd"] == "0.300000000"
    assert ledger.overview({})["totals"]["unassigned_usd"] == "0.000000000"


def test_provider_budget_counts_models_and_alerts_at_one_hundred(ledger):
    ledger.save_settings({"model_budgets": [{"provider": "openrouter", "model": "", "budget_usd": "1"}]})
    with usage.operation(ledger.history, "make"):
        charge(".4", model="a")
        charge(".6", model="b")
        charge()
    budget = ledger.budgets()
    assert budget["rows"][0]["percent"] == 100
    assert budget["rows"][0]["unknown_calls"] == 1
    assert {a["threshold"] for a in budget["alerts"]} == {80, 100}
    ledger.acknowledge(budget["alerts"])
    assert not ledger.budgets()["alerts"]


@pytest.mark.parametrize("billing,units,rate,expected", [
    ("images", {"images": 2}, ".03", ".06"),
    ("audio_seconds", {"audio_seconds": 12.5}, ".001", ".0125"),
    ("video_seconds", {"video_seconds": 6}, ".1", ".6"),
    ("characters", {"characters": 100}, "5", ".0005"),
])
def test_resource_price_estimates(billing, units, rate, expected):
    assert usage.estimate(units, {"billing": billing, "rate": rate}) == usage.nano(expected)


def test_all_history_includes_costs_before_current_month(ledger):
    with usage.operation(ledger.history, "make"):
        charge(".2")
    ledger.history._exec("UPDATE usage_events SET created_at='2020-01-01T00:00:00+00:00'")
    assert ledger.overview({})["totals"]["calls"] == 0
    assert ledger.overview({"all_time": "1"})["totals"]["known_usd"] == "0.200000000"


@pytest.mark.parametrize("valid", [False, True])
def test_transcription_usage_and_invalid_paid_reply(ledger, settings, monkeypatch, tmp_path, valid):
    from purffle_shorts import clipper

    data = {"id": "gen-stt", "usage": {"cost": ".04", "seconds": 8},
            "words": [{"word": "Hello", "start": 0, "end": 1}] if valid else []}
    monkeypatch.setattr(clipper.ffmpeg, "run", lambda *a, **kw: (tmp_path / "audio.mp3").write_bytes(b"audio"))
    monkeypatch.setattr(clipper.ffmpeg, "duration", lambda *a: 8)
    monkeypatch.setattr(clipper, "http", lambda: SimpleNamespace(post=lambda *a, **kw: Response(data)))
    s = settings.with_overrides(openrouter_api_key="fake", clip_transcription_model="stt-model")
    with usage.operation(ledger.history, "clip"):
        if valid:
            assert clipper.transcribe(tmp_path / "video.mp4", tmp_path, s)[0].text == "Hello"
        else:
            with pytest.raises(clipper.PermanentError):
                clipper.transcribe(tmp_path / "video.mp4", tmp_path, s)
    event = ledger.events()[0]
    assert event["actual_nusd"] == usage.nano(".04") and event["stage"] == "transcription"
    assert json.loads(event["units"])["audio_seconds"] == 8
    assert event["status"] == ("done" if valid else "failed")


def test_pollinations_retries_record_each_attempt(ledger, monkeypatch, tmp_path):
    attempts = []

    def download(*a, **kw):
        assert kw["attempts"] == 1
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("temporary failure")
        return a[1]
    monkeypatch.setattr(media, "download", download)
    monkeypatch.setattr("purffle_shorts.utils.time.sleep", lambda n: None)
    with usage.operation(ledger.history, "make"):
        media.pollinations_image("mountain", tmp_path / "image.jpg", 720, 1280)
    assert len(ledger.events()) == 2
    assert {e["status"] for e in ledger.events()} == {"failed", "done"}


def test_selected_idea_claim_is_atomic_across_history_instances(ledger):
    idea_id = ledger.history.add_idea("Selected topic")

    def claim(_):
        return History(ledger.history.path).claim_idea(idea_id)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(claim, range(4)))
    assert sum(row is not None for row in results) == 1
    assert next(row for row in results if row)["id"] == idea_id


def test_pipeline_planning_draft_and_repeated_renders_keep_identity(settings, monkeypatch):
    from purffle_shorts import pipeline, planner

    class Model:
        label = "metered:model"
        providers = [object()]

        def __init__(self, settings):
            pass

        def complete_json(self, system, *a, **kw):
            if "content strategist" in system:
                charge(".2")
                return {"ideas": [{"subject": "Why cats purr", "style": "facts", "angle": "Purring"},
                                  {"subject": "Why dogs dream", "style": "facts", "angle": "Dreams"}]}
            charge(".03")
            return {"title": "Why cats purr", "scenes": [{"narration": "Cats purr for several reasons.",
                                                          "search_query": "cat"}]}
    monkeypatch.setattr(pipeline, "LLM", Model)
    s = settings.with_overrides(script_review="off")
    studio = pipeline.Studio(s)
    ledger = Costs(studio.history, s)
    ideas = planner.plan_ideas(Model(s), s, studio.history, 2)
    script, pick, _ = studio.draft(idea_id=ideas[0]["id"])
    assert pick.idea_id == ideas[0]["id"] and script._usage_run_id

    def produce(self, script, *a, **kw):
        with usage.phase("voice", shared=False):
            charge(".02")
        vid = output(ledger, s, f"render-{len(ledger.history.recent())}")
        return pipeline.Result(True, title=script.title, record_id=vid)
    monkeypatch.setattr(pipeline.Studio, "produce", produce)
    first = studio.make(script=script)
    second = studio.make(script=script, source_video_id=first.record_id)
    assert first.usage_run_id != second.usage_run_id
    assert ledger.video_details(first.record_id)["known_usd"] == "0.150000000"
    assert ledger.video_details(second.record_id)["known_usd"] == "0.020000000"
    assert ledger.overview({})["totals"]["unassigned_usd"] == "0.100000000"
    assert next(i for i in ledger.history.ideas("used") if i["id"] == pick.idea_id)["video_id"] == first.record_id


def test_video_pagination_filters_before_loading_details(ledger, settings, monkeypatch):
    for n in range(4):
        with usage.operation(ledger.history, "make") as run:
            charge(".1", model="selected" if n % 2 else "other")
            output(ledger, settings, f"paged-{n}")
    last_run = run.id
    loaded = []
    real = ledger.video_details

    def detail(*args, **kw):
        loaded.append(args[0])
        return real(*args, **kw)
    monkeypatch.setattr(ledger, "video_details", detail)
    page = ledger.video_page({"model": "selected", "page": "2", "page_size": "1"})
    assert page["total"] == 2 and len(page["rows"]) == len(loaded) == 1
    assert page["rows"][0]["known_usd"] == "0.100000000"
    page = ledger.video_page({"run_id": last_run})
    assert page["total"] == 1 and page["rows"][0]["run_id"] == last_run


@pytest.mark.parametrize("value", [
    {"brl_per_usd": "NaN"}, {"monthly_budget_usd": "-1"},
    {"prices": [{"provider": "openai", "model": "m", "billing": "tokens", "input": "", "output": "1"}]},
])
def test_settings_validation(ledger, value):
    with pytest.raises((ValueError, ArithmeticError)):
        ledger.save_settings(value)
