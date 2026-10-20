"""Visual sourcing: stock footage, your media folder, OpenAI / OpenRouter image generation, and optional
OpenRouter video generation. Clips are never reused across videos, portrait footage is preferred, and a scene
always gets *something* (animated gradient)."""

from __future__ import annotations

import base64
import concurrent.futures
import logging
import math
import random
import re
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import quote

from . import usage
from .config import Settings
from .utils import PermanentError, download, http, raise_for_status, redact, with_retries

log = logging.getLogger("purffle")

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
STOP_WORDS = {"the", "a", "an", "of", "and", "in", "on", "with", "for", "to", "at", "by", "from", "closeup"}
# Camera / framing words and vague modifiers: they say nothing about *what* is on screen.
CAMERA_WORDS = {"closeup", "close", "up", "shot", "view", "scene", "footage", "video", "clip", "camera", "slow",
                "motion", "macro", "aerial", "pov", "angle", "cinematic", "background", "detail", "detailed"}
MODIFIER_WORDS = {"hands", "hand", "multiple", "same", "numbered", "digital", "single", "several", "showing",
                  "various", "many", "different", "abstract", "concept", "modern", "beautiful", "simple",
                  "small", "big", "large", "tiny", "final", "being", "very"}
# Words that stock sites read the "wrong" way ("stream" -> rivers, "tracking" -> drone tracking shots).
AMBIGUOUS_WORDS = {"stream", "streams", "streaming", "tracking", "track", "flow", "cloud", "pipeline", "bridge"}
AGENT_TO_ACTION = {"reader": "reading", "writer": "writing", "runner": "running", "swimmer": "swimming",
                   "driver": "driving", "speaker": "speaking", "dancer": "dancing", "singer": "singing",
                   "player": "playing", "worker": "working", "painter": "painting", "cooker": "cooking"}
# Disambiguation guard: an office / digital query must never be answered with pure landscape footage.
DIGITAL_CONTEXT = {"data", "code", "coding", "server", "servers", "screen", "software", "reader", "reading", "page",
                   "notebook", "computer", "laptop", "keyboard", "database", "network", "app", "website",
                   "programming", "programmer", "message", "messages", "queue", "office", "phone", "smartphone",
                   "monitor", "spreadsheet", "document", "documents", "book", "writing", "desk"}
NATURE_TERMS = {"waterfall", "river", "forest", "nature", "farm", "tractor", "agriculture", "aerial", "mountain",
                "mountains", "ocean", "sea", "lake", "creek", "landscape", "drone", "field", "fields", "silo",
                "silos", "countryside", "rural", "beach", "waves", "jungle", "woods", "valley", "canyon", "cows",
                "cattle", "crops", "meadow", "hills", "rainforest", "cascade"}
_IGNORED_FOR_RELEVANCE = STOP_WORDS | CAMERA_WORDS | {"hands", "hand", "person", "people", "man", "woman"}
AI_IMAGE_SOURCES = ("openai-images", "ai", "dalle", "gpt-image", "openrouter-images", "pollinations")


@dataclass
class MediaItem:
    source: str
    id: str
    kind: str                     # video | image | generated
    url: str = ""
    width: int = 0
    height: int = 0
    duration: float = 0.0
    credit: str = ""
    path: Path | None = None
    query: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    @property
    def portrait(self) -> bool:
        return self.height > self.width


# ------------------------------------------------------------------------------------------ Pexels
def _pexels_pick_file(files: list[dict], prefer_4k: bool) -> dict | None:
    files = [f for f in files if f.get("link") and f.get("width") and f.get("height")
             and f.get("file_type", "video/mp4") == "video/mp4"]
    if not files:
        return None
    cap = 4096 if prefer_4k else 2160

    def short(f):
        return min(f["width"], f["height"])
    good = [f for f in files if 1080 <= short(f) <= cap]
    if good:
        return min(good, key=short) if not prefer_4k else max(good, key=short)
    return max(files, key=short)


def _slug_words(page_url: str) -> str:
    """'https://www.pexels.com/video/person-writing-in-a-notebook-12345/' -> 'person writing in a notebook'."""
    path = (page_url or "").rstrip("/").rsplit("/", 1)[-1]
    words = [w for w in re.split(r"[-_]+", path) if w and not w.isdigit()]
    return " ".join(words)


