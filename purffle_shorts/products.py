"""Product scouting across Shopify, Nuvemshop and WooCommerce stores + AI viral dossier generation."""

from __future__ import annotations

import html
import json
import logging
import math
import re
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote_plus, unquote, urljoin, urlparse

from .config import Settings
from .history import History
from .script import LANGUAGES
from .topics import (
    Topic,
    _find_ld_products,
    _ld_images,
    _select_main_product,
    _strip_html,
    _TextExtractor,
    extract_product,
)
from .utils import http, raise_for_status

log = logging.getLogger("purffle")

DEFAULT_STORES = [
    {
        "name": "Mavigadget",
        "url": "https://mavigadget.com",
        "platform": "shopify",
        "niche": "viral gadgets, home & car problem solvers",
    },
    {
        "name": "Inspire Uplift",
        "url": "https://www.inspireuplift.com",
        "platform": "shopify",
        "niche": "kitchen, bathroom, organization & everyday finds",
    },
    {
        "name": "The Grommet",
        "url": "https://thegrommet.com",
        "platform": "shopify",
        "niche": "clever inventions & daily problem solvers",
    },
    {
        "name": "Joseph Joseph",
        "url": "https://us.josephjoseph.com",
        "platform": "shopify",
        "niche": "smart kitchen & bathroom organization",
    },
]

ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["products"],
    "properties": {
        "products": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["index", "short_name", "viral_score", "pain_point", "hook_idea", "visual_angle", "benefits"],
                "properties": {
                    "index": {"type": "integer"},
                    "short_name": {"type": "string"},
                    "viral_score": {"type": "integer"},
                    "pain_point": {"type": "string"},
                    "hook_idea": {"type": "string"},
                    "visual_angle": {"type": "string"},
                    "benefits": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}

_VIDEO_URL_RE = re.compile(r'https?://[^\s"\'<>\\]+\.(?:mp4|webm)(?:\?[^\s"\'<>\\]*)?', re.I)
_INVALID_PRODUCT_IMAGE = re.compile(r"(?:logo|favicon|payment|bandeira|pix|whatsapp|placeholder|avatar|1x1|blank|\.svg|\.gif)", re.I)


def upgrade_and_dedupe_product_images(urls: list[str]) -> list[str]:
    """Normalize store image URLs, prefer the largest supplied variant, and remove invalid duplicates."""
    out: list[str] = []
    seen: dict[str, tuple[int, int]] = {}
    for raw in urls or []:
        url = str(raw or "").strip()
        if not url:
            continue
        url = re.sub(r"^http://", "https://", url, flags=re.I)
        url = re.sub(r"^//", "https://", url)
        parsed = urlparse(url)
        host, path = parsed.netloc.lower(), parsed.path
        if _INVALID_PRODUCT_IMAGE.search(path):
            continue
        image_size = 0
        if host.endswith(("mitiendanube.com", "tiendanube.com")):
            match = re.search(
                r"-(?:(50|100|240|320|480|640)-0|(1024)-1024)\.(?:webp|jpe?g|png)$", path, flags=re.I
            )
            if match:
                image_size = int(match.group(1) or match.group(2))
        if "cdn.shopify.com" in host:
            path = re.sub(r"_(?:pico|icon|thumb|small|compact|medium|large|grande|1024x1024|480x480|\d+x\d*)(?=\.(?:jpg|jpeg|png|webp)$)", "", path, flags=re.I)
            path = re.sub(r"-sw(?=\.(?:jpg|jpeg|png|webp)$)", "", path, flags=re.I)
        if "wp-content/uploads/" in path:
            path = re.sub(r"-\d+x\d+(?=\.(?:jpg|jpeg|png|webp)$)", "", path, flags=re.I)
        if "susercontent.com" in host:
            path = re.sub(r"@resize[^\s]+", "", path)
            path = re.sub(r"_tn$", "", path)
            path = re.sub(r"_tn(?=\.(?:jpg|jpeg|png|webp)$)", "", path, flags=re.I)
        upgraded = parsed._replace(scheme="https", path=path).geturl()
        canonical_path = re.sub(r"-(?:50|100|240|320|480|640|1024)-0(?=\.(?:webp|jpe?g|png)$)", "", path, flags=re.I)
        canonical_path = re.sub(r"-1024-1024(?=\.(?:webp|jpe?g|png)$)", "", canonical_path, flags=re.I)
        canonical_path = re.sub(r"-sw(?=\.(?:jpg|jpeg|png|webp)$)", "", canonical_path, flags=re.I)
        canonical = f"{host.lower()}{canonical_path}".lower()
        previous = seen.get(canonical)
        if previous:
            previous_index, previous_size = previous
            if image_size > previous_size:
                out[previous_index] = upgraded
                seen[canonical] = (previous_index, image_size)
            continue
        seen[canonical] = (len(out), image_size)
        out.append(upgraded)
    return out


def classify_product_media_url(url: str, index: int) -> dict:
    """Guess whether a product URL is a clip, clean hero photo, detail, or specification chart."""
    path = unquote(urlparse(str(url or "")).path).lower()
    name = path.rsplit("/", 1)[-1]
    words = set(re.findall(r"[a-z0-9]+", name))
    if Path(path).suffix.lower() in {".mp4", ".mov", ".m4v", ".webm", ".m3u8"} or "video" in words or "vod.susercontent" in url or "cv.shopee" in url:
        return {"kind": "video", "role": "demo"}
    if words & {"size", "dimension", "dimensions", "measurement", "measurements", "medida", "medidas",
                "tabela", "chart", "spec", "specs"}:
        role = "spec"
    elif words & {"hero", "main", "primary", "front", "cover"} or index == 0:
        role = "hero"
    else:
        role = "detail"
    return {"kind": "image", "role": role}


def _product_media_catalog(product: dict, image_limit: int = 8) -> list[tuple[str, dict]]:
    videos = [str(url).strip() for url in (product.get("videos") or []) if str(url or "").strip()]
    images = upgrade_and_dedupe_product_images(product.get("images") or [])
    indexed_images = [(i, url, classify_product_media_url(url, i)) for i, url in enumerate(images[:image_limit])]
    indexed_images.sort(key=lambda row: (row[2]["role"] == "spec", row[0]))
    if indexed_images and not any(meta["role"] == "hero" for _, _, meta in indexed_images):
        for _, _, meta in indexed_images:
            if meta["role"] != "spec":
                meta["role"] = "hero"
                break
    catalog = [(url, {"kind": "video", "role": "demo"}) for url in videos[:8]]
    catalog.extend((url, {**meta, "kind": "image", "role": "detail" if meta["kind"] == "video" else meta["role"]})
                   for _, url, meta in indexed_images)
    return catalog


def _media_context(product: dict, image_limit: int = 8) -> str:
    catalog = _product_media_catalog(product, image_limit)
    video_count = sum(meta["kind"] == "video" for _, meta in catalog)
    image_count = len(catalog) - video_count
    lines = [f"Available visual media: {video_count} video(s), {image_count} photo(s)."]
    if video_count == 0 and image_count:
        lines.append(
            "Media constraint: This product only has static catalog photos (no video clips). Write narration "
            "that highlights visible details, features, and benefits naturally over moving photos (Ken Burns), "
            "avoiding phrases that pretend a live hand movement is happening on screen right now."
        )
    elif video_count == 0:
        lines.append("Media constraint: No product video or catalog photo is available; do not describe a live action on screen.")
    lines.append("Product media inventory:")
    lines.extend(
        f"- [media_index={i}] {meta['kind']} ({meta['role']}): {urlparse(url).path.rsplit('/', 1)[-1] or url}"
        for i, (url, meta) in enumerate(catalog)
    )
    return "\n".join(lines)


class _ProductGalleryParser(HTMLParser):
    """Collect large image URLs from the product gallery classes used by Nuvemshop and WooCommerce."""

    _GALLERY_CLASSES = {"js-product-slide-img", "woocommerce-product-gallery__image"}
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.images: list[str] = []
        self.stack: list[tuple[str, bool]] = []

    def _capture(self, attrs: dict[str, str]) -> None:
        for key in ("data-zoom", "data-large_image", "data-srcset", "srcset", "href", "data-src", "src"):
            value = attrs.get(key, "")
            if not value:
                continue
            if "srcset" in key:
                candidates = []
                for part in value.split(","):
                    bits = part.strip().split()
                    if bits:
                        rank = float(re.sub(r"[^0-9.]", "", bits[-1]) or 0) if len(bits) > 1 else 0
                        candidates.append((rank, bits[0]))
                value = max(candidates, default=(0, ""))[1]
            if value and not value.lower().startswith("data:"):
                full = urljoin(self.base_url, html.unescape(value.strip()))
                if full not in self.images:
                    self.images.append(full)

    def handle_starttag(self, tag, attrs):
        values = {key.lower(): (value or "") for key, value in attrs if key}
        classes = set(values.get("class", "").lower().split())
        is_gallery = bool(classes & self._GALLERY_CLASSES)
        if is_gallery or any(active for _, active in self.stack):
            self._capture(values)
        if tag not in self._VOID:
            self.stack.append((tag, is_gallery))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def _product_gallery_images(page: str, base_url: str) -> list[str]:
    main_page = re.split(
        r"(?i)(?:id=[\"']?related|class=[\"'][^\"']*(?:related|cross-sell|upsell|section-products-related))",
        page, maxsplit=1,
    )[0]
    parser = _ProductGalleryParser(base_url)
    try:
        parser.feed(main_page)
    except Exception:
        pass
    return parser.images


def _base_url(url: str) -> str:
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def detect_platform(url: str, page: str = "") -> str:
    low_u = (url or "").lower()
    low_p = (page or "").lower()
    if "shopee." in low_u or "shopeemobile.com" in low_p or "susercontent.com" in low_p:
        return "shopee"
    if "myshopify.com" in low_u or "cdn.shopify.com" in low_p or "shopify.shop" in low_p:
        return "shopify"
    if any(x in low_u or x in low_p for x in ("nuvemshop", "tiendanube", "d26lpennugtm8s.cloudfront.net", "ls.store")):
        return "nuvemshop"
    if any(x in low_u or x in low_p for x in ("woocommerce", "wp-content/plugins/woocommerce", "wc-blocks")):
        return "woocommerce"
    return "shopify"


def _calc_discount(price_str: str, compare_str: str) -> int:
    try:
        p = float(re.sub(r"[^\d.]", "", str(price_str).replace(",", ".")))
        c = float(re.sub(r"[^\d.]", "", str(compare_str).replace(",", ".")))
        if c > p > 0:
            return round((c - p) / c * 100)
    except (ValueError, TypeError):
        pass
    return 0


def _extract_bullets_from_html(raw_html: str) -> tuple[str, list[str]]:
    if not raw_html:
        return "", []
    ext = _TextExtractor()
    try:
        ext.feed(raw_html)
    except Exception:
        pass
    bullets = [b for b in ext.bullets if 8 <= len(b) <= 180][:6]
    desc = _strip_html(raw_html)[:1200]
    return desc, bullets


def _extract_videos_from_html(raw_html: str, base_url: str = "") -> list[str]:
    if not raw_html:
        return []
    unescaped = raw_html.replace(r"\/", "/")
    found: list[str] = []
    for m in _VIDEO_URL_RE.finditer(unescaped):
        u = html.unescape(m.group(0))
        if base_url:
            u = urljoin(base_url, u)
        if u not in found:
            found.append(u)
    return found[:4]


# ------------------------------------------------------------------ Platform 1: Shopify
def scout_shopify_store(store_url: str, store_name: str = "", query: str = "", limit: int = 12) -> list[dict]:
    """Fetch best-selling (or matching) products from a Shopify store's JSON feeds."""
    base = _base_url(store_url)
    name = store_name or urlparse(base).netloc.removeprefix("www.")
    endpoints = [
        f"{base}/collections/best-selling/products.json?limit={max(limit * 2, 24)}",
        f"{base}/collections/all/products.json?limit={max(limit * 2, 24)}",
        f"{base}/products.json?limit={max(limit * 2, 24)}",
    ]
    raw_products: list[dict] = []
    is_best_selling = False
    for idx, ep in enumerate(endpoints):
        try:
            r = http().get(ep, timeout=20, headers={"Accept": "application/json"})
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and isinstance(data.get("products"), list) and data["products"]:
                    raw_products = data["products"]
                    is_best_selling = (idx == 0)
                    break
        except Exception:
            continue

    if not raw_products:
        return []

    q_words = [w.lower() for w in re.split(r"\W+", query or "") if len(w) >= 2]
    results: list[dict] = []
    for rank, prod in enumerate(raw_products, 1):
        title = _strip_html(str(prod.get("title") or "")).strip()
        handle = str(prod.get("handle") or "").strip()
        if not title or not handle:
            continue
        body_html = str(prod.get("body_html") or "")
        tags = prod.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        ptype = str(prod.get("product_type") or "")
        blob = f"{title} {ptype} {' '.join(tags)} {_strip_html(body_html)}".lower()
        if q_words and not any(w in blob for w in q_words):
            continue

        variants = prod.get("variants") or []
        v0 = variants[0] if variants and isinstance(variants[0], dict) else {}
        price = str(v0.get("price") or "").strip()
        compare = str(v0.get("compare_at_price") or "").strip()
        discount = _calc_discount(price, compare)

        imgs: list[str] = []
        for im in prod.get("images") or []:
            src = im.get("src") if isinstance(im, dict) else str(im or "")
            if src:
                src = re.sub(r"^//", "https://", src.strip())
                if src not in imgs:
                    imgs.append(src)

        desc, bullets = _extract_bullets_from_html(body_html)
        videos = _extract_videos_from_html(body_html, base)
        for med in prod.get("media") or []:
            if isinstance(med, dict) and med.get("media_type") == "video":
                for s in med.get("sources") or []:
                    u = s.get("url") if isinstance(s, dict) else ""
                    if u and (".mp4" in u.lower() or s.get("format") == "mp4"):
                        u = re.sub(r"^//", "https://", u.strip())
                        if u not in videos:
                            videos.append(u)
        results.append({
            "store_name": name,
            "platform": "shopify",
            "external_url": f"{base}/products/{handle}",
            "url": f"{base}/products/{handle}",
            "title": title,
            "price": price,
            "compare_price": compare if discount > 0 else "",
            "currency": "",
            "discount_pct": discount,
            "rating": None,
            "reviews_count": 0,
            "best_seller_rank": rank if is_best_selling else None,
            "benefits": bullets[:4],
            "description": desc,
            "images": upgrade_and_dedupe_product_images(imgs)[:8],
            "videos": videos[:4],
        })
        if len(results) >= limit:
            break
    return results


# ------------------------------------------------------------------ Platform 2: WooCommerce
def scout_woocommerce_store(store_url: str, store_name: str = "", query: str = "", limit: int = 12) -> list[dict]:
    """Fetch popular products from a WooCommerce store via Store API or HTML fallback."""
    base = _base_url(store_url)
    name = store_name or urlparse(base).netloc.removeprefix("www.")
    params = {"orderby": "popularity", "per_page": str(max(limit, 16))}
    if query:
        params["search"] = query

    for api_path in ("/wp-json/wc/store/v1/products", "/wp-json/wc/store/products"):
        try:
            r = http().get(base + api_path, params=params, timeout=20, headers={"Accept": "application/json"})
            if r.status_code == 200:
                items = r.json()
                if isinstance(items, list) and items:
                    out: list[dict] = []
                    for rank, item in enumerate(items[:limit], 1):
                        title = _strip_html(str(item.get("name") or "")).strip()
                        permalink = str(item.get("permalink") or "").strip()
                        if not title or not permalink:
                            continue
                        prices = item.get("prices") if isinstance(item.get("prices"), dict) else {}
                        minor = int(prices.get("currency_minor_unit") or 2)
                        div = 10 ** minor if minor >= 0 else 1
                        raw_p = prices.get("price") or ""
                        raw_reg = prices.get("regular_price") or ""
                        price = f"{int(raw_p) / div:.2f}" if str(raw_p).isdigit() else str(raw_p)
                        compare = f"{int(raw_reg) / div:.2f}" if str(raw_reg).isdigit() else str(raw_reg)
                        discount = _calc_discount(price, compare)
                        currency = str(prices.get("currency_code") or "")
                        rating_raw = item.get("average_rating")
                        try:
                            rating = round(float(rating_raw), 1) if rating_raw and float(rating_raw) > 0 else None
                        except (ValueError, TypeError):
                            rating = None
                        rev_cnt = int(item.get("review_count") or 0)
                        raw_desc = str(item.get("short_description") or "") + "\n" + str(item.get("description") or "")
                        desc, bullets = _extract_bullets_from_html(raw_desc)
                        imgs = []
                        for im in item.get("images") or []:
                            src = im.get("src") if isinstance(im, dict) else ""
                            if src and src not in imgs:
                                imgs.append(src)
                        videos = _extract_videos_from_html(raw_desc, base)
                        out.append({
                            "store_name": name,
                            "platform": "woocommerce",
                            "external_url": permalink,
                            "title": title,
                            "price": price,
                            "compare_price": compare if discount > 0 else "",
                            "currency": currency,
                            "discount_pct": discount,
                            "rating": rating,
                            "reviews_count": rev_cnt,
                            "best_seller_rank": rank,
                            "benefits": bullets[:4],
                            "description": desc,
                            "images": upgrade_and_dedupe_product_images(imgs)[:8],
                            "videos": videos,
                        })
                    if out:
                        return out
        except Exception:
            continue

    # HTML fallback for WooCommerce
    search_url = f"{base}/?post_type=product&orderby=popularity" + (f"&s={quote_plus(query)}" if query else "")
    return _scout_html_catalog(search_url, base, name, "woocommerce", limit)


# ------------------------------------------------------------------ Platform 3: Nuvemshop
def scout_nuvemshop_store(store_url: str, store_name: str = "", query: str = "", limit: int = 12) -> list[dict]:
    """Fetch best-selling products from a Nuvemshop / Tiendanube store."""
    base = _base_url(store_url)
    name = store_name or urlparse(base).netloc.removeprefix("www.")
    candidates = (
        [f"{base}/search/?q={quote_plus(query)}"] if query else []
    ) + [
        f"{base}/produtos/?sort_by=best-selling",
        f"{base}/productos/?sort_by=best-selling",
        base,
    ]
    for url in candidates:
        items = _scout_html_catalog(url, base, name, "nuvemshop", limit)
        if items:
            return items
    return []


def _scout_html_catalog(catalog_url: str, base: str, store_name: str, platform: str, limit: int) -> list[dict]:
    try:
        r = http().get(catalog_url, timeout=20, headers={"Accept": "text/html,application/xhtml+xml"})
        if r.status_code >= 400:
            return []
        page = r.text
    except Exception:
        return []

    links: list[str] = []
    for m in re.finditer(r'href=["\']([^"\'#?]+)["\']', page, re.I):
        href = html.unescape(m.group(1)).strip()
        full = urljoin(base, href)
        if not full.startswith(base):
            continue
        path = urlparse(full).path.lower()
        if re.search(r"/(?:produtos?|products?|item|p)/[\w-]+/?$", path) and not re.search(
            r"/(?:categoria|category|collections?|cart|account|login|page)/", path
        ):
            if full not in links:
                links.append(full)

    out: list[dict] = []
    for rank, link in enumerate(links[:limit], 1):
        try:
            item = scout_product_url(link, store_name=store_name, platform=platform, rank=rank)
            if item:
                out.append(item)
        except Exception:
            continue
    return out


def scout_shopee_product(url: str, store_name: str = "", rank: int | None = None,
                         use_browser: bool = True) -> dict | None:
    """Extract product metadata, full image gallery and HD demo videos from a Shopee product page URL.

    Combines fast SSR/crawler metadata extraction with an optional Playwright network intercept
    to capture the seller's original .mp4 video stream and 800x800+ catalog images.
    """
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        return None
    base = _base_url(url)
    name = store_name or "Shopee"

    headers = {
        "User-Agent": "WhatsApp/2.21.12.21 A",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    title = ""
    desc = ""
    images: list[str] = []
    videos: list[str] = []

    # 1. Fast Meta extraction via SSR/crawler headers
    try:
        r = http().get(url, headers=headers, timeout=20)
        if r.status_code == 200:
            html_text = r.text
            m_title = re.search(r'<meta[^>]+property=[\"\']og:title[\"\'][^>]+content=[\"\']([^\"\']+)[\"\']', html_text, re.I)
            if m_title:
                title = re.sub(r"\s*\|\s*Shopee.*$", "", m_title.group(1), flags=re.I).strip()
            m_desc = re.search(r'<meta[^>]+property=[\"\']og:description[\"\'][^>]+content=[\"\']([^\"\']+)[\"\']', html_text, re.I)
            if m_desc:
                desc = re.sub(r"^Compre [^!]+!\s*", "", m_desc.group(1), flags=re.I).strip()
            m_img = re.search(r'<meta[^>]+property=[\"\']og:image[\"\'][^>]+content=[\"\']([^\"\']+)[\"\']', html_text, re.I)
            if m_img:
                images.append(m_img.group(1).strip())
    except Exception as e:
        log.warning("Shopee SSR crawler request failed: %s", e)

    # 2. Deep Scout via Playwright (intercepts gallery images & video .mp4)
    if use_browser:
        try:
            from playwright.sync_api import sync_playwright
            import os
            chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            launch_kwargs = {"headless": True}
            if os.path.exists(chrome_path):
                launch_kwargs["executable_path"] = chrome_path

            with sync_playwright() as p:
                browser = p.chromium.launch(**launch_kwargs)
                page = browser.new_page(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    locale="pt-BR"
                )

                def on_response(res):
                    u = res.url
                    if "susercontent.com/file/" in u:
                        clean_img = re.sub(r"@resize[^\s]+", "", u).split("_tn")[0]
                        if clean_img not in images and not any(x in clean_img for x in ("icon", "avatar", "logo")):
                            images.append(clean_img)
                    elif any(ext in u for ext in (".mp4", ".m3u8", "cv.shopee.com", "vod.susercontent.com")):
                        if u not in videos:
                            videos.append(u)

                page.on("response", on_response)
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(3500)

                if not title:
                    t = page.title()
                    title = re.sub(r"\s*\|\s*Shopee.*$", "", t, flags=re.I).strip()

                browser.close()
        except Exception as e:
            log.info("Shopee Playwright media intercept skipped or failed: %s", e)

    if not title and not desc:
        return None

    # Bullets extraction from description
    bullets = []
    for line in desc.splitlines():
        clean_ln = line.strip(" •-–*✔🚗🛞⚙️🔋🔦📦📏\t\r")
        if 8 <= len(clean_ln) <= 180 and not clean_ln.startswith("#"):
            bullets.append(clean_ln)
            if len(bullets) >= 4:
                break

    return {
        "store_name": name,
        "platform": "shopee",
        "external_url": url,
        "title": title[:160],
        "price": "",
        "compare_price": "",
        "currency": "BRL",
        "discount_pct": 0,
        "rating": None,
        "reviews_count": 0,
        "best_seller_rank": rank,
        "benefits": bullets[:4],
        "description": desc[:1200],
        "images": upgrade_and_dedupe_product_images(images)[:8],
        "videos": videos[:4],
    }


def scout_product_url(url: str, store_name: str = "", platform: str = "", rank: int | None = None,
                      use_browser: bool = True) -> dict | None:
    """Extract a full product record from a single product page URL (Shopify .json or HTML JSON-LD/OpenGraph)."""
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        return None
    base = _base_url(url)
    name = store_name or urlparse(base).netloc.removeprefix("www.")

    # Try Shopee dedicated scraper with crawler + Playwright video/image interception
    if "shopee." in url.lower():
        shopee_item = scout_shopee_product(url, store_name=name, rank=rank, use_browser=use_browser)
        if shopee_item:
            return shopee_item

    # Try Shopify single-product JSON endpoint first if URL contains /products/<handle>
    m_shop = re.search(r"^(https?://[^/]+/products/[^/?#]+)", url, re.I)
    if m_shop:
        try:
            rj = http().get(m_shop.group(1) + ".json", timeout=15, headers={"Accept": "application/json"})
            if rj.status_code == 200 and isinstance(rj.json().get("product"), dict):
                prod = rj.json()["product"]
                title = _strip_html(str(prod.get("title") or "")).strip()
                body_html = str(prod.get("body_html") or "")
                variants = prod.get("variants") or []
                v0 = variants[0] if variants and isinstance(variants[0], dict) else {}
                price = str(v0.get("price") or "").strip()
                compare = str(v0.get("compare_at_price") or "").strip()
                discount = _calc_discount(price, compare)
                imgs = [str(im.get("src") or "").strip()
                        for im in (prod.get("images") or []) if isinstance(im, dict) and im.get("src")]
                desc, bullets = _extract_bullets_from_html(body_html)
                videos = _extract_videos_from_html(body_html, base)
                return {
                    "store_name": name,
                    "platform": "shopify",
                    "external_url": m_shop.group(1),
                    "title": title,
                    "price": price,
                    "compare_price": compare if discount > 0 else "",
                    "currency": "",
                    "discount_pct": discount,
                    "rating": None,
                    "reviews_count": 0,
                    "best_seller_rank": rank,
                    "benefits": bullets[:4],
                    "description": desc,
                    "images": upgrade_and_dedupe_product_images(imgs)[:8],
                    "videos": videos,
                }
        except Exception:
            pass

    r = http().get(url, timeout=25, headers={"Accept": "text/html,application/xhtml+xml"})
    raise_for_status(r, f"fetch product {url[:60]}")
    page = r.text
    plat = platform or detect_platform(url, page)

    ext = _TextExtractor()
    ext.feed(page)
    ld_products: list[dict] = []
    for raw in ext.json_ld:
        try:
            ld_products.extend(_find_ld_products(json.loads(raw)))
        except Exception:
            continue

    prod_res = extract_product(page, url)
    title = prod_res[0] if prod_res else (ext.meta_title or ext.title).strip()
    ctx = prod_res[1] if prod_res else "\n".join(ext.parts[:8])
    imgs = prod_res[2] if prod_res else []
    if not title and not ctx:
        return None

    price, compare, currency = "", "", ""
    rating = None
    rev_cnt = 0
    if ld_products:
        lp = _select_main_product(ld_products, title)
        offers = lp.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            price = str(offers.get("price") or offers.get("lowPrice") or "").strip()
            compare = str(offers.get("highPrice") or "").strip()
            currency = str(offers.get("priceCurrency") or "").strip()
        agg = lp.get("aggregateRating") if isinstance(lp.get("aggregateRating"), dict) else {}
        try:
            if agg.get("ratingValue"):
                rating = round(float(agg["ratingValue"]), 1)
            if agg.get("reviewCount") or agg.get("ratingCount"):
                rev_cnt = int(agg.get("reviewCount") or agg.get("ratingCount") or 0)
        except (ValueError, TypeError):
            pass
        if not imgs:
            imgs = _ld_images(lp.get("image"))

    if not price:
        price = (ext.meta.get("product:price:amount") or ext.meta.get("og:price:amount") or [""])[0]
        currency = (ext.meta.get("product:price:currency") or ext.meta.get("og:price:currency") or [""])[0]

    discount = _calc_discount(price, compare)
    bullets = [b for b in ext.bullets if 10 <= len(b) <= 180][:4]
    if plat in {"nuvemshop", "woocommerce"}:
        imgs.extend(_product_gallery_images(page, url))
    imgs = upgrade_and_dedupe_product_images(imgs)
    videos = _extract_videos_from_html(page, base)
    return {
        "store_name": name,
        "platform": plat,
        "external_url": url,
        "title": title[:160],
        "price": price,
        "compare_price": compare if discount > 0 else "",
        "currency": currency,
        "discount_pct": discount,
        "rating": rating,
        "reviews_count": rev_cnt,
        "best_seller_rank": rank,
        "benefits": bullets,
        "description": ctx[:1200],
        "images": imgs[:8],
        "videos": videos,
    }


def search_products_web(query: str, platform: str = "", limit: int = 8) -> list[dict]:
    """Search the web for product pages on Shopify, Nuvemshop or WooCommerce matching ``query``."""
    q = (query or "").strip()
    if not q:
        return []
    plat_filter = {
        "shopify": 'inurl:/products/ "Shopify"',
        "nuvemshop": 'inurl:/produtos/ "Nuvemshop"',
        "woocommerce": '(inurl:/product/ OR inurl:/produto/) "WooCommerce"',
    }.get(platform, '(inurl:/products/ OR inurl:/produtos/ OR inurl:/product/)')
    search_q = f"{q} {plat_filter}"
    urls: list[str] = []
    try:
        r = http().get("https://html.duckduckgo.com/html/", params={"q": search_q}, timeout=20,
                       headers={"Accept": "text/html"})
        if r.status_code == 200:
            for m in re.finditer(r'uddg=([^&"\'>]+)', r.text):
                u = unquote(m.group(1)).strip()
                if re.match(r"^https?://", u) and re.search(r"/(?:products?|produtos?)/[\w-]+", u, re.I):
                    clean_u = u.split("?")[0]
                    if clean_u not in urls:
                        urls.append(clean_u)
    except Exception as e:
        log.warning("Web product search failed: %s", e)

    out: list[dict] = []
    for u in urls[:limit]:
        try:
            item = scout_product_url(u, platform=platform)
            if item:
                out.append(item)
        except Exception:
            continue
    return out


# ------------------------------------------------------------------ AI Viral Dossier
def _heuristic_insights(item: dict) -> dict:
    title = item.get("title") or "Product"
    words = re.split(r"[\s|–—,-]+", title)
    short_name = " ".join(w for w in words if w)[:34].strip() or title[:30]
    rank = item.get("best_seller_rank")
    discount = int(item.get("discount_pct") or 0)
    rev = int(item.get("reviews_count") or 0)
    base_score = 72
    if rank and rank <= 3:
        base_score += 14
    elif rank and rank <= 10:
        base_score += 8
    if discount >= 25:
        base_score += 5
    if rev >= 50:
        base_score += 5
    if item.get("videos"):
        base_score += 4
    score = max(45, min(96, base_score))
    benefits = item.get("benefits") or []
    pain = benefits[0] if benefits else (item.get("description") or title)[:110]
    return {
        "short_name": short_name,
        "viral_score": score,
        "pain_point": pain[:140],
        "hook_idea": f"Olha como {short_name} resolve isso em segundos.",
        "visual_angle": f"Close-up mostrando {short_name} em uso prático resolvendo o problema.",
        "benefits": benefits[:3] or [title],
    }


def analyze_products_with_ai(llm, items: list[dict], settings: Settings | None = None, *, language: str = "") -> list[dict]:
    """Enrich scouted products with Viral Score (0-100), Pain Point, 2s Hook, Visual Angle and Short Name."""
    if not items:
        return []
    # Always populate defaults first so every item is complete even if LLM is offline or skips one
    for it in items:
        defaults = _heuristic_insights(it)
        for k, v in defaults.items():
            if not it.get(k):
                it[k] = v

    if llm is None:
        return items

    raw_lang = language or (settings.language if settings else "pt")
    lang = LANGUAGES.get(raw_lang, raw_lang)
    for start in range(0, len(items), 10):
        batch = items[start:start + 10]
        payload = [
            {
                "index": idx,
                "title": b.get("title", ""),
                "store": b.get("store_name", ""),
                "platform": b.get("platform", ""),
                "best_seller_rank": b.get("best_seller_rank"),
                "price": f"{b.get('currency', '')} {b.get('price', '')}".strip(),
                "discount_pct": b.get("discount_pct", 0),
                "rating": b.get("rating"),
                "reviews_count": b.get("reviews_count", 0),
                "videos_count": len(b.get("videos") or []),
                "images_count": len(b.get("images") or []),
                "image_files": [urlparse(str(url)).path.rsplit("/", 1)[-1]
                                for url in (b.get("images") or [])[:8]],
                "benefits": (b.get("benefits") or [])[:4],
                "description": (b.get("description") or "")[:500],
            }
            for idx, b in enumerate(batch)
        ]
        system = (
            "You are an expert e-commerce & YouTube Shorts / TikTok viral product researcher. "
            "You analyze products and prepare high-converting video creative briefs. "
            "Reply with a single JSON object and nothing else."
        )
        user = f"""Analyze these {len(batch)} e-commerce products and write all text fields in **{lang}**.

Products:
{json.dumps(payload, ensure_ascii=False, indent=1)}

For each product (keep the exact `index`), return:
- "short_name": a punchy 2-4 word product name in {lang} suitable for a top-of-screen video badge (e.g. "Protetor de Tomada", "Escova Alisadora Térmica").
- "viral_score": integer 0-100 rating how well this product can perform in a viral Short (weight: best-seller rank / reviews / discount + how relatable the daily problem is + how visually demonstrable the before/after is).
- "pain_point": 1 short sentence in {lang} naming the exact everyday frustration or problem this product solves.
- "hook_idea": 1 scroll-stopping 2-second opening hook line in {lang} (max 14 words) that starts directly with the pain point or visual surprise.
- "visual_angle": 1 concrete sentence in {lang} describing the best close-up demonstration shot for the video.
- "benefits": array of up to 3 concrete factual specs/benefits in {lang} taken strictly from the product data above (do not invent specifications)."""
        try:
            if hasattr(llm, "complete_json"):
                resp = llm.complete_json(system, user, ANALYSIS_SCHEMA, max_tokens=3500)
            else:
                resp = llm.generate_json(user, system=system)
            for row in (resp.get("products") or []):
                idx = row.get("index")
                if isinstance(idx, int):
                    target = batch[idx] if 0 <= idx < len(batch) else (batch[idx - 1] if 1 <= idx <= len(batch) else None)
                    if target is None:
                        continue
                    if row.get("short_name"):
                        target["short_name"] = str(row["short_name"]).strip()[:48]
                    if row.get("viral_score") is not None:
                        try:
                            target["viral_score"] = max(0, min(100, int(row["viral_score"])))
                        except (ValueError, TypeError):
                            pass
                    for field in ("pain_point", "hook_idea", "visual_angle"):
                        if row.get(field):
                            target[field] = str(row[field]).strip()[:240]
                    if isinstance(row.get("benefits"), list) and row["benefits"]:
                        target["benefits"] = [str(x).strip()[:160] for x in row["benefits"] if str(x).strip()][:4]
        except Exception as e:
            log.warning("AI product analysis fell back to heuristics: %s", e)
    return items


# ------------------------------------------------------------------ Scout orchestration & Topic builder
def run_scout(history: History, settings: Settings, llm=None, *, mode: str = "stores",
              store_id: int | None = None, query: str = "", platform: str = "",
              url: str = "", limit: int = 8, progress=None) -> list[dict]:
    """Scout products from stores, web search, or a direct URL, enrich with AI, and save to SQLite."""
    from . import usage
    with usage.operation(history, "scout", query or url or "Product research") as run:
        items = _run_scout(history, settings, llm, mode=mode, store_id=store_id, query=query,
                           platform=platform, url=url, limit=limit, progress=progress)
        run.safe(run.store.allocate_products, run.id, items)
        return items


def _run_scout(history: History, settings: Settings, llm=None, *, mode: str = "stores",
               store_id: int | None = None, query: str = "", platform: str = "",
               url: str = "", limit: int = 8, progress=None) -> list[dict]:
    from . import usage
    history.ensure_default_stores(DEFAULT_STORES)
    collected: list[dict] = []

    if mode == "url" and url.strip():
        u = url.strip()
        if progress:
            progress("topic", 15, f"Scouting {u[:50]}…")
        if re.search(r"/(?:products?|produtos?|item|p)/", u, re.I):
            item = scout_product_url(u, platform=platform)
            if item:
                collected.append(item)
        else:
            plat = platform or detect_platform(u)
            fn = {"shopify": scout_shopify_store, "woocommerce": scout_woocommerce_store,
                  "nuvemshop": scout_nuvemshop_store}.get(plat, scout_shopify_store)
            collected.extend(fn(u, query=query, limit=limit))
    elif mode in ("web", "search") and query.strip():
        if progress:
            progress("topic", 20, f"Searching stores for '{query}'…")
        # Search both registered stores and web
        for st in history.list_stores():
            if platform and st["platform"] != platform:
                continue
            fn = {"shopify": scout_shopify_store, "woocommerce": scout_woocommerce_store,
                  "nuvemshop": scout_nuvemshop_store}.get(st["platform"], scout_shopify_store)
            collected.extend(fn(st["url"], st["name"], query=query, limit=max(2, limit // 2)))
        if len(collected) < limit:
            collected.extend(search_products_web(query, platform=platform, limit=limit - len(collected)))
    else:
        stores = history.list_stores()
        if store_id:
            stores = [s for s in stores if s["id"] == int(store_id)]
        elif platform:
            stores = [s for s in stores if s["platform"] == platform]
        per_store = limit if len(stores) <= 1 else max(2, math.ceil(limit / len(stores)))
        for idx, st in enumerate(stores):
            if progress:
                pct = 10 + int(45 * idx / max(1, len(stores)))
                progress("topic", pct, f"Scouting best-sellers from {st['name']}…")
            fn = {"shopify": scout_shopify_store, "woocommerce": scout_woocommerce_store,
                  "nuvemshop": scout_nuvemshop_store}.get(st["platform"], scout_shopify_store)
            found = fn(st["url"], st["name"], query=query, limit=per_store)
            for f in found:
                f["store_id"] = st["id"]
            if found:
                history.touch_store(st["id"])
                collected.extend(found)

    # Deduplicate by external_url and cap at limit
    deduped: list[dict] = []
    seen_urls: set[str] = set()
    for item in collected:
        ext = str(item.get("external_url") or item.get("url") or "").strip()
        if ext and ext not in seen_urls:
            seen_urls.add(ext)
            deduped.append(item)
    collected = deduped[:limit]
    if not collected:
        return []

    if progress:
        progress("script", 65, f"Analyzing {len(collected)} products with AI…")
    usage.step("product-analysis")
    analyze_products_with_ai(llm, collected, settings)

    saved_ids: list[int] = []
    for item in collected:
        pid = history.upsert_product(item)
        saved_ids.append(pid)
    if progress:
        progress("done", 100, f"Scouted {len(saved_ids)} products")
    return history.get_products(saved_ids)


def format_product_links(products: list[dict], custom_links: list[str] | None = None) -> list[str]:
    """Build ordered affiliate link lines (`Produto: link`) for the video description."""
    if custom_links:
        cleaned = [str(ln).strip() for ln in custom_links if str(ln).strip()]
        if cleaned:
            return cleaned
    lines: list[str] = []
    for idx, p in enumerate(products, 1):
        name = (p.get("short_name") or p.get("title") or f"Produto {idx}").strip()
        link = (p.get("affiliate_url") or p.get("external_url") or p.get("url") or "").strip()
        if not link:
            continue
        lines.append(f"{name}: {link}")
    return lines


def build_scene_media_for_products(products: list[dict], scenes: list, timeline: list,
                                   offline: bool = False) -> list[list]:
    """Map each scene in `timeline` to the specific product it presents and return ordered MediaItems per scene."""
    from .media import MediaItem
    if offline or not products or not timeline:
        return []
    pools: list[list[MediaItem]] = []
    names: list[set[str]] = []
    for p_idx, p in enumerate(products):
        catalog = _product_media_catalog(p)
        counts = {"video": 0, "image": 0}
        pool = []
        for media_index, (url, meta) in enumerate(catalog):
            kind = meta["kind"]
            media_id = f"p{p_idx}{'vid' if kind == 'video' else 'img'}{counts[kind]:02d}"
            counts[kind] += 1
            pool.append(MediaItem("product-page", media_id, kind, url=url,
                                  extra={**meta, "media_index": media_index}))
        pools.append(pool)
        words = set(re.findall(
            r"\w{3,}", f"{p.get('short_name') or ''} {p.get('title') or ''}".lower()
        ))
        names.append(words)

    counts = [0] * len(products)
    last_media: dict[int, str] = {}
    out: list[list[MediaItem]] = []
    for t_idx, st in enumerate(timeline):
        sc = scenes[st.index] if st.index < len(scenes) else scenes[-1]
        label = (getattr(sc, "product", "") or "").strip()
        chosen: int | None = None
        if len(products) == 1:
            chosen = 0
        else:
            m_num = re.match(r"^#?(\d+)[\.\)\s:-]", label)
            if m_num:
                idx_num = int(m_num.group(1)) - 1
                if 0 <= idx_num < len(products):
                    chosen = idx_num
            if chosen is None and label:
                l_words = set(re.findall(r"\w{3,}", label.lower()))
                best_overlap, best_i = 0, None
                for p_i, wset in enumerate(names):
                    ov = len(l_words & wset)
                    if ov > best_overlap:
                        best_overlap, best_i = ov, p_i
                if best_i is not None:
                    chosen = best_i
            if chosen is None:
                chosen = min(len(products) - 1, int(t_idx * len(products) / max(1, len(timeline))))
        pool = pools[chosen]
        if pool:
            scene_number = counts[chosen]
            requested = getattr(sc, "media_index", -1)
            selected = next((item for item in pool if item.extra["media_index"] == requested), None)
            if selected and (selected.extra["role"] == "spec" and t_idx < 2):
                selected = None
            if selected and selected.key == last_media.get(chosen) and len(pool) > 1:
                # Avoid freezing on the exact same static media across consecutive scenes
                selected = None
            if selected is None:
                narration = getattr(sc, "narration", "") or ""
                specs = bool(re.search(r"\b\d+(?:[.,]\d+)?\s*(?:cm|mm|ml|watts?|w|litros?)\b|material|medida", narration, re.I))
                if scene_number == 0:
                    roles = {"demo": 0, "hero": 1, "detail": 2, "spec": 3}
                elif specs:
                    roles = {"spec": 0, "detail": 1, "demo": 2, "hero": 3}
                else:
                    roles = {"demo": 0, "detail": 1, "hero": 2, "spec": 3}
                ordered = sorted(pool, key=lambda item: roles.get(item.extra["role"], 4))
                if len(pool) > 1 and t_idx < 2:
                    non_specs = [item for item in ordered if item.extra["role"] != "spec"]
                    ordered = non_specs + [item for item in ordered if item.extra["role"] == "spec"]
                eligible = [item for item in ordered if item.key != last_media.get(chosen)] or ordered
                best_rank = min(roles.get(item.extra["role"], 4) for item in eligible)
                preferred = [item for item in eligible if roles.get(item.extra["role"], 4) == best_rank]
                selected = preferred[max(0, scene_number - 1) % len(preferred)]
            start = pool.index(selected)
            counts[chosen] += 1
            last_media[chosen] = selected.key
            rotated = pool[start:] + pool[:start]
            focused = replace(selected, extra={**selected.extra, "focus_x": getattr(sc, "focus_x", 0.5),
                                               "focus_y": getattr(sc, "focus_y", 0.5)})
            out.append([focused] + [item for item in rotated if item.key != selected.key])
        else:
            out.append([])
    return out


def build_product_topic(products: list[dict], custom_links: list[str] | None = None) -> Topic:
    """Turn 1 scouted product (deep-dive) or 2-5 scouted products (compiled showcase) into a rich Topic."""
    if not products:
        raise ValueError("No products selected")

    images: list[str] = []
    videos: list[str] = []
    blocks: list[str] = ["DOSSIÊ VERIFICADO DE PRODUTOS VIRAIS:"]
    links = format_product_links(products, custom_links)
    pids = [int(p["id"]) for p in products if str(p.get("id") or "").isdigit()]

    if len(products) == 1:
        p = products[0]
        name = (p.get("short_name") or p.get("title") or "Product").strip()
        subject = f"{p.get('title') or name}"
        price = f"{p.get('currency', '')} {p.get('price', '')}".strip()
        header = " · ".join(x for x in [
            f"Product: {p.get('title')}",
            f"Badge name: {name}",
            f"Store: {p.get('store_name')}" if p.get("store_name") else "",
            f"Best-seller rank: #{p['best_seller_rank']}" if p.get("best_seller_rank") else "",
            f"Price: {price}" if price else "",
            f"Discount: {p['discount_pct']}% OFF" if p.get("discount_pct") else "",
            f"Rating: {p['rating']}/5 ({p.get('reviews_count', 0)} reviews)" if p.get("rating") else "",
        ] if x)
        blocks.append(header)
        if p.get("pain_point"):
            blocks.append(f"Problem / Pain point it solves: {p['pain_point']}")
        if p.get("hook_idea"):
            blocks.append(f"Suggested 2s Hook: {p['hook_idea']}")
        if p.get("visual_angle"):
            blocks.append(f"Visual demonstration angle: {p['visual_angle']}")
        blocks.append(_media_context(p))
        if p.get("benefits"):
            blocks.append("Verified features & specs:\n" + "\n".join(f"- {b}" for b in p["benefits"]))
        if p.get("description"):
            blocks.append(f"Product details:\n{p['description'][:1200]}")
        catalog = _product_media_catalog(p)
        videos.extend(url for url, meta in catalog if meta["kind"] == "video")
        images.extend(url for url, meta in catalog if meta["kind"] == "image")
    else:
        names = [p.get("short_name") or p.get("title") or f"Product {i}" for i, p in enumerate(products, 1)]
        subject = f"{len(products)} viral products: " + ", ".join(names[:5])
        blocks.append(
            f"Compiled showcase of {len(products)} products. Present them in this EXACT numbered order "
            "using the numbered badge names below:"
        )
        # Interleave up to 2 images per product in order so Visuals uses each product's photos in turn
        for idx, p in enumerate(products, 1):
            short = (p.get("short_name") or p.get("title") or f"Product {idx}").strip()
            short = re.sub(r"^\d+[\.\)]\s*", "", short)
            badge = f"{idx}. {short}"
            price = f"{p.get('currency', '')} {p.get('price', '')}".strip()
            lines = [f"### {badge} ({p.get('title', short)})"]
            lines.append(_media_context(p, image_limit=4))
            if price or p.get("best_seller_rank"):
                meta = " · ".join(x for x in [
                    f"Best-seller #{p['best_seller_rank']}" if p.get("best_seller_rank") else "",
                    f"Price: {price}" if price else "",
                    f"Discount: {p['discount_pct']}% OFF" if p.get("discount_pct") else "",
                ] if x)
                lines.append(meta)
            if p.get("pain_point"):
                lines.append(f"- Pain point it solves: {p['pain_point']}")
            if p.get("hook_idea"):
                lines.append(f"- Angle / Hook idea: {p['hook_idea']}")
            if p.get("visual_angle"):
                lines.append(f"- Visual shot: {p['visual_angle']}")
            for b in (p.get("benefits") or [])[:3]:
                lines.append(f"- Verified spec: {b}")
            if p.get("description"):
                lines.append(f"- Details: {p['description'][:400]}")
            blocks.append("\n".join(lines))
            catalog = _product_media_catalog(p, image_limit=4)
            for v, meta in catalog:
                if meta["kind"] != "video":
                    continue
                if v not in videos:
                    videos.append(v)
            for im, meta in catalog:
                if meta["kind"] != "image":
                    continue
                if im not in images:
                    images.append(im)

    key = "products:" + ",".join(str(p.get("id") or p.get("external_url")) for p in products)
    return Topic(
        subject=subject[:200],
        source="products",
        key=key,
        context="\n\n".join(blocks)[:6000],
        style="product",
        images=images[:20],
        videos=videos[:20],
        product_links=links,
        product_ids=pids,
    )
