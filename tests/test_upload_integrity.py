"""Upload reservations and failure recovery without OAuth, network or rendering."""

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from purffle_shorts import history as H
from purffle_shorts import pipeline as P
from purffle_shorts import youtube as Y

STAMP = "2026-10-19T15:00:00+00:00"
DAY = "2026-10-19T07:00:00+00:00"


@pytest.fixture
def studio(settings, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime.fromisoformat(STAMP)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(H, "now_iso", lambda: STAMP)
    monkeypatch.setattr(P, "quota_day_start", lambda: DAY)
    monkeypatch.setattr(Y, "datetime", Clock)
    monkeypatch.setattr(Y, "upload", Mock(side_effect=AssertionError("Unexpected upload")))
    monkeypatch.setattr(P.notify, "send", Mock())
    return P.Studio(settings.with_overrides(offline=True, keep_videos=True, timezone="UTC"))


def add_video(studio, name="Video", **fields):
    folder = studio.s.out_path / name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "short.mp4"
    path.write_bytes(b"unit-test video")
    vid = studio.history.add_video(title=name, folder=str(folder), video_path=str(path), status="rendered",
                                   tags=["shorts"], description="Description", **fields)
    return vid, path


def reserve(studio, vid):
    return studio.history.reserve_upload(vid, studio.s, DAY)


def uncertain(studio, vid):
    item = reserve(studio, vid)
    studio.history.start_upload(vid, item["token"])
    studio.history.finish_upload(vid, item["token"], "unknown", status="upload-unknown", error="Connection lost")
    return item


def test_reservation_persists_and_counts_toward_quota(studio):
    vid, _ = add_video(studio)
    item = reserve(studio, vid)
    reopened = H.History(studio.history.path)
    assert item["status"] == "reserved" and item["publish"] is None
    assert reopened.upload_attempt(vid)["token"] == item["token"]
    assert reopened.upload_attempt(vid)["state"] == "reserved"
    assert studio.quota_left() == studio.s.daily_upload_limit - 1


def test_same_video_is_reserved_once_across_history_instances(studio):
    vid, _ = add_video(studio)
    histories = [H.History(studio.history.path) for _ in range(8)]
    barrier = threading.Barrier(len(histories))

    def claim(history):
        barrier.wait(timeout=5)
        return history.reserve_upload(vid, studio.s, DAY)["status"]

    with ThreadPoolExecutor(max_workers=len(histories)) as pool:
        statuses = list(pool.map(claim, histories))
    assert statuses.count("reserved") == 1
    assert statuses.count("uploading") == 7
    assert studio.history.uploads_since(DAY) == 1


def test_parallel_videos_cannot_exceed_daily_quota(studio):
    settings = studio.s.with_overrides(daily_upload_limit=1)
    vids = [add_video(studio, str(n))[0] for n in range(2)]
    histories = [H.History(studio.history.path) for _ in vids]
    barrier = threading.Barrier(2)

    def claim(index):
        barrier.wait(timeout=5)
        return histories[index].reserve_upload(vids[index], settings, DAY)["status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(claim, range(2)))
    assert sorted(statuses) == ["queued", "reserved"]
    assert studio.history.uploads_since(DAY) == 1


def test_concurrent_upload_calls_perform_one_remote_insert(studio):
    vid, _ = add_video(studio)
    other = P.Studio(studio.s)
    entered, release = threading.Event(), threading.Event()

    def upload(*args):
        entered.set()
        assert release.wait(timeout=5)
        return {"id": "remote-id"}

    Y.upload.side_effect = upload
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(studio.upload_record, vid)
        try:
            assert entered.wait(timeout=5)
            assert other.upload_record(vid) == "uploading"
        finally:
            release.set()
        assert first.result(timeout=5) == "uploaded"
    Y.upload.assert_called_once()


def test_parallel_reservations_use_distinct_publication_slots(studio):
    settings = studio.s.with_overrides(publish_times=["18:00"])
    vids = [add_video(studio, str(n))[0] for n in range(2)]
    histories = [H.History(studio.history.path) for _ in vids]
    with ThreadPoolExecutor(max_workers=2) as pool:
        items = list(pool.map(lambda n: histories[n].reserve_upload(vids[n], settings, DAY), range(2)))
    assert all(item["status"] == "reserved" for item in items)
    assert len({item["publish"] for item in items}) == 2
    assert studio.history.uploads_since(DAY) == 2


@pytest.mark.parametrize("publish_at,expected", [(None, "uploaded"), ("2026-10-20T18:00:00Z", "scheduled")])
def test_already_published_video_does_not_need_local_file(studio, publish_at, expected):
    vid, path = add_video(studio, youtube_id="remote-id", publish_at=publish_at)
    studio.history.update_video(vid, status="failed")
    path.unlink()
    result = P.Result(True)
    assert studio.upload_record(vid, result) == expected
    assert result.youtube_id == "remote-id" and result.publish_at == publish_at
    Y.upload.assert_not_called()


@pytest.mark.parametrize("missing_record", [False, True])
def test_missing_video_never_reserves_or_uploads(studio, missing_record):
    vid, path = add_video(studio)
    if missing_record:
        studio.history.delete_video(vid)
    else:
        path.unlink()
    result = P.Result(True)
    assert studio.upload_record(vid, result) == "missing"
    assert result.error
    assert studio.history.upload_attempt(vid) is None
    Y.upload.assert_not_called()


def test_wrong_tokens_cannot_start_or_finish_an_upload(studio):
    vid, _ = add_video(studio)
    reserve(studio, vid)
    with pytest.raises(ValueError, match="reservation"):
        studio.history.start_upload(vid, "wrong")
    with pytest.raises(ValueError, match="reservation"):
        studio.history.finish_upload(vid, "wrong", "done", status="uploaded", youtube_id="wrong-id")
    assert studio.history.upload_attempt(vid)["state"] == "reserved"
    assert studio.history.get(vid)["youtube_id"] is None


def test_a_started_upload_cannot_be_started_again(studio):
    vid, _ = add_video(studio)
    item = reserve(studio, vid)
    studio.history.start_upload(vid, item["token"])
    with pytest.raises(ValueError, match="reservation"):
        studio.history.start_upload(vid, item["token"])
    assert studio.history.upload_attempt(vid)["state"] == "uploading"


def test_stale_token_cannot_overwrite_a_later_upload_attempt(studio):
    vid, _ = add_video(studio)
    first = reserve(studio, vid)
    studio.history.finish_upload(vid, first["token"], "failed")
    second = reserve(studio, vid)
    assert first["token"] != second["token"]
    with pytest.raises(ValueError, match="reservation"):
        studio.history.finish_upload(vid, first["token"], "done", status="uploaded", youtube_id="stale-id")
    assert studio.history.upload_attempt(vid)["token"] == second["token"]
    assert studio.history.get(vid)["youtube_id"] is None


def test_unknown_attempt_blocks_upload_after_restart(studio):
    vid, path = add_video(studio)
    uncertain(studio, vid)
    restarted = P.Studio(studio.s)
    assert restarted.upload_record(vid) == "upload-unknown"
    assert path.exists() and restarted.history.get(vid)["youtube_id"] is None
    assert restarted.history.uploads_since(DAY) == 1
    Y.upload.assert_not_called()


def test_finish_upload_rolls_back_attempt_when_video_update_fails(studio):
    vid, _ = add_video(studio)
    item = reserve(studio, vid)
    with pytest.raises(sqlite3.OperationalError):
        studio.history.finish_upload(vid, item["token"], "done", nonexistent_column="bad")
    assert studio.history.upload_attempt(vid)["state"] == "reserved"
    assert studio.history.get(vid)["status"] == "rendered"


@pytest.mark.parametrize("started,attempt_state,video_state", [
    (False, "failed", "queued"), (True, "unknown", "upload-unknown"),
])
def test_dead_owner_is_recovered_without_blind_retry(studio, monkeypatch, started, attempt_state, video_state):
    vid, _ = add_video(studio)
    item = reserve(studio, vid)
    if started:
        studio.history.start_upload(vid, item["token"])
    monkeypatch.setattr(H.os, "kill", Mock(side_effect=ProcessLookupError))
    reopened = H.History(studio.history.path)
    assert reopened.upload_attempt(vid)["state"] == attempt_state
    assert reopened.get(vid)["status"] == video_state
    if started:
        assert studio.upload_record(vid) == "upload-unknown"
        Y.upload.assert_not_called()
    else:
        assert reserve(studio, vid)["token"] != item["token"]


def test_owner_with_denied_process_access_remains_active(studio, monkeypatch):
    vid, _ = add_video(studio)
    reserve(studio, vid)
    monkeypatch.setattr(H.os, "kill", Mock(side_effect=PermissionError))
    assert reserve(studio, vid)["status"] == "uploading"
    assert studio.history.upload_attempt(vid)["state"] == "reserved"


def test_recovery_handles_an_attempt_without_owner_pid(studio):
    vid, _ = add_video(studio)
    item = reserve(studio, vid)
    studio.history.start_upload(vid, item["token"])
    studio.history._exec("UPDATE upload_attempts SET owner_pid=NULL WHERE video_id=?", (vid,))
    assert studio.history.upload_attempt(vid)["state"] == "unknown"


@pytest.mark.parametrize("scheduled", [False, True])
def test_resolve_existing_upload_links_without_calling_youtube(studio, scheduled):
    if scheduled:
        studio.s = studio.s.with_overrides(publish_times=["18:00"])
    vid, path = add_video(studio)
    item = uncertain(studio, vid)
    expected = "scheduled" if scheduled else "uploaded"
    assert studio.history.resolve_upload(vid, youtube_id="existing-id") == expected
    rec = studio.history.get(vid)
    assert rec["youtube_id"] == "existing-id" and rec["uploaded_at"] == STAMP
    assert rec["publish_at"] == (Y.to_rfc3339(item["publish"]) if scheduled else None)
    assert rec["error"] is None and path.exists()
    assert studio.upload_record(vid) == expected
    Y.upload.assert_not_called()


def test_confirming_no_upload_only_releases_reservation(studio):
    vid, path = add_video(studio)
    uncertain(studio, vid)
    assert studio.history.resolve_upload(vid, not_uploaded=True) == "rendered"
    assert studio.history.upload_attempt(vid)["state"] == "failed"
    assert studio.history.get(vid)["error"] is None and path.exists()
    Y.upload.assert_not_called()
    Y.upload.side_effect = None
    Y.upload.return_value = {"id": "new-remote-id"}
    assert studio.upload_record(vid) == "uploaded"
    Y.upload.assert_called_once()


@pytest.mark.parametrize("kwargs", [{}, {"youtube_id": "existing-id", "not_uploaded": True},
                                    {"youtube_id": "https://youtu.be/existing-id"}, {"youtube_id": "bad id"}])
def test_invalid_resolution_keeps_unknown_state(studio, kwargs):
    vid, _ = add_video(studio)
    uncertain(studio, vid)
    with pytest.raises(ValueError):
        studio.history.resolve_upload(vid, **kwargs)
    assert studio.history.upload_attempt(vid)["state"] == "unknown"


@pytest.mark.parametrize("state", ["missing", "reserved", "uploading", "done", "failed"])
def test_only_unknown_attempts_can_be_resolved(studio, state):
    vid, _ = add_video(studio)
    if state != "missing":
        item = reserve(studio, vid)
        studio.history.finish_upload(vid, item["token"], state)
    with pytest.raises(ValueError, match="unknown"):
        studio.history.resolve_upload(vid, not_uploaded=True)


def test_resolution_cannot_link_a_video_owned_by_another_record(studio):
    vid, _ = add_video(studio)
    add_video(studio, "Other", youtube_id="existing-id")
    uncertain(studio, vid)
    with pytest.raises(ValueError, match="another record"):
        studio.history.resolve_upload(vid, youtube_id="existing-id")
    assert studio.history.get(vid)["youtube_id"] is None
    assert studio.history.upload_attempt(vid)["state"] == "unknown"


def test_missing_video_cannot_be_resolved(studio):
    with pytest.raises(ValueError, match="unknown"):
        studio.history.resolve_upload(999, not_uploaded=True)


@pytest.mark.parametrize("keep", [False, True])
def test_upload_is_committed_before_cleanup_and_idempotent_after_restart(studio, keep):
    studio.s = studio.s.with_overrides(keep_videos=keep)
    vid, path = add_video(studio)
    Y.upload.side_effect = None
    Y.upload.return_value = {"id": "remote-id"}
    first, second = P.Result(True), P.Result(True)
    assert studio.upload_record(vid, first) == "uploaded"
    assert path.exists() is keep
    assert P.Studio(studio.s).upload_record(vid, second) == "uploaded"
    assert first.youtube_id == second.youtube_id == "remote-id"
    assert studio.history.upload_attempt(vid)["state"] == "done"
    assert studio.history.uploads_since(DAY) == 1
    Y.upload.assert_called_once()


def test_local_cleanup_failure_does_not_lose_remote_id(studio, monkeypatch):
    studio.s = studio.s.with_overrides(keep_videos=False)
    vid, path = add_video(studio)
    Y.upload.side_effect = None
    Y.upload.return_value = {"id": "remote-id"}
    unlink = Path.unlink

    def fail_video_only(p, *args, **kwargs):
        if p == path:
            raise OSError("File is busy")
        return unlink(p, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_video_only)
    assert studio.upload_record(vid) == "uploaded"
    assert path.exists() and studio.history.get(vid)["youtube_id"] == "remote-id"
    assert studio.upload_record(vid) == "uploaded"
    Y.upload.assert_called_once()


@pytest.mark.parametrize("response", [{}, {"id": ""}, {"id": None}, {"id": 7}, None])
def test_missing_remote_id_requires_manual_reconciliation(studio, response):
    vid, path = add_video(studio)
    Y.upload.side_effect = None
    Y.upload.return_value = response
    result = P.Result(True)
    assert studio.upload_record(vid, result) == "upload-unknown"
    assert result.error and path.exists()
    assert studio.upload_record(vid) == "upload-unknown"
    Y.upload.assert_called_once()


@pytest.mark.parametrize("error", [TimeoutError("Lost reply"), RuntimeError("Server error"),
                                  KeyboardInterrupt(), SystemExit(2)])
def test_uncertain_failure_keeps_file_and_prevents_another_insert(studio, error):
    vid, path = add_video(studio)
    Y.upload.side_effect = error
    if isinstance(error, Exception):
        assert studio.upload_record(vid) == "upload-unknown"
    else:
        with pytest.raises(type(error)):
            studio.upload_record(vid)
    assert path.exists() and studio.history.upload_attempt(vid)["state"] == "unknown"
    assert studio.upload_record(vid) == "upload-unknown"
    Y.upload.assert_called_once()


@pytest.mark.parametrize("metadata", ["not JSON", "[]"])
def test_preflight_failure_is_retryable_without_remote_call(studio, metadata):
    vid, path = add_video(studio)
    meta = path.parent / "metadata.json"
    meta.write_text(metadata)
    assert studio.upload_record(vid) == "failed"
    assert studio.history.upload_attempt(vid)["state"] == "failed"
    assert studio.history.uploads_since(DAY) == 0
    Y.upload.assert_not_called()
    meta.write_text(json.dumps({"category_id": "27"}))
    Y.upload.side_effect = None
    Y.upload.return_value = {"id": "remote-id"}
    assert studio.upload_record(vid) == "uploaded"


def test_overlong_description_is_rejected_before_remote_attempt(studio):
    vid, path = add_video(studio)
    studio.history.update_video(vid, description="á" * 2501)
    assert studio.upload_record(vid) == "failed"
    assert path.exists() and studio.history.upload_attempt(vid)["state"] == "failed"
    Y.upload.assert_not_called()


def test_quota_refusal_releases_attempt_but_stops_uploads_for_today(studio):
    first, _ = add_video(studio, "First")
    second, path = add_video(studio, "Second")
    Y.upload.side_effect = Y.QuotaExceeded("uploadLimitExceeded")
    assert studio.upload_record(first) == studio.upload_record(second) == "queued"
    assert studio.history.upload_attempt(first)["state"] == "failed"
    assert studio.history.upload_attempt(second) is None
    assert studio.quota_left() == 0 and path.exists()
    Y.upload.assert_called_once()


def test_missing_authorization_preserves_render_and_releases_attempt(studio):
    vid, path = add_video(studio)
    Y.upload.side_effect = Y.NotAuthorized("Run auth")
    with pytest.raises(Y.NotAuthorized):
        studio.upload_record(vid)
    assert studio.history.get(vid)["status"] == "rendered" and path.exists()
    assert studio.history.upload_attempt(vid)["state"] == "failed"
    assert studio.history.uploads_since(DAY) == 0


def test_bad_schedule_never_turns_into_immediate_upload(studio):
    studio.s = studio.s.with_overrides(publish_times=["25:99"])
    vid, path = add_video(studio)
    result = P.Result(True)
    assert studio.upload_record(vid, result) == "upload-failed"
    assert "PUBLISH_TIMES" in result.error and path.exists()
    assert studio.history.upload_attempt(vid) is None
    Y.upload.assert_not_called()


def test_invalid_timezone_prevents_upload_without_consuming_quota(studio):
    studio.s = studio.s.with_overrides(publish_times=["18:00"], timezone="Invalid/Timezone")
    vid, path = add_video(studio)
    result = P.Result(True)
    assert studio.upload_record(vid, result) == "upload-failed"
    assert result.error and path.exists()
    assert studio.history.upload_attempt(vid) is None
    assert studio.history.uploads_since(DAY) == 0
    Y.upload.assert_not_called()


def test_no_schedule_vacancy_keeps_video_queued(studio, monkeypatch):
    vid, path = add_video(studio)
    monkeypatch.setattr(Y, "next_publish_slot", Mock(side_effect=Y.NoPublishSlot("No vacancy")))
    result = P.Result(True)
    assert studio.upload_record(vid, result) == "queued"
    assert result.error == "No vacancy" and path.exists()
    assert studio.history.get(vid)["status"] == "queued"
    assert studio.history.upload_attempt(vid) is None
    Y.upload.assert_not_called()


@pytest.mark.parametrize("date,offset", [("2026-03-08", -7), ("2026-11-01", -8), ("2026-10-19", -7)])
def test_quota_reset_uses_next_civil_midnight(studio, monkeypatch, date, offset):
    moment = datetime.fromisoformat(date + "T12:00:00").replace(tzinfo=ZoneInfo("America/Los_Angeles"))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz)

    monkeypatch.setattr(P, "datetime", Clock)
    assert moment.utcoffset().total_seconds() / 3600 == offset
    assert P.seconds_until_quota_reset() == 12 * 3600 + 120


@pytest.mark.parametrize("date,hours", [("2026-03-08", 23), ("2026-11-01", 25), ("2026-10-19", 24)])
def test_quota_reset_handles_short_and_long_days_at_midnight(monkeypatch, date, hours):
    moment = datetime.fromisoformat(date + "T00:00:00").replace(tzinfo=ZoneInfo("America/Los_Angeles"))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz)

    monkeypatch.setattr(P, "datetime", Clock)
    assert P.seconds_until_quota_reset() == hours * 3600 + 120