@usage.free_call("pexels", "video-search")
def pexels_videos(query: str, key: str, prefer_4k: bool = False, orientation: str = "portrait") -> list[MediaItem]:
    params = {"query": query, "per_page": 15, "size": "medium"}
    if orientation:
        params["orientation"] = orientation
    r = http().get("https://api.pexels.com/videos/search", params=params, headers={"Authorization": key}, timeout=30)
    raise_for_status(r, "Pexels video search")
    items = []
    for rank, v in enumerate(r.json().get("videos", [])):
        f = _pexels_pick_file(v.get("video_files", []), prefer_4k)
        if not f:
            continue
        items.append(MediaItem("pexels", str(v["id"]), "video", f["link"], f["width"], f["height"],
                               float(v.get("duration") or 0), (v.get("user") or {}).get("name", ""), query=query,
                               extra={"tags": _slug_words(str(v.get("url") or "")), "rank": rank}))
    return items


@usage.free_call("pexels", "photo-search")
def pexels_photos(query: str, key: str, orientation: str = "portrait") -> list[MediaItem]:
    params = {"query": query, "per_page": 15}
    if orientation:
        params["orientation"] = orientation
    r = http().get("https://api.pexels.com/v1/search", params=params, headers={"Authorization": key}, timeout=30)
    raise_for_status(r, "Pexels photo search")
    items = []
    for rank, p in enumerate(r.json().get("photos", [])):
        src = p.get("src") or {}
        url = src.get("original")
        if not url:
            continue
        url += ("&" if "?" in url else "?") + "auto=compress&cs=tinysrgb&h=2400"
        tags = f"{_slug_words(str(p.get('url') or ''))} {p.get('alt') or ''}".strip()
        items.append(MediaItem("pexels-photo", str(p["id"]), "image", url, p.get("width", 0), p.get("height", 0),
                               credit=p.get("photographer", ""), query=query, extra={"tags": tags, "rank": rank}))
    return items


# ------------------------------------------------------------------------------------------ Pixabay
@usage.free_call("pixabay", "video-search")
def pixabay_videos(query: str, key: str, prefer_4k: bool = False) -> list[MediaItem]:
    r = http().get("https://pixabay.com/api/videos/", timeout=30, params={
        "key": key, "q": query[:100], "per_page": 20, "safesearch": "true"})
    raise_for_status(r, "Pixabay video search")
    order = ["large", "medium", "small"] if prefer_4k else ["medium", "large", "small"]
    items = []
    for rank, h in enumerate(r.json().get("hits", [])):
        vids = h.get("videos") or {}
        f = next((vids[q] for q in order if (vids.get(q) or {}).get("url")), None)
        if not f:
            continue
        items.append(MediaItem("pixabay", str(h["id"]), "video", f["url"], f.get("width", 0), f.get("height", 0),
                               float(h.get("duration") or 0), h.get("user", ""), query=query,
                               extra={"tags": str(h.get("tags") or ""), "rank": rank}))
    return items


@usage.free_call("pixabay", "photo-search")
def pixabay_photos(query: str, key: str, orientation: str = "portrait") -> list[MediaItem]:
    pix = {"portrait": "vertical", "landscape": "horizontal"}.get(orientation, "all")
    r = http().get("https://pixabay.com/api/", timeout=30, params={
        "key": key, "q": query[:100], "image_type": "photo", "orientation": pix,
        "per_page": 20, "safesearch": "true"})
    raise_for_status(r, "Pixabay photo search")
    return [MediaItem("pixabay-photo", str(h["id"]), "image", h["largeImageURL"], h.get("imageWidth", 0),
                      h.get("imageHeight", 0), credit=h.get("user", ""), query=query,
                      extra={"tags": str(h.get("tags") or ""), "rank": rank})
            for rank, h in enumerate(r.json().get("hits", [])) if h.get("largeImageURL")]


