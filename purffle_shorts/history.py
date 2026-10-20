"""SQLite history: every video made, what was uploaded or scheduled, which stock clips and topics
were used (so nothing repeats), today's upload count (YouTube quota), the idea queue filled by the
planner, and view counts for the videos that are live."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    subject TEXT, source TEXT, topic TEXT, style TEXT, language TEXT,
    title TEXT, description TEXT, tags TEXT,
    folder TEXT, video_path TEXT, duration REAL,
    llm TEXT, voice TEXT,
    status TEXT NOT NULL,          -- rendered | queued | uploaded | scheduled | failed
    youtube_id TEXT, publish_at TEXT, uploaded_at TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS media_used (key TEXT PRIMARY KEY, used_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS topics_used (key TEXT PRIMARY KEY, used_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS upload_attempts (
    video_id INTEGER PRIMARY KEY, token TEXT NOT NULL, state TEXT NOT NULL,
    owner_pid INTEGER, started_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    publish_at TEXT, youtube_id TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    subject TEXT NOT NULL,
    style TEXT, notes TEXT,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | used
    used_at TEXT, video_id INTEGER
);
CREATE TABLE IF NOT EXISTS product_stores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    platform TEXT NOT NULL DEFAULT 'shopify', -- shopify | nuvemshop | woocommerce
    niche TEXT DEFAULT '',
    last_scouted_at TEXT
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    store_id INTEGER,
    store_name TEXT DEFAULT '',
    platform TEXT NOT NULL DEFAULT 'shopify',
    external_url TEXT NOT NULL UNIQUE,
    affiliate_url TEXT DEFAULT '',
    title TEXT NOT NULL,
    short_name TEXT DEFAULT '',
    price TEXT DEFAULT '',
    compare_price TEXT DEFAULT '',
    currency TEXT DEFAULT '',
    discount_pct INTEGER DEFAULT 0,
    rating REAL,
    reviews_count INTEGER DEFAULT 0,
    best_seller_rank INTEGER,
    viral_score INTEGER,
    pain_point TEXT DEFAULT '',
    hook_idea TEXT DEFAULT '',
    visual_angle TEXT DEFAULT '',
    benefits_json TEXT DEFAULT '[]',
    description TEXT DEFAULT '',
    images_json TEXT DEFAULT '[]',
    videos_json TEXT DEFAULT '[]',
    starred INTEGER NOT NULL DEFAULT 0,
    video_id INTEGER
);
"""

