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
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from . import usage
from .config import Settings
from .utils import PermanentError, download, http, raise_for_status, redact, with_retries

log = logging.getLogger("purffle")

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
STOP_WORDS = {"the", "a", "an", "of", "and", "in", "on", "with", "for", "to", "at", "by", "from", "closeup"}


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


@usage.free_call("pexels", "video-search")
def pexels_videos(query: str, key: str, prefer_4k: bool = False, orientation: str = "portrait") -> list[MediaItem]:
    params = {"query": query, "per_page": 15, "size": "medium"}
    if orientation:
        params["orientation"] = orientation
    r = http().get("https://api.pexels.com/videos/search", params=params, headers={"Authorization": key}, timeout=30)
    raise_for_status(r, "Pexels video search")
    items = []
    for v in r.json().get("videos", []):
        f = _pexels_pick_file(v.get("video_files", []), prefer_4k)
        if not f:
            continue
        items.append(MediaItem("pexels", str(v["id"]), "video", f["link"], f["width"], f["height"],
                               float(v.get("duration") or 0), (v.get("user") or {}).get("name", ""), query=query))
    return items


@usage.free_call("pexels", "photo-search")
def pexels_photos(query: str, key: str, orientation: str = "portrait") -> list[MediaItem]:
    params = {"query": query, "per_page": 15}
    if orientation:
        params["orientation"] = orientation
    r = http().get("https://api.pexels.com/v1/search", params=params, headers={"Authorization": key}, timeout=30)
    raise_for_status(r, "Pexels photo search")
    items = []
    for p in r.json().get("photos", []):
        src = p.get("src") or {}
        url = src.get("original")
        if not url:
            continue
        url += ("&" if "?" in url else "?") + "auto=compress&cs=tinysrgb&h=2400"
        items.append(MediaItem("pexels-photo", str(p["id"]), "image", url, p.get("width", 0), p.get("height", 0),
                               credit=p.get("photographer", ""), query=query))
    return items


# ------------------------------------------------------------------------------------------ Pixabay
@usage.free_call("pixabay", "video-search")
def pixabay_videos(query: str, key: str, prefer_4k: bool = False) -> list[MediaItem]:
    r = http().get("https://pixabay.com/api/videos/", timeout=30, params={
        "key": key, "q": query[:100], "per_page": 20, "safesearch": "true"})
    raise_for_status(r, "Pixabay video search")
    order = ["large", "medium", "small"] if prefer_4k else ["medium", "large", "small"]
    items = []
    for h in r.json().get("hits", []):
        vids = h.get("videos") or {}
        f = next((vids[q] for q in order if (vids.get(q) or {}).get("url")), None)
        if not f:
            continue
        items.append(MediaItem("pixabay", str(h["id"]), "video", f["url"], f.get("width", 0), f.get("height", 0),
                               float(h.get("duration") or 0), h.get("user", ""), query=query))
    return items


@usage.free_call("pixabay", "photo-search")
def pixabay_photos(query: str, key: str, orientation: str = "portrait") -> list[MediaItem]:
    pix = {"portrait": "vertical", "landscape": "horizontal"}.get(orientation, "all")
    r = http().get("https://pixabay.com/api/", timeout=30, params={
        "key": key, "q": query[:100], "image_type": "photo", "orientation": pix,
        "per_page": 20, "safesearch": "true"})
    raise_for_status(r, "Pixabay photo search")
    return [MediaItem("pixabay-photo", str(h["id"]), "image", h["largeImageURL"], h.get("imageWidth", 0),
                      h.get("imageHeight", 0), credit=h.get("user", ""), query=query)
            for h in r.json().get("hits", []) if h.get("largeImageURL")]


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
    words = [w for w in re.findall(r"[A-Za-z]+", query.lower()) if w not in STOP_WORDS]
    return " ".join(words[:2])


def _shape(item: MediaItem) -> str:
    if item.height > item.width:
        return "portrait"
    return "landscape" if item.width > item.height else "square"


def _score(item: MediaItem, need: float, orientation: str = "portrait") -> float:
    s = 0.0
    if _shape(item) == orientation or (orientation == "square" and item.width and item.height):
        s += 3
    if item.kind == "video":
        s += 2 if item.duration >= need else (1 if item.duration >= need * 0.6 else 0)
    if min(item.width, item.height) >= 1080:
        s += 1
    return s + random.uniform(0, 1.5)  # a little variety between similar candidates


class Visuals:
    def __init__(self, settings: Settings, used_keys: set[str] | None = None,
                 extra_images: list[str] | None = None):
        self.s = settings
        self.used = set(used_keys or ())
        self.lock = threading.Lock()
        self._search_cache: dict[tuple[str, str], list[MediaItem]] = {}
        self.sources = [x for x in settings.visual_sources if x]
        if settings.offline:
            self.sources = ["local"]
        self.extra_images = [
            MediaItem("product-page", f"img{i:02d}", "image", url=u)
            for i, u in enumerate(extra_images or []) if u and not settings.offline
        ]
        self.credits: set[str] = set()

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

    def _claim(self, candidates: list[MediaItem], need: float) -> MediaItem | None:
        with self.lock:
            fresh = [c for c in candidates if c.key not in self.used]
            if not fresh:
                return None
            if fresh[0].source == "product-page":
                best = fresh[0]
            elif fresh[0].source == "local":
                best = fresh[0] if fresh[0].extra.get("overlap") else random.choice(fresh)
            else:
                best = max(fresh, key=lambda c: _score(c, need, self.s.orientation))
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
                if source in self.sources:
                    self.sources = [x for x in self.sources if x != source]
                    hint = (" Anonymous Pollinations use is now heavily rate-limited; set POLLINATIONS_API_KEY "
                            "or use Pexels/Pixabay (free keys)." if source == "pollinations" and " 402" in str(e)
                            else "")
                    log.warning("AI images from %s refused (%s); skipping it for this video.%s",
                                source, redact(e)[:160], hint)
            return None
        except Exception as e:
            log.warning("AI image (%s) for scene %d failed: %s", source, idx + 1, redact(e))
            return None
        log.info("Scene %d: %s image", idx + 1, source)
        return MediaItem(source, dest.name, "image", path=dest, width=s.width, height=s.height, query=prompt)

    def for_scene(self, idx: int, query: str, image_prompt: str, topic: str, need: float, dest_dir: Path) -> MediaItem:
        if self.extra_images:
            while True:
                item = self._claim(self.extra_images, need)
                if not item:
                    break
                try:
                    item.query = query
                    self._fetch(item, dest_dir, idx)
                    log.info("Scene %d: product page image (%s)", idx + 1, item.id)
                    return item
                except Exception as e:
                    log.warning("Product image download failed (%s): %s", item.url[:60], redact(e))
        queries = []
        for q in (query, simplify_query(query), simplify_query(topic), topic):
            q = (q or "").strip()
            if q and q.lower() not in [x.lower() for x in queries]:
                queries.append(q)
        for source in list(self.sources):
            if source in ("openai-images", "ai", "dalle", "gpt-image", "openrouter-images", "pollinations"):
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
            for q in queries:
                cand = self._search(source, q)
                item = self._claim(cand, need)
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