# ------------------------------------------------------------------------------------------ AI images
@usage.stage("image")
def openai_image(prompt: str, dest: Path, key: str, model: str, orientation: str = "portrait") -> Path:
    body = {"model": model, "prompt": prompt, "n": 1}
    if model.startswith("dall-e"):
        size = {"portrait": "1024x1792", "landscape": "1792x1024"}.get(orientation, "1024x1024")
        body.update(size=size, response_format="b64_json", quality="hd" if model == "dall-e-3" else "standard")
    else:
        size = {"portrait": "1024x1536", "landscape": "1536x1024"}.get(orientation, "1024x1024")
        body.update(size=size, quality="medium")

    def _do():
        with usage.request("openai", model, images=1) as call:
            r = http().post("https://api.openai.com/v1/images/generations", json=body, timeout=240,
                            headers={"Authorization": f"Bearer {key}"})
            call.capture(r)
            raise_for_status(r, "OpenAI image")
            d = r.json()["data"][0]
            if d.get("b64_json"):
                dest.write_bytes(base64.b64decode(d["b64_json"]))
            else:
                download(d["url"], dest)
            return dest

    return with_retries(_do, attempts=2, label="OpenAI image")


@usage.stage("image")
def openrouter_image(prompt: str, dest: Path, settings: Settings) -> Path:
    if not settings.openrouter_api_key:
        raise PermanentError("VISUAL_SOURCES=openrouter-images needs OPENROUTER_API_KEY")
    aspect = {"portrait": "9:16", "landscape": "16:9"}.get(settings.orientation, "1:1")
    body = {"model": settings.openrouter_image_model, "prompt": prompt, "n": 1,
            "resolution": "1K", "aspect_ratio": aspect, "output_format": "png"}
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}",
               "HTTP-Referer": "https://github.com/Chamanrajragu/purffle-shorts", "X-Title": "PurffleShorts"}

    def _do():
        with usage.request("openrouter", settings.openrouter_image_model, images=1) as call:
            r = http().post("https://openrouter.ai/api/v1/images", json=body, headers=headers, timeout=240)
            call.capture(r)
            raise_for_status(r, "OpenRouter image")
            images = r.json().get("data") or []
            if not images or not images[0].get("b64_json"):
                raise PermanentError("OpenRouter image response did not contain image data")
            image = base64.b64decode(images[0]["b64_json"])
            suffix = (".jpg" if image.startswith(b"\xff\xd8\xff") else
                      ".webp" if image.startswith(b"RIFF") and image[8:12] == b"WEBP" else ".png")
            path = dest.with_suffix(suffix)
            path.write_bytes(image)
            return path

    return with_retries(_do, attempts=2, label="OpenRouter image")


@usage.stage("video")
def openrouter_video(prompt: str, dest: Path, settings: Settings, seconds: float) -> Path:
    if not settings.openrouter_api_key:
        raise PermanentError("VISUAL_SOURCES=openrouter-video needs OPENROUTER_API_KEY")
    aspect = {"portrait": "9:16", "landscape": "16:9"}.get(settings.orientation, "1:1")
    body = {"model": settings.openrouter_video_model, "prompt": prompt,
            "duration": max(4, min(15, math.ceil(seconds))), "resolution": "720p",
            "aspect_ratio": aspect, "generate_audio": False}
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}",
               "HTTP-Referer": "https://github.com/Chamanrajragu/purffle-shorts", "X-Title": "PurffleShorts"}
    api = "https://openrouter.ai/api/v1/videos"
    with usage.request("openrouter", settings.openrouter_video_model, video_seconds=body["duration"]) as call:
        r = http().post(api, json=body, headers=headers, timeout=60)
        call.capture(r)
        raise_for_status(r, "OpenRouter video")
        job_id = r.json().get("id")
        if not job_id:
            raise PermanentError("OpenRouter video response did not contain a job id")
        call.event["job_id"] = str(job_id)
        call.event["request_id"] = r.json().get("generation_id")
        call.checkpoint()
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            r = http().get(f"{api}/{quote(str(job_id), safe='')}", headers=headers, timeout=30)
            raise_for_status(r, "OpenRouter video status")
            status = r.json()
            call.capture(r, status)
            if status.get("status") == "completed":
                return download(f"{api}/{quote(str(job_id), safe='')}/content?index=0", dest,
                                headers=headers, timeout=120)
            if status.get("status") in ("failed", "cancelled", "expired"):
                raise PermanentError(f"OpenRouter video {status.get('status')}: {status.get('error', 'unknown error')}")
            time.sleep(5)
        raise TimeoutError("OpenRouter video generation did not finish within 10 minutes")


_POLLINATIONS_LOCK = threading.Lock()


