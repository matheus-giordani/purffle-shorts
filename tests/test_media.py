from purffle_shorts import media as M
from purffle_shorts.config import Settings


class R:
    def __init__(self, data):
        self.status_code, self._d, self.text = 200, data, ""

    def json(self):
        return self._d


class S:
    def __init__(self, data):
        self.data, self.params = data, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.params.append(params)
        return R(self.data)


def test_pexels_file_choice_prefers_1080_not_4k():
    files = [
        {"link": "u4k", "width": 2160, "height": 3840, "file_type": "video/mp4"},
        {"link": "u1080", "width": 1080, "height": 1920, "file_type": "video/mp4"},
        {"link": "u720", "width": 720, "height": 1280, "file_type": "video/mp4"},
        {"link": "", "width": 1080, "height": 1920},
        {"link": "hls", "width": None, "height": None},
    ]
    assert M._pexels_pick_file(files, prefer_4k=False)["link"] == "u1080"
    assert M._pexels_pick_file(files, prefer_4k=True)["link"] == "u4k"
    assert M._pexels_pick_file(files[2:3], False)["link"] == "u720"


def test_pexels_videos_parse(monkeypatch):
    data = {"videos": [{"id": 7, "duration": 12, "user": {"name": "Ann"},
                        "url": "https://www.pexels.com/video/person-writing-in-a-notebook-123/",
                        "video_files": [{"link": "a", "width": 1080, "height": 1920, "file_type": "video/mp4"}]}]}
    sess = S(data)
    monkeypatch.setattr(M, "http", lambda: sess)
    items = M.pexels_videos("octopus", "key")
    assert items[0].key == "pexels:7" and items[0].portrait and items[0].duration == 12
    assert items[0].extra == {"tags": "person writing in a notebook", "rank": 0}
    assert sess.params[0]["orientation"] == "portrait"


def test_pixabay_prefers_medium(monkeypatch):
    data = {"hits": [{"id": 3, "duration": 9, "user": "bob", "tags": "coffee cup", "videos": {
        "large": {"url": "L", "width": 3840, "height": 2160},
        "medium": {"url": "Md", "width": 1920, "height": 1080},
        "small": {"url": "", "width": 0, "height": 0}}}]}
    monkeypatch.setattr(M, "http", lambda: S(data))
    assert M.pixabay_videos("x", "k")[0].url == "Md"
    assert M.pixabay_videos("x", "k", prefer_4k=True)[0].url == "L"
    item = M.pixabay_videos("x", "k")[0]
    assert item.extra == {"tags": "coffee cup", "rank": 0}


def test_claim_skips_used_media():
    v = M.Visuals(Settings(), used_keys={"pexels:1"})
    a = M.MediaItem("pexels", "1", "video", width=1080, height=1920, duration=10)
    b = M.MediaItem("pexels", "2", "video", width=1920, height=1080, duration=10)
    assert v._claim([a, b], 5).key == "pexels:2"
    assert v._claim([a, b], 5) is None


def test_simplify_query():
    assert M.simplify_query("The octopus in the deep ocean") == "octopus deep"
    assert M.simplify_query("writing numbered entries in notebook") == "writing notebook"
    assert M.simplify_query("reader tracking page in notebook") == "reading notebook"
    assert M.simplify_query("quiz contestant spilling coffee") == "spilling coffee"


def test_claim_prefers_semantic_match_over_nature_false_positive():
    v = M.Visuals(Settings())
    waterfall = M.MediaItem("pixabay", "1", "video", width=1080, height=1920,
                            extra={"tags": "waterfall, river, nature", "rank": 0})
    screen = M.MediaItem("pixabay", "2", "video", width=1920, height=1080,
                         extra={"tags": "computer, data, screen", "rank": 8})
    assert v._claim([waterfall, screen], 5, "data stream").key == "pixabay:2"


def test_ai_image_fallback_runs_after_scene_stock_misses(tmp_path, monkeypatch):
    settings = Settings(visual_sources=["pixabay"], openrouter_api_key="test-key")
    visuals = M.Visuals(settings)
    unrelated = M.MediaItem("pixabay", "waterfall", "video", width=1080, height=1920,
                             extra={"tags": "waterfall, river, nature", "rank": 0})
    monkeypatch.setattr(visuals, "_search", lambda *_: [unrelated])
    calls = []

    def fake_ai(source, prompt, *_):
        calls.append((source, prompt))
        return M.MediaItem(source, "scene", "image", query=prompt)

    monkeypatch.setattr(visuals, "_ai", fake_ai)
    item = visuals.for_scene(0, "data stream", "laptop displaying data", "software", 3.0, tmp_path)
    assert item.source == "openrouter-images"
    assert calls == [("openrouter-images", "laptop displaying data")]


def test_no_footage_falls_back_to_generated(tmp_path):
    v = M.Visuals(Settings(visual_sources=["local"], media_dir=str(tmp_path / "none")))
    item = v.for_scene(0, "octopus", "octopus", "sea", 3.0, tmp_path)
    assert item.kind == "generated"


def test_pollinations_payment_required_stops_asking(monkeypatch, tmp_path, caplog):
    calls = []

    def refuse(prompt, dest, width, height, key=""):
        calls.append(key)
        raise M.PermanentError("download https://image.pollinations.ai/...: HTTP 402 — {}")
    monkeypatch.setattr(M, "pollinations_image", refuse)
    v = M.Visuals(Settings(visual_sources=["pollinations"], pollinations_api_key="pk_x"))
    items = [v.for_scene(i, "cat", "a cat", "cats", 3.0, tmp_path) for i in range(4)]
    assert calls == ["pk_x"] and all(i.kind == "generated" for i in items)
    assert "POLLINATIONS_API_KEY" in caplog.text and caplog.text.count("refused") == 1
