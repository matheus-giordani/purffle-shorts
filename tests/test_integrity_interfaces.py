"""Boundary contracts for scheduling, affiliate links, ideas, HTTP, CLI and MCP."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from purffle_shorts import cli, pipeline, script, studio, topics, youtube
from purffle_shorts.history import History
from purffle_shorts.mcp_server import _describe

from .test_products import call_handler


@pytest.fixture
def app(settings, monkeypatch):
    # Exercise the actual handler with an in-memory socket, without starting a worker or TCP server.
    value = object.__new__(studio.StudioServer)
    value.settings = settings.with_overrides(offline=True, keep_videos=True)
    value.studio = pipeline.Studio(value.settings)
    value.token = "unit-test-token"
    value.submit = Mock(return_value=SimpleNamespace(id=17))
    monkeypatch.setattr(youtube, "upload", Mock(side_effect=AssertionError("Unexpected network upload")))
    return value


def make_unknown(app):
    folder = app.settings.out_path / "video"
    folder.mkdir()
    path = folder / "short.mp4"
    path.write_bytes(b"fake")
    h = app.studio.history
    vid = h.add_video(title="Video", status="rendered", folder=str(folder), video_path=str(path))
    reservation = h.reserve_upload(vid, app.settings, pipeline.quota_day_start())
    h.finish_upload(vid, reservation["token"], "unknown", status="upload-unknown", error="Lost response")
    return vid


def raw_script(links=()):
    return {"title": "Product", "style": "product", "language": "pt", "topic": "Product",
            "scenes": [{"narration": "This product has a documented feature.", "search_query": "product"}],
            "product_links": list(links)}


@pytest.mark.parametrize("bad", ["25:00", "09:60", "-1:00", "nine", "", None, 900, "09:30:00"])
def test_invalid_publish_times_raise_instead_of_disabling_schedule(settings, bad):
    config = settings.with_overrides(publish_times=["18:00", bad], timezone="UTC")
    with pytest.raises(ValueError, match="PUBLISH_TIMES"):
        youtube.next_publish_slot(config, [], datetime(2026, 10, 19, 12, tzinfo=timezone.utc))


def test_exhausted_schedule_has_distinct_error(settings):
    now = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    taken = [youtube.to_rfc3339((now + timedelta(days=n)).replace(hour=18)) for n in range(60)]
    with pytest.raises(youtube.NoPublishSlot):
        youtube.next_publish_slot(settings.with_overrides(publish_times=["18:00"], timezone="UTC"), taken, now)


@pytest.mark.parametrize("seconds,day", [(0, 19), (1, 20)])
def test_publish_slot_observes_fifteen_minute_boundary(settings, seconds, day):
    now = datetime(2026, 10, 19, 17, 45, seconds, tzinfo=timezone.utc)
    slot = youtube.next_publish_slot(settings.with_overrides(publish_times=["18:00"], timezone="UTC"), [], now)
    assert slot.day == day and slot.hour == 18


@pytest.mark.parametrize("text", ["x" * 5000, "á" * 2500, "😀" * 1250])
def test_description_exactly_at_utf8_limit_is_preserved(settings, text):
    assert len(text.encode("utf-8")) == 5000
    body = youtube.build_body(settings, "Title", text, ["tag"], "27", "pt")
    assert body["snippet"]["description"] == text


@pytest.mark.parametrize("text", ["x" * 5001, "á" * 2501, "😀" * 1251])
def test_description_over_utf8_limit_is_rejected(settings, text):
    with pytest.raises(ValueError, match="5000"):
        youtube.build_body(settings, "Title", text, [], "27", "pt")


def test_description_preserves_affiliate_url_at_last_bytes(settings):
    link = "https://example.invalid/?signature=" + "a" * 400
    text = "x" * (5000 - len(link)) + link
    body = youtube.build_body(settings, "Title", text, [], "27", "pt")
    assert body["snippet"]["description"].endswith(link)


@pytest.mark.parametrize("as_string", [False, True])
def test_normalization_retains_complete_affiliate_links(as_string):
    links = ["Produto: https://example.invalid/?signature=" + "a" * 800,
             "https://example.invalid/?encoded=%C3%A1&ref=" + "b" * 450]
    data = raw_script(links)
    if as_string:
        data["product_links"] = "\n".join(links)
    normalized = script.normalize(data, "Product", "product", "pt")
    assert normalized.product_links == links
    assert all(link in pipeline.final_description(normalized) for link in links)


@pytest.mark.parametrize("token", [None, "wrong"])
def test_resolution_endpoint_rejects_missing_or_invalid_auth(app, token):
    vid = make_unknown(app)
    status, _ = call_handler(app, "POST", f"/api/videos/{vid}/resolve-upload", {"not_uploaded": True}, token)
    assert status == 403
    assert app.studio.history.upload_attempt(vid)["state"] == "unknown"
    app.submit.assert_not_called()


@pytest.mark.parametrize("body,expected", [({"youtube_id": "remote-id"}, "uploaded"),
                                          ({"not_uploaded": True}, "rendered")])
def test_resolution_endpoint_changes_only_local_state(app, body, expected):
    vid = make_unknown(app)
    status, response = call_handler(app, "POST", f"/api/videos/{vid}/resolve-upload", body, app.token)
    assert status == 200 and json.loads(response)["status"] == expected
    assert app.studio.history.get(vid)["status"] == expected
    app.submit.assert_not_called()
    youtube.upload.assert_not_called()


@pytest.mark.parametrize("body", [{}, {"not_uploaded": "true"}, {"not_uploaded": "false"}, {"not_uploaded": 1},
                                  {"not_uploaded": True, "youtube_id": "remote-id"},
                                  {"youtube_id": "https://youtu.be/remote-id"}])
def test_resolution_endpoint_rejects_ambiguous_or_coerced_input(app, body):
    vid = make_unknown(app)
    status, response = call_handler(app, "POST", f"/api/videos/{vid}/resolve-upload", body, app.token)
    assert status == 400 and json.loads(response)["error"]
    assert app.studio.history.upload_attempt(vid)["state"] == "unknown"


def test_video_detail_exposes_state_without_reservation_credentials(app):
    vid = make_unknown(app)
    status, body = call_handler(app, "GET", f"/api/videos/{vid}")
    detail = json.loads(body)
    assert status == 200 and detail["upload_state"] == "unknown"
    assert detail["status"] == "upload-unknown"
    assert "token" not in detail and "owner_pid" not in detail


@pytest.mark.parametrize("link", ["", "https://example.invalid/?signature=" + "a" * 900])
def test_affiliate_endpoint_preserves_full_value(app, link):
    pid = app.studio.history.upsert_product(title="Product", external_url="https://example.invalid/p")
    status, body = call_handler(app, "POST", f"/api/products/{pid}/affiliate", {"affiliate_url": link}, app.token)
    assert status == 200 and json.loads(body)["affiliate_url"] == link
    assert app.studio.history.get_products([pid])[0]["affiliate_url"] == link


def test_affiliate_endpoint_reports_missing_product(app):
    status, body = call_handler(app, "POST", "/api/products/999/affiliate", {"affiliate_url": "https://example.invalid"}, app.token)
    assert status == 404 and json.loads(body)["error"]
    assert not app.studio.history.set_product_affiliate(999, "https://example.invalid")


@pytest.mark.parametrize("kind", ["make", "draft"])
def test_worker_preserves_links_across_request_and_script_normalization(app, kind, monkeypatch):
    link = "Produto: https://example.invalid/?signature=" + "a" * 900
    data = raw_script([link])
    job = studio.Job(1, kind, {})
    if kind == "make":
        method = Mock(return_value=pipeline.Result(True))
        monkeypatch.setattr(app.studio, "make", method)
        params = {"script": data, "product_links": [link]}
    else:
        draft = script.normalize(data, "Product", "product", "pt")
        draft._usage_run_id = "draft-run"
        method = Mock(return_value=(draft, topics.Topic("Product", "products"), "fake-model"))
        monkeypatch.setattr(app.studio, "draft", method)
        params = {"product_links": link}
    assert app._run(job, app.studio, app.settings, params)
    assert method.call_args.kwargs["product_links"] == [link]
    if kind == "make":
        assert method.call_args.kwargs["script"].product_links == [link]
    else:
        assert job.result["script"]["product_links"] == [link]


@pytest.mark.parametrize("error", [RuntimeError("Source failed"), KeyboardInterrupt(), SystemExit(2)])
def test_source_failure_releases_claimed_idea(settings, monkeypatch, error):
    producer = pipeline.Studio(settings.with_overrides(offline=True))
    iid = producer.history.add_idea("https://example.invalid/article", style="facts")
    monkeypatch.setattr(topics, "from_url", Mock(side_effect=error))
    with pytest.raises(type(error)):
        producer.draft(idea_id=iid)
    idea = producer.history.ideas("pending")[0]
    assert idea["id"] == iid and idea["used_at"] is None and idea["video_id"] is None


def test_deleted_product_source_releases_idea(settings):
    producer = pipeline.Studio(settings.with_overrides(offline=True))
    iid = producer.history.add_idea("Missing product", notes="products:999")
    with pytest.raises(ValueError, match="no longer available"):
        producer.draft(idea_id=iid)
    assert producer.history.ideas("pending")[0]["id"] == iid


def test_product_topic_failure_releases_idea(settings, monkeypatch):
    from purffle_shorts import products
    producer = pipeline.Studio(settings.with_overrides(offline=True))
    pid = producer.history.upsert_product(title="Product", external_url="https://example.invalid/p")
    iid = producer.history.add_idea("Product idea", notes=f"products:{pid}")
    monkeypatch.setattr(products, "build_product_topic", Mock(side_effect=ValueError("Invalid dossier")))
    with pytest.raises(ValueError, match="Invalid dossier"):
        producer.draft(idea_id=iid)
    assert producer.history.ideas("pending")[0]["id"] == iid


def test_writer_failure_releases_idea_after_source_loaded(settings, monkeypatch):
    producer = pipeline.Studio(settings.with_overrides(offline=True))
    iid = producer.history.add_idea("A documented topic")
    monkeypatch.setattr(pipeline, "write_script", Mock(side_effect=RuntimeError("Writer failed")))
    result = producer.make(idea_id=iid)
    assert not result.ok and "Writer failed" in result.error
    assert producer.history.ideas("pending")[0]["id"] == iid


def test_release_never_reopens_an_idea_linked_to_video(settings):
    history = History(settings.data_path / "history.db")
    iid = history.add_idea("Already produced")
    history.claim_idea(iid)
    vid = history.add_video(title="Video", status="rendered")
    history.link_idea(iid, vid)
    history.release_idea(iid)
    assert history.ideas("pending") == []
    assert history.ideas("used")[0]["video_id"] == vid


@pytest.mark.parametrize("date,expected", [("2026-03-08", "2026-03-08T08:00:00+00:00"),
                                           ("2026-11-01", "2026-11-01T07:00:00+00:00")])
def test_quota_day_starts_at_actual_pacific_midnight(monkeypatch, date, expected):
    moment = datetime.fromisoformat(date + "T12:00:00").replace(tzinfo=ZoneInfo("America/Los_Angeles"))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz)

    monkeypatch.setattr(pipeline, "datetime", Clock)
    assert pipeline.quota_day_start() == expected


@pytest.mark.parametrize("flag,kwargs", [("--link-youtube-id", {"youtube_id": "remote-id", "not_uploaded": False}),
                                        ("--confirm-not-uploaded", {"youtube_id": "", "not_uploaded": True})])
def test_cli_resolution_does_not_start_upload(settings, monkeypatch, capsys, flag, kwargs):
    producer = SimpleNamespace(history=SimpleNamespace(resolve_upload=Mock(return_value="rendered")),
                               upload_record=Mock(), flush_queue=Mock())
    monkeypatch.setattr(pipeline, "Studio", Mock(return_value=producer))
    command = ["upload", "--id", "12", flag] + (["remote-id"] if flag == "--link-youtube-id" else [])
    args = cli.build_parser().parse_args(command)
    assert cli.cmd_upload(args, settings) == 0
    producer.history.resolve_upload.assert_called_once_with(12, **kwargs)
    producer.upload_record.assert_not_called()
    producer.flush_queue.assert_not_called()
    assert "No upload was started" in capsys.readouterr().out


@pytest.mark.parametrize("extra", [[], ["--pending"], ["--pending", "--id", "12"]])
def test_cli_resolution_requires_exactly_one_video(settings, monkeypatch, extra):
    producer = SimpleNamespace(history=SimpleNamespace(resolve_upload=Mock()))
    monkeypatch.setattr(pipeline, "Studio", Mock(return_value=producer))
    args = cli.build_parser().parse_args(["upload", "--confirm-not-uploaded", *extra])
    assert cli.cmd_upload(args, settings) == 2
    producer.history.resolve_upload.assert_not_called()


def test_cli_resolution_flags_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["upload", "--id", "12", "--link-youtube-id", "remote-id", "--confirm-not-uploaded"])


def test_cli_and_mcp_show_publication_problem_for_successful_render(capsys):
    result = pipeline.Result(True, title="Video", status="upload-unknown", error="Check YouTube before retrying")
    cli.print_result(result)
    for text in (capsys.readouterr().out, _describe(result)):
        assert "upload-unknown" in text and "Check YouTube before retrying" in text
