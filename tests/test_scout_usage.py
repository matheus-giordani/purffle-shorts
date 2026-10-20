"""Product research accounting with fake providers and temporary SQLite history."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from purffle_shorts import products, usage
from purffle_shorts.costs import Costs
from purffle_shorts.history import History

from .test_usage import Response, charge, output


@pytest.fixture
def ledger(settings):
    return Costs(History(settings.data_path / "history.db"), settings.with_overrides(timezone="UTC"))


@pytest.fixture
def catalog(monkeypatch):
    items = [{"title": f"Product {n}", "external_url": f"https://example.invalid/products/{n}",
              "benefits": ["Extracted feature"], "images": [f"https://example.invalid/{n}.jpg"]}
             for n in range(3)]
    monkeypatch.setattr(products, "scout_shopify_store", lambda *a, **kw: deepcopy(items))
    return items


class Model:
    def __init__(self, cost=".3", error=None, request_id=None):
        self.cost, self.error, self.request_id = cost, error, request_id
        self.calls = 0

    def complete_json(self, *args, **kwargs):
        self.calls += 1
        with usage.request("openrouter", "test/model", characters=1000) as call:
            call.capture(data={"id": self.request_id, "usage": {"cost": self.cost} if self.cost is not None else {}})
            if self.error:
                raise self.error
        return {"products": []}


def scout(ledger, settings, count=2, model=None):
    return products.run_scout(ledger.history, settings, model, mode="url", url="https://example.invalid",
                              limit=count)


def make(ledger, settings, name, ids=(), source_run_id=None, voice=None):
    with usage.operation(ledger.history, "make", source_run_id=source_run_id) as run:
        usage.use_products(list(ids))
        if voice is not None:
            with usage.phase("voice", shared=False):
                charge(voice)
        vid = output(ledger, settings, name)
    return run.id, vid


def test_scout_records_run_stage_model_and_consumption(ledger, settings, catalog):
    model = Model()
    items = scout(ledger, settings, model=model)
    event = ledger.events()[0]
    run = ledger.history._all("SELECT * FROM usage_runs")[0]
    assert len(items) == 2 and model.calls == 1
    assert run["kind"] == "scout" and run["status"] == "done" and run["telemetry_complete"] == 1
    assert event["stage"] == "product-analysis" and event["shared"] == 1
    assert event["provider"] == "openrouter" and event["model"] == "test/model"
    assert usage.amount(event) == usage.nano(".3")
    assert ledger.overview({"all_time": "1"})["totals"]["unassigned_usd"] == "0.300000000"
    assert ledger.event_page({"view": "runs"})["rows"][0]["kind"] == "scout"


@pytest.mark.parametrize("cost,known,unknown", [("0", "0.000000000", 0),
                                               ("0.000000001", "0.000000001", 0),
                                               (None, "0.000000000", 1)])
def test_scout_distinguishes_zero_tiny_and_unknown_cost(ledger, settings, catalog, cost, known, unknown):
    items = scout(ledger, settings, count=1, model=Model(cost))
    _, vid = make(ledger, settings, "video", [items[0]["id"]])
    totals = ledger.overview({"all_time": "1"})["totals"]
    detail = ledger.video_details(vid)
    assert totals["known_usd"] == known and totals["unknown_calls"] == unknown
    assert detail["known_usd"] == known and detail["unknown_calls"] == unknown
    assert detail["events"][0]["allocated_usd"] == (None if unknown else known)


def test_only_used_product_share_transfers_to_video(ledger, settings, catalog):
    items = scout(ledger, settings, model=Model())
    _, vid = make(ledger, settings, "first", [items[0]["id"]], voice=".02")
    detail = ledger.video_details(vid)
    assert detail["direct_usd"] == "0.020000000"
    assert detail["shared_usd"] == "0.150000000"
    assert detail["known_usd"] == "0.170000000"
    totals = ledger.overview({"all_time": "1"})["totals"]
    assert totals["known_usd"] == "0.320000000" and totals["unassigned_usd"] == "0.150000000"


def test_selected_products_combine_fractions_of_same_call(ledger, settings, catalog):
    items = scout(ledger, settings, count=3, model=Model())
    _, first = make(ledger, settings, "first", [p["id"] for p in items[:2]])
    assert ledger.video_details(first)["shared_usd"] == "0.200000000"
    assert ledger.overview({"all_time": "1"})["totals"]["unassigned_usd"] == "0.100000000"
    _, second = make(ledger, settings, "second", [items[-1]["id"]])
    assert ledger.video_details(second)["shared_usd"] == "0.100000000"
    assert ledger.overview({"all_time": "1"})["totals"]["unassigned_usd"] == "0.000000000"
    assert len(ledger.events()) == 1


def test_same_product_is_not_charged_again_on_rerender_or_repeated_finalization(ledger, settings, catalog):
    items = scout(ledger, settings, count=1, model=Model())
    run_id, first = make(ledger, settings, "first", [items[0]["id"]])
    ledger.finalize_allocations(run_id)
    ledger.finalize_allocations(run_id)
    _, second = make(ledger, settings, "rerender", [items[0]["id"]], voice=".02")
    assert ledger.video_details(first)["shared_usd"] == "0.300000000"
    assert ledger.video_details(second)["known_usd"] == "0.020000000"
    assert ledger.video_details(second)["shared_usd"] == "0.000000000"
    assert ledger.overview({"all_time": "1"})["totals"]["known_usd"] == "0.320000000"


def test_repeated_scout_keeps_distinct_original_charges(ledger, settings, catalog):
    first = scout(ledger, settings, count=1, model=Model(".2"))
    second = scout(ledger, settings, count=1, model=Model(".4"))
    assert first[0]["id"] == second[0]["id"]
    _, vid = make(ledger, settings, "video", [first[0]["id"]])
    assert ledger.video_details(vid)["shared_usd"] == "0.600000000"
    assert len(ledger.events()) == 2
    assert ledger.overview({"all_time": "1"})["totals"]["known_usd"] == "0.600000000"


def test_scout_counts_once_in_global_and_model_budgets(ledger, settings, catalog):
    ledger.save_settings({"monthly_budget_usd": ".2", "model_budgets": [
        {"provider": "openrouter", "model": "test/model", "budget_usd": ".25"}]})
    items = scout(ledger, settings, model=Model())
    make(ledger, settings, "video", [p["id"] for p in items])
    budget = ledger.budgets()
    assert len(budget["rows"]) == 2
    assert all(row["spent_usd"] == "0.300000000" for row in budget["rows"])
    assert {alert["threshold"] for alert in budget["alerts"]} == {80, 100}
    ledger.acknowledge(budget["alerts"])
    assert ledger.budgets()["alerts"] == []
    assert ledger.overview({"all_time": "1"})["totals"]["known_usd"] == "0.300000000"


def test_draft_retains_products_until_first_completed_production(ledger, settings, catalog):
    items = scout(ledger, settings, model=Model())
    with usage.operation(ledger.history, "draft") as draft:
        usage.use_products([items[0]["id"]])
        usage.step("script")
        charge(".05")
    assert ledger.overview({"all_time": "1"})["totals"]["unassigned_usd"] == "0.350000000"
    _, first = make(ledger, settings, "first", source_run_id=draft.id)
    _, second = make(ledger, settings, "second", source_run_id=draft.id)
    assert ledger.video_details(first)["shared_usd"] == "0.200000000"
    assert ledger.video_details(second)["shared_usd"] == "0.000000000"
    assert ledger.overview({"all_time": "1"})["totals"]["unassigned_usd"] == "0.150000000"


def test_failed_production_does_not_consume_product_share(ledger, settings, catalog):
    items = scout(ledger, settings, count=1, model=Model())
    with pytest.raises(RuntimeError, match="Render failed"):
        with usage.operation(ledger.history, "make"):
            usage.use_products([items[0]["id"]])
            raise RuntimeError("Render failed")
    assert ledger.overview({"all_time": "1"})["totals"]["unassigned_usd"] == "0.300000000"
    _, vid = make(ledger, settings, "recovered", [items[0]["id"]])
    assert ledger.video_details(vid)["shared_usd"] == "0.300000000"


def test_translations_split_research_only_across_completed_versions(ledger, settings, catalog):
    items = scout(ledger, settings, count=1, model=Model(".6"))
    with usage.operation(ledger.history, "make"):
        usage.use_products([items[0]["id"]])
        with usage.phase("voice", shared=False):
            charge(".01")
        original = output(ledger, settings, "original")
        with usage.operation(ledger.history, "translation", child=True):
            with usage.phase("voice", shared=False):
                charge(".02")
            translated = output(ledger, settings, "translated")
        with pytest.raises(RuntimeError):
            with usage.operation(ledger.history, "translation", child=True):
                with usage.phase("voice", shared=False):
                    charge(".03")
                raise RuntimeError("Translation failed")
    assert ledger.video_details(original)["known_usd"] == "0.310000000"
    assert ledger.video_details(translated)["known_usd"] == "0.320000000"
    totals = ledger.overview({"all_time": "1"})["totals"]
    assert totals["known_usd"] == "0.660000000" and totals["unassigned_usd"] == "0.030000000"


def test_concurrent_productions_claim_research_once(ledger, settings, catalog):
    items = scout(ledger, settings, count=1, model=Model())
    histories = [History(ledger.history.path) for _ in range(2)]
    barrier = Barrier(2)

    def produce(index):
        local = Costs(histories[index], settings)
        with usage.operation(local.history, "make"):
            usage.use_products([items[0]["id"]])
            with usage.phase("voice", shared=False):
                charge(".01")
            barrier.wait(timeout=5)
            return output(local, settings, f"parallel-{index}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        vids = list(pool.map(produce, range(2)))
    assert sorted(ledger.video_details(vid)["known_usd"] for vid in vids) == ["0.010000000", "0.310000000"]
    assert ledger.overview({"all_time": "1"})["totals"]["known_usd"] == "0.320000000"


def test_research_allocation_survives_restart_and_video_deletion(ledger, settings, catalog):
    items = scout(ledger, settings, model=Model())
    reopened = Costs(History(ledger.history.path), settings)
    _, vid = make(reopened, settings, "video", [items[0]["id"]])
    reopened.history.delete_video(vid)
    reopened.history.delete_product(items[1]["id"])
    detail = Costs(History(ledger.history.path), settings).video_details(vid)
    assert detail["deleted"] and detail["shared_usd"] == "0.150000000"
    totals = reopened.overview({"all_time": "1"})["totals"]
    assert totals["known_usd"] == "0.300000000" and totals["unassigned_usd"] == "0.150000000"


def test_nanodollar_remainders_are_preserved_across_products_and_videos(ledger, settings, catalog):
    items = scout(ledger, settings, count=3, model=Model(".000000001"))
    for n, item in enumerate(items):
        make(ledger, settings, f"video-{n}", [item["id"]])
    amounts = [usage.nano(ledger.video_details(v["id"])["shared_usd"]) for v in ledger.history.recent()]
    assert sum(amounts) == 1
    totals = ledger.overview({"all_time": "1"})["totals"]
    assert totals["known_usd"] == "0.000000001" and totals["unassigned_usd"] == "0.000000000"


def test_reconciliation_updates_attributed_estimate_without_duplicate_charge(ledger, settings, catalog, monkeypatch):
    ledger.save_settings({"prices": [{"provider": "openrouter", "model": "test/model", "billing": "characters", "rate": "10"}]})
    items = scout(ledger, settings, count=1, model=Model(None, request_id="scout-generation"))
    _, vid = make(ledger, settings, "video", [items[0]["id"]])
    assert ledger.video_details(vid)["shared_usd"] == "0.010000000"
    get = Mock(return_value=Response({"data": {"total_cost": ".02"}}))
    monkeypatch.setattr(usage, "http", lambda: SimpleNamespace(get=get))
    config = settings.with_overrides(openrouter_api_key="unit-test-key")
    assert ledger.reconcile(config)["updated"] == 1
    assert ledger.reconcile(config)["updated"] == 0
    assert get.call_count == 1 and len(ledger.events()) == 1
    assert ledger.video_details(vid)["shared_usd"] == "0.020000000"
    assert ledger.overview({"all_time": "1"})["totals"]["known_usd"] == "0.020000000"


def test_charged_model_failure_stays_recorded_when_heuristics_succeed(ledger, settings, catalog):
    items = scout(ledger, settings, model=Model(".03", error=RuntimeError("Invalid reply")))
    assert len(items) == 2 and all(p["viral_score"] is not None for p in items)
    event = ledger.events()[0]
    assert event["status"] == "failed" and event["actual_nusd"] == usage.nano(".03")


def test_source_failure_leaves_failed_run_even_without_calls(ledger, settings, catalog, monkeypatch):
    monkeypatch.setattr(products, "scout_shopify_store", Mock(side_effect=OSError("Source failed")))
    model = Model()
    with pytest.raises(OSError):
        scout(ledger, settings, model=model)
    run = ledger.history._all("SELECT * FROM usage_runs")[0]
    assert run["kind"] == "scout" and run["status"] == "failed"
    assert ledger.events() == [] and model.calls == 0


def test_no_products_creates_run_without_fake_usage(ledger, settings, catalog, monkeypatch):
    monkeypatch.setattr(products, "scout_shopify_store", lambda *a, **kw: [])
    model = Model()
    assert scout(ledger, settings, model=model) == []
    assert len(ledger.history._all("SELECT * FROM usage_runs")) == 1
    assert ledger.events() == [] and model.calls == 0


@pytest.mark.parametrize("failure", ["event", "allocation"])
def test_telemetry_failure_does_not_interrupt_scout(ledger, settings, catalog, monkeypatch, failure):
    if failure == "event":
        original = ledger.history._exec

        def fail_event(sql, args=()):
            if sql.startswith("INSERT INTO usage_events"):
                raise RuntimeError("Usage storage failed")
            return original(sql, args)

        monkeypatch.setattr(ledger.history, "_exec", fail_event)
    else:
        monkeypatch.setattr(usage.Store, "allocate_products", Mock(side_effect=RuntimeError("Allocation failed")))
    assert len(scout(ledger, settings, model=Model())) == 2
    run = ledger.history._all("SELECT * FROM usage_runs")[0]
    assert run["telemetry_complete"] == 0


@pytest.mark.parametrize("entry", ["direct", "draft"])
def test_real_pipeline_entrypoints_keep_research_product_identity(ledger, settings, catalog, monkeypatch, entry):
    from purffle_shorts import pipeline, script

    items = scout(ledger, settings, count=1, model=Model())
    producer = pipeline.Studio(settings.with_overrides(offline=True))
    content = script.normalize({"title": "Product", "scenes": [{"narration": "A documented product feature."}]},
                               "Product", "product", "pt")
    monkeypatch.setattr(pipeline, "write_script", Mock(return_value=content))

    def produce(*args, **kwargs):
        vid = output(ledger, settings, "video")
        return pipeline.Result(True, record_id=vid)

    monkeypatch.setattr(producer, "produce", produce)
    if entry == "draft":
        draft, _, _ = producer.draft(product_ids=[items[0]["id"]])
        result = producer.make(script=draft, usage_run_id=draft._usage_run_id)
    else:
        result = producer.make(product_ids=[items[0]["id"]])
    assert result.ok
    assert ledger.video_details(result.record_id)["shared_usd"] == "0.300000000"