@usage.stage("image")
def pollinations_image(prompt: str, dest: Path, width: int, height: int, key: str = "") -> Path:
    url = (f"https://image.pollinations.ai/prompt/{quote(prompt[:900])}"
           f"?width={width}&height={height}&nologo=true&model=flux&seed={random.randint(1, 10**9)}")
    headers = {"Authorization": f"Bearer {key}"} if key else None
    # One request at a time: parallel scenes would all be rate-limited. Since September 2026 anonymous
    # use is limited to roughly one image every few minutes (HTTP 402 "payment required" otherwise).
    with _POLLINATIONS_LOCK:
        def attempt():
            with usage.request("pollinations", "flux", images=1):
                return download(url, dest, headers=headers, timeout=180, max_bytes=30 * 1024 * 1024, attempts=1)
        return with_retries(attempt, attempts=3, label="Pollinations image")


# ------------------------------------------------------------------------------------------ selection
def simplify_query(query: str) -> str:
    """Shorter fallback query that keeps the action and the concrete subject.

    'writing numbered entries in notebook' -> 'writing notebook'; 'quiz contestant spilling coffee' ->
    'spilling coffee'. Camera words, vague modifiers and words stock sites misread are dropped."""
    drop = STOP_WORDS | CAMERA_WORDS | MODIFIER_WORDS | AMBIGUOUS_WORDS
    words = [AGENT_TO_ACTION.get(w, w) for w in re.findall(r"[A-Za-z]+", query.lower()) if w not in drop]
    words = list(dict.fromkeys(words))
    if len(words) <= 2:
        return " ".join(words)
    last = words[-1]
    action = next((w for w in words[:-1] if len(w) > 4 and w.endswith("ing")), "")
    return f"{action} {last}" if action else " ".join(words[:2])


def _stem(word: str) -> str:
    w = word.lower()
    if len(w) > 5 and w.endswith("ing"):
        w = w[:-3]
    elif len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith(("ches", "shes", "xes", "sses")):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    elif len(w) > 4 and w.endswith("ed"):
        w = w[:-2]
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "aeiou":
        w = w[:-1]
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    return w


def _tokens(text: str, ignore: set[str] = frozenset()) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z]+", (text or "").lower()) if w not in ignore and len(w) > 1}


def _relevance_score(item: MediaItem, query: str) -> tuple[int, float]:
    """(overlap_count, rank_bonus) between a search hit and the scene's query.

    overlap_count is how many meaningful query terms appear in the hit's tags; -100 marks a classic false
    positive (an office / digital query answered with pure landscape footage) that must never be used."""
    extra = item.extra or {}
    rank = extra.get("rank")
    rank_bonus = max(0.0, 2.0 - float(rank) * 0.15) if isinstance(rank, (int, float)) else 0.0
    tags_raw = str(extra.get("tags") or "")
    if not tags_raw.strip():
        return 0, rank_bonus
    q_words = {w for w in re.findall(r"[a-z]+", (query or "").lower())}
    q_tokens = _tokens(query, _IGNORED_FOR_RELEVANCE)
    tag_words = set(re.findall(r"[a-z]+", tags_raw.lower()))
    tag_tokens = _tokens(tags_raw, _IGNORED_FOR_RELEVANCE)
    overlap = len(q_tokens & tag_tokens)
    if (q_words & DIGITAL_CONTEXT and overlap == 0 and tag_words & NATURE_TERMS
            and not tag_words & DIGITAL_CONTEXT):
        return -100, 0.0
    return overlap, rank_bonus


def _has_tags(item: MediaItem) -> bool:
    return bool(str((item.extra or {}).get("tags") or "").strip())


def _shape(item: MediaItem) -> str:
    if item.height > item.width:
        return "portrait"
    return "landscape" if item.width > item.height else "square"


def _score(item: MediaItem, need: float, orientation: str = "portrait", query: str = "") -> float:
    overlap, rank_bonus = _relevance_score(item, query) if query else (0, 0.0)
    if overlap < 0:
        return -100.0
    s = overlap * 3.5 + rank_bonus
    if _shape(item) == orientation or (orientation == "square" and item.width and item.height):
        s += 3
    if item.kind == "video":
        s += 2 if item.duration >= need else (1 if item.duration >= need * 0.6 else 0)
    if min(item.width, item.height) >= 1080:
        s += 1
    return s + random.uniform(0, 0.35)  # only a tie-breaker between equally relevant candidates