# Columns added after 2.0; existing databases get them on open.
VIDEO_COLUMNS = {
    "score": "INTEGER",            # Script Doctor retention score, 0-100
    "parent_id": "INTEGER",        # the original video when this one is a translated copy
    "views": "INTEGER", "likes": "INTEGER", "comments": "INTEGER", "stats_at": "TEXT",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class History:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._db() as c:
            from .usage import SCHEMA as USAGE_SCHEMA
            c.executescript(SCHEMA)
            c.executescript(USAGE_SCHEMA)
            c.execute("BEGIN IMMEDIATE")
            usage_columns = {r["name"] for r in c.execute("PRAGMA table_info(usage_runs)")}
            if "owner_pid" not in usage_columns:
                c.execute("ALTER TABLE usage_runs ADD COLUMN owner_pid INTEGER")
            have = {r["name"] for r in c.execute("PRAGMA table_info(videos)")}
            for col, kind in VIDEO_COLUMNS.items():
                if col not in have:
                    c.execute(f"ALTER TABLE videos ADD COLUMN {col} {kind}")

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(self.path, timeout=30)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _exec(self, sql: str, args: tuple = ()) -> int:
        with self._db() as c:
            return c.execute(sql, args).lastrowid or 0

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._db() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    # -- videos --
    def add_video(self, **fields) -> int:
        fields.setdefault("created_at", now_iso())
        if isinstance(fields.get("tags"), list):
            fields["tags"] = json.dumps(fields["tags"])
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        return self._exec(f"INSERT INTO videos ({cols}) VALUES ({marks})", tuple(fields.values()))

    def update_video(self, vid: int, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE videos SET {sets} WHERE id = ?", (*fields.values(), vid))

    def get(self, vid: int) -> dict | None:
        rows = self._all("SELECT * FROM videos WHERE id = ?", (vid,))
        return rows[0] if rows else None

    def recent(self, limit: int = 20) -> list[dict]:
        return self._all("SELECT * FROM videos ORDER BY id DESC LIMIT ?", (limit,))

    def delete_video(self, vid: int) -> None:
        self._exec("DELETE FROM videos WHERE id = ?", (vid,))

    def recent_titles(self, limit: int = 40) -> list[str]:
        return [r["title"] for r in self._all(
            "SELECT title FROM videos WHERE title IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,))]

    def pending_uploads(self, statuses: tuple[str, ...] = ("queued",)) -> list[dict]:
        """queued = deferred by the daily quota; rendered = made with --no-upload."""
        marks = ", ".join("?" for _ in statuses)
        return self._all(f"SELECT * FROM videos WHERE status IN ({marks}) AND video_path IS NOT NULL ORDER BY id",
                         statuses)

    def uploads_since(self, since_iso: str) -> int:
        return self._all("SELECT (SELECT COUNT(*) FROM videos WHERE uploaded_at>=?) + "
                         "(SELECT COUNT(*) FROM upload_attempts WHERE started_at>=? "
                         "AND state IN ('reserved','uploading','unknown')) AS n", (since_iso, since_iso))[0]["n"]

    def scheduled_times(self) -> list[str]:
        return [r["publish_at"] for r in self._all(
            "SELECT publish_at FROM videos WHERE publish_at IS NOT NULL AND status = 'scheduled'")]

    def upload_attempt(self, video_id: int) -> dict | None:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._recover_uploads(db)
            row = db.execute("SELECT * FROM upload_attempts WHERE video_id=?", (video_id,)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def _recover_uploads(db) -> None:
        for attempt in db.execute("SELECT * FROM upload_attempts WHERE state IN ('reserved','uploading')").fetchall():
            try:
                if attempt["owner_pid"] is not None:
                    os.kill(attempt["owner_pid"], 0)
                    continue
            except ProcessLookupError:
                pass
            except PermissionError:
                continue
            uncertain = attempt["state"] == "uploading"
            error = "Upload outcome is unknown. Check YouTube before retrying." if uncertain else None
            db.execute("UPDATE upload_attempts SET state=?,updated_at=?,error=? WHERE video_id=?",
                       ("unknown" if uncertain else "failed", now_iso(), error, attempt["video_id"]))
            db.execute("UPDATE videos SET status=?,error=? WHERE id=? AND youtube_id IS NULL",
                       ("upload-unknown" if uncertain else "queued", error, attempt["video_id"]))

    def reserve_upload(self, video_id: int, settings, day_start: str, refused: bool = False) -> dict:
        """Reserve the video, quota and publication slot atomically across processes."""
        from . import youtube
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._recover_uploads(db)
            rec = db.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
            if not rec:
                return {"status": "missing", "error": "Video not found"}
            if rec["youtube_id"]:
                return {**dict(rec), "status": "scheduled" if rec["publish_at"] else "uploaded"}
            attempt = db.execute("SELECT * FROM upload_attempts WHERE video_id=?", (video_id,)).fetchone()
            if attempt and attempt["state"] in ("reserved", "uploading", "unknown"):
                state = "upload-unknown" if attempt["state"] == "unknown" else "uploading"
                message = ("Upload outcome is unknown. Check YouTube and resolve this attempt before retrying."
                           if state == "upload-unknown" else "This video already has an upload in progress.")
                if state == "upload-unknown":
                    db.execute("UPDATE videos SET status=?,error=? WHERE id=?", (state, message, video_id))
                return {"status": state, "error": message}
            if not rec["video_path"] or not Path(rec["video_path"]).is_file():
                return {"status": "missing", "error": "The local video file is missing"}
            uploaded = db.execute("SELECT COUNT(*) FROM videos WHERE uploaded_at>=?", (day_start,)).fetchone()[0]
            reserved = db.execute("SELECT COUNT(*) FROM upload_attempts WHERE started_at>=? "
                                  "AND state IN ('reserved','uploading','unknown')", (day_start,)).fetchone()[0]
            if refused or uploaded + reserved >= settings.daily_upload_limit:
                db.execute("UPDATE videos SET status='queued',error=NULL WHERE id=?", (video_id,))
                return {"status": "queued", "title": rec["title"], "error": "Daily upload limit reached"}
            taken = [r[0] for r in db.execute(
                "SELECT publish_at FROM videos WHERE status='scheduled' AND publish_at IS NOT NULL "
                "UNION SELECT publish_at FROM upload_attempts "
                "WHERE state IN ('reserved','uploading','unknown') AND publish_at IS NOT NULL")]
            publish = youtube.next_publish_slot(settings, taken)
            stamp, token = now_iso(), uuid.uuid4().hex
            publish_iso = youtube.to_rfc3339(publish) if publish else None
            db.execute("INSERT OR REPLACE INTO upload_attempts "
                       "(video_id,token,state,owner_pid,started_at,updated_at,publish_at) "
                       "VALUES (?,?,'reserved',?,?,?,?)",
                       (video_id, token, os.getpid(), stamp, stamp, publish_iso))
            return {"status": "reserved", "token": token, "publish": publish, "record": dict(rec)}

    def start_upload(self, video_id: int, token: str) -> None:
        with self._db() as db:
            changed = db.execute("UPDATE upload_attempts SET state='uploading',updated_at=? "
                                 "WHERE video_id=? AND token=? AND state='reserved'",
                                 (now_iso(), video_id, token)).rowcount
            if not changed:
                raise ValueError("The upload reservation is no longer active")

    def finish_upload(self, video_id: int, token: str, state: str, **fields) -> None:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE upload_attempts SET state=?,updated_at=?,youtube_id=?,error=? "
                                 "WHERE video_id=? AND token=?", (state, now_iso(), fields.get("youtube_id"),
                                                                 fields.get("error"), video_id, token)).rowcount
            if not changed:
                raise ValueError("The upload reservation no longer exists")
            if fields:
                sets = ",".join(f"{k}=?" for k in fields)
                db.execute(f"UPDATE videos SET {sets} WHERE id=?", (*fields.values(), video_id))

    def resolve_upload(self, video_id: int, *, youtube_id: str = "", not_uploaded: bool = False) -> str:
        """Record the user's check of an uncertain remote outcome; never starts an upload."""
        import re
        if bool(youtube_id) == bool(not_uploaded):
            raise ValueError("Provide a YouTube video ID or confirm that no upload exists")
        if youtube_id and not re.fullmatch(r"[A-Za-z0-9_-]{6,128}", youtube_id):
            raise ValueError("Enter the YouTube video ID, not its URL")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._recover_uploads(db)
            rec = db.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
            attempt = db.execute("SELECT * FROM upload_attempts WHERE video_id=?", (video_id,)).fetchone()
            if not rec or not attempt or attempt["state"] != "unknown":
                raise ValueError("Only an upload with an unknown outcome can be resolved")
            if youtube_id:
                other = db.execute("SELECT id FROM videos WHERE youtube_id=? AND id<>?",
                                   (youtube_id, video_id)).fetchone()
                if other:
                    raise ValueError("That YouTube video is already linked to another record")
                status = "scheduled" if attempt["publish_at"] else "uploaded"
                db.execute("UPDATE videos SET status=?,youtube_id=?,publish_at=?,uploaded_at=?,error=NULL WHERE id=?",
                           (status, youtube_id, attempt["publish_at"], attempt["started_at"], video_id))
            else:
                status = "rendered"
                db.execute("UPDATE videos SET status=?,publish_at=NULL,error=NULL WHERE id=?", (status, video_id))
            db.execute("UPDATE upload_attempts SET state=?,youtube_id=?,updated_at=?,error=NULL WHERE video_id=?",
                       ("done" if youtube_id else "failed", youtube_id or None, now_iso(), video_id))
            return status

    def stats(self) -> dict:
        rows = self._all("SELECT status, COUNT(*) AS n FROM videos GROUP BY status")
        return {r["status"]: r["n"] for r in rows}

    # -- channel performance --
    def live_video_ids(self, limit: int = 500) -> list[str]:
        return [r["youtube_id"] for r in self._all(
            "SELECT youtube_id FROM videos WHERE youtube_id IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,))]

    def set_stats(self, youtube_id: str, views: int, likes: int, comments: int) -> None:
        self._exec("UPDATE videos SET views = ?, likes = ?, comments = ?, stats_at = ? WHERE youtube_id = ?",
                   (views, likes, comments, now_iso(), youtube_id))

    def performers(self, n: int = 5, *, best: bool = True, min_age_hours: int = 48) -> list[dict]:
        """Most (or least) viewed videos that have been public long enough for the numbers to mean something."""
        cutoff = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - min_age_hours * 3600,
                                        timezone.utc).isoformat(timespec="seconds")
        order = "DESC" if best else "ASC"
        return self._all(
            "SELECT id, title, style, views, likes, comments FROM videos WHERE views IS NOT NULL "
            f"AND COALESCE(publish_at, uploaded_at) <= ? ORDER BY views {order} LIMIT ?", (cutoff, n))

    # -- idea queue (planner) --
    def add_idea(self, subject: str, style: str = "", notes: str = "") -> int:
        return self._exec("INSERT INTO ideas (created_at, subject, style, notes) VALUES (?, ?, ?, ?)",
                          (now_iso(), subject.strip(), style or None, notes or None))

    def ideas(self, status: str | None = "pending", limit: int = 200) -> list[dict]:
        if status:
            return self._all("SELECT * FROM ideas WHERE status = ? ORDER BY id LIMIT ?", (status, limit))
        return self._all("SELECT * FROM ideas ORDER BY id DESC LIMIT ?", (limit,))

    def claim_idea(self, idea_id: int | None = None) -> dict | None:
        """Take the oldest pending idea (atomically, so parallel workers never get the same one)."""
        with self._db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM ideas WHERE status = 'pending'"
                            + (" AND id = ?" if idea_id is not None else "") + " ORDER BY id LIMIT 1",
                            (idea_id,) if idea_id is not None else ()).fetchone()
            if not row:
                return None
            c.execute("UPDATE ideas SET status = 'used', used_at = ? WHERE id = ?", (now_iso(), row["id"]))
            return dict(row)

    def link_idea(self, idea_id: int, video_id: int) -> None:
        self._exec("UPDATE ideas SET video_id = ? WHERE id = ?", (video_id, idea_id))

    def release_idea(self, idea_id: int) -> None:
        """Put an idea back in the queue after its video failed."""
        self._exec("UPDATE ideas SET status = 'pending', used_at = NULL WHERE id = ? AND video_id IS NULL", (idea_id,))

    def delete_idea(self, idea_id: int) -> None:
        self._exec("DELETE FROM ideas WHERE id = ?", (idea_id,))

    # -- de-duplication --
    def used_media(self) -> set[str]:
        return {r["key"] for r in self._all("SELECT key FROM media_used")}

    def mark_media(self, keys: list[str]) -> None:
        ts = now_iso()
        with self._db() as c:
            c.executemany("INSERT OR IGNORE INTO media_used (key, used_at) VALUES (?, ?)", [(k, ts) for k in keys])

    def topic_used(self, key: str) -> bool:
        return bool(self._all("SELECT 1 FROM topics_used WHERE key = ?", (key.lower(),)))

    def mark_topic(self, key: str) -> None:
        self._exec("INSERT OR IGNORE INTO topics_used (key, used_at) VALUES (?, ?)", (key.lower(), now_iso()))

    # -- product scouting & stores --
    def ensure_default_stores(self, defaults: list[dict]) -> list[dict]:
        with self._db() as c:
            n = c.execute("SELECT COUNT(*) AS n FROM product_stores").fetchone()["n"]
            if n == 0 and defaults:
                ts = now_iso()
                c.executemany(
                    "INSERT OR IGNORE INTO product_stores (created_at, name, url, platform, niche) VALUES (?, ?, ?, ?, ?)",
                    [(ts, d["name"], d["url"], d.get("platform", "shopify"), d.get("niche", "")) for d in defaults],
                )
        return self.list_stores()

    def list_stores(self) -> list[dict]:
        return self._all("SELECT * FROM product_stores ORDER BY id")

    def add_store(self, name: str, url: str, platform: str = "shopify", niche: str = "") -> int:
        url = url.strip().rstrip("/")
        with self._db() as c:
            row = c.execute("SELECT id FROM product_stores WHERE url = ?", (url,)).fetchone()
            if row:
                c.execute("UPDATE product_stores SET name = ?, platform = ?, niche = ? WHERE id = ?",
                          (name.strip(), platform, niche.strip(), row["id"]))
                return int(row["id"])
            return c.execute(
                "INSERT INTO product_stores (created_at, name, url, platform, niche) VALUES (?, ?, ?, ?, ?)",
                (now_iso(), name.strip(), url, platform, niche.strip()),
            ).lastrowid or 0

    def touch_store(self, store_id: int) -> None:
        self._exec("UPDATE product_stores SET last_scouted_at = ? WHERE id = ?", (now_iso(), store_id))

    def delete_store(self, store_id: int) -> None:
        self._exec("DELETE FROM product_stores WHERE id = ?", (store_id,))

    def _unpack_product(self, row: dict) -> dict:
        d = dict(row)
        for col, key in (("benefits_json", "benefits"), ("images_json", "images"), ("videos_json", "videos")):
            try:
                d[key] = json.loads(d.pop(col, "[]") or "[]")
            except Exception:
                d[key] = []
        d["starred"] = bool(d.get("starred"))
        d["url"] = d.get("external_url") or ""
        return d

    def upsert_product(self, data: dict | None = None, **fields) -> int:
        if isinstance(data, dict):
            fields = {**data, **fields}
        if "url" in fields and not fields.get("external_url"):
            fields["external_url"] = fields.pop("url")
        else:
            fields.pop("url", None)
        ext_url = str(fields.get("external_url") or "").strip()
        if not ext_url:
            raise ValueError("external_url is required")
        fields["external_url"] = ext_url
        now = now_iso()
        for key, col in (("benefits", "benefits_json"), ("images", "images_json"), ("videos", "videos_json")):
            if key in fields:
                val = fields.pop(key)
                fields[col] = json.dumps(val if isinstance(val, list) else [], ensure_ascii=False)
        with self._db() as c:
            existing = c.execute("SELECT * FROM products WHERE external_url = ?", (ext_url,)).fetchone()
            if existing:
                pid = int(existing["id"])
                updates = {"updated_at": now}
                for k, v in fields.items():
                    if k in ("id", "created_at", "external_url"):
                        continue
                    # Preserve user-entered affiliate_url and existing AI insights if re-scouting without them
                    if k == "affiliate_url" and not v and existing["affiliate_url"]:
                        continue
                    if k in ("viral_score", "pain_point", "hook_idea", "visual_angle", "short_name") and not v and existing[k]:
                        continue
                    updates[k] = v
                sets = ", ".join(f"{k} = ?" for k in updates)
                c.execute(f"UPDATE products SET {sets} WHERE id = ?", (*updates.values(), pid))
                return pid
            fields.setdefault("created_at", now)
            fields["updated_at"] = now
            cols = ", ".join(fields)
            marks = ", ".join("?" for _ in fields)
            return c.execute(f"INSERT INTO products ({cols}) VALUES ({marks})", tuple(fields.values())).lastrowid or 0

    def list_products(self, *, platform: str = "", store_id: int | None = None, q: str = "",
                      sort: str = "viral_score", starred_only: bool = False, limit: int = 200) -> list[dict]:
        where, args = ["1=1"], []
        if platform:
            where.append("platform = ?")
            args.append(platform)
        if store_id:
            where.append("store_id = ?")
            args.append(int(store_id))
        if starred_only:
            where.append("starred = 1")
        if q:
            like = f"%{q.lower()}%"
            where.append("(LOWER(title) LIKE ? OR LOWER(short_name) LIKE ? OR LOWER(pain_point) LIKE ? "
                         "OR LOWER(description) LIKE ? OR LOWER(store_name) LIKE ?)")
            args.extend([like] * 5)
        order = {
            "viral": "COALESCE(viral_score, -1) DESC, COALESCE(best_seller_rank, 9999) ASC, id DESC",
            "viral_score": "COALESCE(viral_score, -1) DESC, COALESCE(best_seller_rank, 9999) ASC, id DESC",
            "rank": "COALESCE(best_seller_rank, 9999) ASC, COALESCE(viral_score, -1) DESC, id DESC",
            "best_seller": "COALESCE(best_seller_rank, 9999) ASC, COALESCE(viral_score, -1) DESC, id DESC",
            "discount": "COALESCE(discount_pct, 0) DESC, COALESCE(viral_score, -1) DESC, id DESC",
            "recent": "updated_at DESC, id DESC",
        }.get(sort, "COALESCE(viral_score, -1) DESC, id DESC")
        sql = f"SELECT * FROM products WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?"
        args.append(limit)
        return [self._unpack_product(r) for r in self._all(sql, tuple(args))]

    def get_products(self, ids: list[int]) -> list[dict]:
        clean = [int(i) for i in ids if str(i).isdigit() or isinstance(i, int)]
        if not clean:
            return []
        marks = ", ".join("?" for _ in clean)
        rows = {r["id"]: self._unpack_product(r)
                for r in self._all(f"SELECT * FROM products WHERE id IN ({marks})", tuple(clean))}
        return [rows[i] for i in clean if i in rows]

    def set_product_affiliate(self, pid: int, affiliate_url: str) -> bool:
        with self._db() as db:
            return bool(db.execute("UPDATE products SET affiliate_url=?,updated_at=? WHERE id=?",
                                   (affiliate_url.strip(), now_iso(), int(pid))).rowcount)

    def toggle_product_star(self, pid: int) -> bool:
        with self._db() as c:
            row = c.execute("SELECT starred FROM products WHERE id = ?", (int(pid),)).fetchone()
            if not row:
                return False
            new_val = 0 if row["starred"] else 1
            c.execute("UPDATE products SET starred = ? WHERE id = ?", (new_val, int(pid)))
            return bool(new_val)

    def link_products_video(self, pids: list[int], video_id: int) -> None:
        for pid in pids:
            self._exec("UPDATE products SET video_id = ? WHERE id = ?", (int(video_id), int(pid)))

    def delete_product(self, pid: int) -> None:
        self._exec("DELETE FROM products WHERE id = ?", (int(pid),))

