"""The Studio web app's server: security checks, the JSON API and a real (offline) job."""

import http.client
import json
import logging
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

from purffle_shorts import studio as ST


@pytest.fixture
def server(settings):
    app = ST.StudioServer(settings.with_overrides(upload=False))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ST._handler(app, "127.0.0.1"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield app, httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()
    root = logging.getLogger()
    for h in [h for h in root.handlers if isinstance(h, ST._JobLog)]:
        root.removeHandler(h)


def req(port, method, path, body=None, token=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Studio-Token"] = token
    if host:
        headers["Host"] = host
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, dict(r.getheaders()), data


def test_page_has_token_and_strict_csp(server):
    app, port = server
    status, headers, body = req(port, "GET", "/")
    assert status == 200 and app.token.encode() in body and b"__TOKEN__" not in body
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert "unsafe-inline" not in headers["Content-Security-Policy"]
    assert req(port, "GET", "/static/app.js")[0] == 200
    assert req(port, "GET", "/static/../studio.py")[0] == 404


def test_other_host_names_are_refused(server):
    app, port = server
    assert req(port, "GET", "/api/info", host="evil.example:8765")[0] == 421
    assert req(port, "GET", "/api/info", host=f"localhost:{port}")[0] == 200


def test_writes_need_the_token(server):
    app, port = server
    assert req(port, "POST", "/api/ideas", {"subject": "x"})[0] == 403
    status, _, body = req(port, "POST", "/api/ideas", {"subject": "Why cats purr", "style": "facts"}, app.token)
    assert status == 200
    iid = json.loads(body)["id"]
    ideas = json.loads(req(port, "GET", "/api/ideas")[2])["pending"]
    assert [(i["id"], i["style"]) for i in ideas] == [(iid, "facts")]
    req(port, "POST", f"/api/ideas/{iid}/delete", {}, app.token)
    assert json.loads(req(port, "GET", "/api/ideas")[2])["pending"] == []


def test_options_and_doctor(server):
    app, port = server
    opts = json.loads(req(port, "GET", "/api/options")[2])
    assert {"chat", "dialogue"} <= set(opts["styles"]) and "16:9" in opts["aspects"]
    checks = json.loads(req(port, "GET", "/api/doctor")[2])
    assert any(c["label"] == "Python" for c in checks)


def test_form_values_are_validated(server):
    app, _ = server
    s = app.overrides({"caption_style": "<script>", "aspect": "16:9", "duration": "999", "review": "rewrite",
                       "grade": "cinematic", "visuals": ["pollinations"], "music": False, "tts": "rm -rf"})
    assert s.caption_style == app.settings.caption_style and s.resolution == (1920, 1080)
    assert s.target_seconds == 170 and s.color_grade == "cinematic" and s.visual_sources == ["pollinations"]
    assert s.music_volume == 0.0 and s.tts_engine == app.settings.tts_engine


def test_final_speed_api_validation(server):
    app, port = server
    assert app.overrides({"speed": 1.5}).video_speed == 1.5
    assert json.loads(req(port, "GET", "/api/info")[2])["speed"] == 1
    for bad in (0, "NaN", 2.1, "fast"):
        assert req(port, "POST", "/api/make", {"speed": bad}, app.token)[0] == 400
        assert req(port, "POST", "/api/clip", {"source": "/tmp/video.mp4", "speed": bad}, app.token)[0] == 400


def test_unavailable_accounting_preserves_studio(server, monkeypatch):
    app, port = server

    def broken(*a, **kw):
        raise OSError("temporary telemetry failure")
    monkeypatch.setattr(app.costs, "budgets", broken)
    data = json.loads(req(port, "GET", "/api/info")[2])
    assert "costs" in data and data["costs"]["error"]
    assert req(port, "GET", "/api/costs")[0] == 503
    assert req(port, "POST", "/api/draft", {"offline": True}, app.token)[0] == 200


def test_offline_draft_job_runs_to_completion(server):
    app, port = server
    status, _, body = req(port, "POST", "/api/draft", {"offline": True, "style": "chat"}, app.token)
    jid = json.loads(body)["job"]
    for _ in range(100):
        job = json.loads(req(port, "GET", f"/api/jobs/{jid}")[2])
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    assert job["result"]["script"]["style"] == "chat" and job["pct"] == 100
    assert job["label"] == "Demo video"
    assert job["result"]["usage_run_id"]


def test_costs_api_settings_filters_export_and_auth(server):
    from purffle_shorts import usage
    app, port = server
    assert req(port, "GET", "/static/costs.js")[0] == 200
    assert req(port, "POST", "/api/costs/settings", {"monthly_budget_usd": "1"})[0] == 403
    status, _, body = req(port, "POST", "/api/costs/settings",
                           {"monthly_budget_usd": "1", "brl_per_usd": "5.2"}, app.token)
    assert status == 200 and json.loads(body)["monthly_budget_usd"] == "1.000000000"
    with usage.operation(app.studio.history, "make", "tracked video"):
        with usage.request("openrouter", "model") as call:
            call.capture(data={"usage": {"cost": ".9"}})
    summary = json.loads(req(port, "GET", "/api/costs")[2])
    assert summary["totals"]["known_usd"] == "0.900000000" and summary["budgets"]["alerts"]
    events = json.loads(req(port, "GET", "/api/costs/events?provider=openrouter")[2])
    assert events["total"] == 1
    assert req(port, "GET", "/api/costs?from=garbage")[0] == 400
    assert req(port, "POST", "/api/costs/settings", {"brl_per_usd": "Infinity"}, app.token)[0] == 400
    status, headers, csv = req(port, "GET", "/api/costs/export.csv")
    assert status == 200 and "text/csv" in headers["Content-Type"] and b"0.900000000" in csv
    assert req(port, "POST", "/api/costs/alerts", {"alerts": summary["budgets"]["alerts"]}, app.token)[0] == 200
    assert not json.loads(req(port, "GET", "/api/costs")[2])["budgets"]["alerts"]
    assert req(port, "POST", "/api/costs/sync", {}, app.token)[0] == 202
    old = app.studio.history.add_video(title="legacy", status="rendered")
    assert not json.loads(req(port, "GET", f"/api/videos/{old}/costs")[2])["tracked"]
    assert req(port, "GET", "/api/videos/999999/costs")[0] == 404


def test_make_now_keeps_idea_identity(server, monkeypatch):
    from purffle_shorts.pipeline import Result, Studio
    app, port = server
    idea = app.studio.history.add_idea("Selected idea")
    captured = []

    def make(self, *args, **kwargs):
        captured.append(kwargs)
        return Result(True)
    monkeypatch.setattr(Studio, "make", make)
    _, _, body = req(port, "POST", "/api/make", {"idea_id": idea, "source": "queue"}, app.token)
    jid = json.loads(body)["job"]
    for _ in range(100):
        if app.jobs[jid].finished:
            break
        time.sleep(.01)
    assert captured[0]["idea_id"] == idea
    assert app.studio.history.ideas()[0]["id"] == idea