class Visuals:
    def __init__(self, settings: Settings, used_keys: set[str] | None = None,
                 extra_images: list[str] | None = None, extra_videos: list[str] | None = None,
                 repeat_extra: bool = False, scene_media: list[list[MediaItem]] | None = None):
        self.s = settings
        self.used = set(used_keys or ())
        self.lock = threading.Lock()
        self._search_cache: dict[tuple[str, str], list[MediaItem]] = {}
        self.sources = [x for x in settings.visual_sources if x]
        if settings.offline:
            self.sources = ["local"]
        vids = [
            MediaItem("product-page", f"vid{i:02d}", "video", url=u)
            for i, u in enumerate(extra_videos or []) if u and not settings.offline
        ]
        imgs = [
            MediaItem("product-page", f"img{i:02d}", "image", url=u)
            for i, u in enumerate(extra_images or []) if u and not settings.offline
        ]
        self.extra_images = vids + imgs
        self.repeat_extra = repeat_extra
        self.scene_media = scene_media or []
        self.credits: set[str] = set()
        self._ai_refused: set[str] = set()

    def _ai_fallback_source(self) -> str | None:
        """AI image source used when stock footage has no confirmed match for a scene (needs a key)."""
        s = self.s
        if s.offline or not getattr(s, "ai_image_fallback", True):
            return None
        if s.openrouter_api_key and "openrouter-images" not in self._ai_refused:
            return "openrouter-images"
        if s.openai_api_key and "openai-images" not in self._ai_refused:
            return "openai-images"
        return None

    # -- search per source (cached per query) --
    def _search(self, source: str, query: str) -> list[MediaItem]:
        ck = (source, query.lower())
        if ck in self._search_cache:
            return self._search_cache[ck]
        s = self.s
        items: list[MediaItem] = []
        try:
            o = s.orientation
            if source == "pexels" and s.pexels_api_key:
                items = pexels_videos(query, s.pexels_api_key, s.prefer_4k, orientation=o)
                if len(items) < 3:
                    items += pexels_videos(query, s.pexels_api_key, s.prefer_4k, orientation="")
                if not items:
                    items = pexels_photos(query, s.pexels_api_key, orientation=o)
            elif source == "pexels-photos" and s.pexels_api_key:
                items = pexels_photos(query, s.pexels_api_key, orientation=o)
            elif source == "pixabay" and s.pixabay_api_key:
                items = (pixabay_videos(query, s.pixabay_api_key, s.prefer_4k)
                         or pixabay_photos(query, s.pixabay_api_key, orientation=o))
            elif source == "pixabay-photos" and s.pixabay_api_key:
                items = pixabay_photos(query, s.pixabay_api_key, orientation=o)
            elif source == "local":
                items = self._local(query)
            seen: set[str] = set()
            items = [i for i in items if not (i.key in seen or seen.add(i.key))]
        except PermanentError as e:
            log.warning("%s search failed permanently (%s); disabling it for this video", source, redact(e))
            self.sources = [x for x in self.sources if x != source]
        except Exception as e:
            log.warning("%s search for %r failed: %s", source, query, redact(e))
        self._search_cache[ck] = items
        return items

    @usage.free_call("local", "media-folder")
    def _local(self, query: str) -> list[MediaItem]:
        root = Path(self.s.media_dir)
        if not root.is_dir():
            return []
        words = set(simplify_query(query).split()) | set(query.lower().split())
        items = []
        for p in root.rglob("*"):
            ext = p.suffix.lower()
            if ext not in VIDEO_EXT | IMAGE_EXT:
                continue
            stem = set(re.findall(r"[a-z]+", p.stem.lower()))
            item = MediaItem("local", str(p), "video" if ext in VIDEO_EXT else "image", path=p, query=query)
            item.extra["overlap"] = len(words & stem)
            items.append(item)
        items.sort(key=lambda i: i.extra["overlap"], reverse=True)
        return items

    def _claim(self, candidates: list[MediaItem], need: float, query: str = "",
               min_overlap: int = 0) -> MediaItem | None:
        """Pick the best unused candidate. Stock hits carrying tags are ranked by relevance to ``query``;
        known false positives are dropped, and ``min_overlap`` demands a confirmed semantic match."""
        with self.lock:
            fresh = [c for c in candidates if c.key not in self.used]
            if not fresh:
                return None
            if fresh[0].source == "product-page":
                best = fresh[0]
            elif fresh[0].source == "local":
                if min_overlap and not fresh[0].extra.get("overlap"):
                    return None
                best = fresh[0] if fresh[0].extra.get("overlap") else random.choice(fresh)
            else:
                if query:
                    rel = {c.key: _relevance_score(c, query) for c in fresh}
                    fresh = [c for c in fresh if rel[c.key][0] >= 0]
                    if min_overlap:
                        fresh = [c for c in fresh if rel[c.key][0] >= min_overlap]
                    if not fresh:
                        return None
                    tagged = [c for c in fresh if _has_tags(c)]
                    if (tagged and len(tagged) == len(fresh)
                            and all(rel[c.key][0] == 0 and int(c.extra.get("rank", 0) or 0) >= 5 for c in fresh)):
                        return None  # only low-ranked, unrelated leftovers: try the next query instead
                best = max(fresh, key=lambda c: _score(c, need, self.s.orientation, query))
            self.used.add(best.key)
            return best

    def _fetch(self, item: MediaItem, dest_dir: Path, idx: int) -> MediaItem:
        if item.source == "local":
            return item
        ext = ".mp4" if item.kind == "video" else ".jpg"
        item.path = download(item.url, dest_dir / f"scene{idx:02d}_{item.source}_{item.id}{ext}")
        return item

    def _ai(self, source: str, prompt: str, dest_dir: Path, idx: int) -> MediaItem | None:
        s = self.s
        full = f"{prompt}. {s.visual_style}. No text, no letters, no watermark."
        dest = dest_dir / f"scene{idx:02d}_ai.png"
        try:
            if source in ("openai-images", "ai", "dalle", "gpt-image") and s.openai_api_key:
                openai_image(full, dest, s.openai_api_key, s.image_model, s.orientation)
            elif source == "openrouter-images":
                dest = openrouter_image(full, dest, s)
            elif source == "pollinations":
                pollinations_image(full, dest.with_suffix(".jpg"), s.width, s.height, s.pollinations_api_key)
                dest = dest.with_suffix(".jpg")
            else:
                return None
        except PermanentError as e:
            # A refused key or an exhausted free tier won't recover within this video: stop asking.
            with self.lock:
                first_refusal = source not in self._ai_refused
                self._ai_refused.add(source)
                if source in self.sources:
                    self.sources = [x for x in self.sources if x != source]
                    hint = (" Anonymous Pollinations use is now heavily rate-limited; set POLLINATIONS_API_KEY "
                            "or use Pexels/Pixabay (free keys)." if source == "pollinations" and " 402" in str(e)
                            else "")
                    log.warning("AI images from %s refused (%s); skipping it for this video.%s",
                                source, redact(e)[:160], hint)
                elif first_refusal:
                    log.warning("AI image fallback (%s) refused (%s); using stock footage only for this video",
                                source, redact(e)[:160])
            return None
        except Exception as e:
            log.warning("AI image (%s) for scene %d failed: %s", source, idx + 1, redact(e))
            return None
        log.info("Scene %d: %s image", idx + 1, source)
        return MediaItem(source, dest.name, "image", path=dest, width=s.width, height=s.height, query=prompt)

    def _extra_candidates_for_scene(self, idx: int) -> list[MediaItem]:
        if idx < len(self.scene_media) and self.scene_media[idx]:
            return list(self.scene_media[idx])
        pool = self.extra_images
        if not pool:
            return []
        if self.repeat_extra:
            start = idx % len(pool)
            return pool[start:] + pool[:start]
        if idx < len(pool):
            return pool[idx:]
        return []

    def _stock_pick(self, source: str, queries: list[str], need: float, dest_dir: Path, idx: int,
                    min_overlap: int = 0) -> MediaItem | None:
        for q in queries:
            cand = self._search(source, q)
            item = self._claim(cand, need, q, min_overlap=min_overlap)
            if not item:
                continue
            try:
                self._fetch(item, dest_dir, idx)
            except Exception as e:
                log.warning("Download failed for %s: %s", item.key, redact(e))
                continue
            if item.source.startswith("pexels"):
                self.credits.add("Pexels")
            elif item.source.startswith("pixabay"):
                self.credits.add("Pixabay")
            log.info("Scene %d: %s %s (%r)", idx + 1, item.source, item.kind, q)
            return item
        return None

    def for_scene(self, idx: int, query: str, image_prompt: str, topic: str, need: float, dest_dir: Path) -> MediaItem:
        for cand in self._extra_candidates_for_scene(idx):
            item = replace(cand, query=query)
            try:
                self._fetch(item, dest_dir, idx)
                with self.lock:
                    self.used.add(item.key)
                log.info("Scene %d: product page %s (%s)", idx + 1, item.kind, item.id)
                return item
            except Exception as e:
                log.warning("Product media download failed (%s): %s", item.url[:60], redact(e))

        # Product scenes stay within their mapped gallery. A failed store URL must not turn into unrelated stock.
        if idx < len(self.scene_media):
            log.info("Scene %d: product media unavailable — using an animated background", idx + 1)
            with usage.request("local", "animated-background", free=True, video_seconds=need):
                pass
            return MediaItem("generated", f"gradient-{idx}", "generated", query=query)

        def dedupe(values, skip=()):
            out: list[str] = []
            for q in values:
                q = (q or "").strip()
                if q and q.lower() not in [x.lower() for x in [*out, *skip]]:
                    out.append(q)
            return out
        scene_qs = dedupe([query, simplify_query(query)])
        topic_qs = dedupe([simplify_query(topic), topic], skip=scene_qs)
        # With an AI image key available, stock footage must prove it matches the scene (tag overlap) before
        # it is used; a scene with no real match gets a tailor-made image instead of an unrelated clip.
        fallback = self._ai_fallback_source()
        strict = 1 if fallback else 0
        tried_ai: set[str] = set()
        deferred_ai = {"openrouter-images": {"openrouter-images"},
                       "openai-images": {"openai-images", "ai", "dalle", "gpt-image"}}
        for source in list(self.sources):
            if source in AI_IMAGE_SOURCES:
                if fallback and source in deferred_ai.get(fallback, set()):
                    continue
                tried_ai.add(source)
                item = self._ai(source, image_prompt or query, dest_dir, idx)
                if item:
                    return item
                continue
            if source == "openrouter-video":
                dest = dest_dir / f"scene{idx:02d}_openrouter.mp4"
                try:
                    openrouter_video(f"{image_prompt or query}. {self.s.visual_style}", dest, self.s, need)
                    log.info("Scene %d: OpenRouter video", idx + 1)
                    return MediaItem(source, dest.name, "video", width=self.s.width, height=self.s.height,
                                     duration=need, path=dest, query=image_prompt or query)
                except PermanentError as e:
                    with self.lock:
                        self.sources = [x for x in self.sources if x != source]
                    log.warning("OpenRouter video unavailable (%s); disabling it for this video", redact(e)[:160])
                except Exception as e:
                    log.warning("OpenRouter video for scene %d failed: %s", idx + 1, redact(e))
                continue
            item = self._stock_pick(source, scene_qs, need, dest_dir, idx, min_overlap=strict)
            if not item and not strict:
                item = self._stock_pick(source, topic_qs, need, dest_dir, idx)
            if item:
                return item
        if strict:
            if fallback not in tried_ai:
                log.info("Scene %d: no stock footage really matches %r — generating an image", idx + 1, query)
                item = self._ai(fallback, image_prompt or query, dest_dir, idx)
                if item:
                    return item
            for source in [x for x in self.sources if x not in AI_IMAGE_SOURCES and x != "openrouter-video"]:
                item = self._stock_pick(source, [*scene_qs, *topic_qs], need, dest_dir, idx)
                if item:
                    return item
        log.info("Scene %d: no footage found for %r — using an animated background", idx + 1, query)
        with usage.request("local", "animated-background", free=True, video_seconds=need):
            pass
        return MediaItem("generated", f"gradient-{idx}", "generated", query=query)

    def for_scenes(self, jobs: list[tuple[str, str, float]], topic: str, dest_dir: Path) -> list[MediaItem]:
        """jobs: [(search_query, image_prompt, seconds_needed)] -> one MediaItem per scene."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        workers = 2 if any(s in ("openai-images", "ai", "openrouter-images", "openrouter-video", "pollinations")
                           for s in self.sources) else 4
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [usage.submit(ex, self.for_scene, i, q, p, topic, need, dest_dir)
                    for i, (q, p, need) in enumerate(jobs)]
            return [f.result() for f in futs]
