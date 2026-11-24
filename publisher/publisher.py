#!/usr/bin/env python3
"""Local video publishing queue. Run: python publisher.py --help"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time as time_module
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
os.chdir(BASE)
load_dotenv(BASE / ".env")

import backends  # noqa: E402

STATE = BASE / "state"
DATABASE = STATE / "publisher.sqlite3"
LOCKFILE = STATE / "publisher.lock"
TARGETS = ("facebook", "youtube", "tiktok")
STREAMS = ("short", "long")
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def config_timezone() -> ZoneInfo:
    return ZoneInfo(os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh"))


def localnow() -> datetime:
    return datetime.now(config_timezone())


def video_dir() -> Path:
    value = os.getenv("VIDEO_DIR")
    if not value:
        raise backends.PreflightError("Set VIDEO_DIR in .env")
    return Path(value).expanduser().resolve()


def long_video_dir() -> Path | None:
    # V3 name first; V2 path remains supported without moving video files.
    value = (os.getenv("FULL_VIDEO_DIR", "").strip() or
             os.getenv("YT_LONG_VIDEO_DIR", "").strip())
    return Path(value).expanduser().resolve() if value else None


@contextmanager
def exclusive_lock():
    import fcntl

    LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCKFILE.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def db() -> sqlite3.Connection:
    class ClosingConnection(sqlite3.Connection):
        def __exit__(self, exc_type, exc, tb):
            try:
                return super().__exit__(exc_type, exc, tb)
            finally:
                self.close()

    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATABASE, factory=ClosingConnection)
    con.row_factory = sqlite3.Row
    con.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS videos (
          id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
          path TEXT NOT NULL, title_hint TEXT NOT NULL, created_at TEXT NOT NULL,
          kind TEXT NOT NULL DEFAULT 'short', file_size INTEGER, mtime_ns INTEGER,
          stale INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS dispatches (
          id INTEGER PRIMARY KEY, slot_key TEXT NOT NULL UNIQUE, video_id INTEGER NOT NULL UNIQUE,
          day TEXT NOT NULL, caption_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
          created_at TEXT NOT NULL, FOREIGN KEY(video_id) REFERENCES videos(id)
        );
        CREATE TABLE IF NOT EXISTS posts (
          dispatch_id INTEGER NOT NULL, platform TEXT NOT NULL,
          status TEXT NOT NULL, remote_id TEXT, error TEXT, updated_at TEXT NOT NULL,
          PRIMARY KEY(dispatch_id,platform), FOREIGN KEY(dispatch_id) REFERENCES dispatches(id)
        );
    """)
    # Preserve existing queued posts and fingerprints when upgrading from the shorts-only MVP.
    current = {row[1] for row in con.execute("PRAGMA table_info(videos)")}
    for column, definition in (
        ("kind", "TEXT NOT NULL DEFAULT 'short'"),
        ("file_size", "INTEGER"), ("mtime_ns", "INTEGER"),
        ("stale", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if column not in current:
            con.execute(f"ALTER TABLE videos ADD COLUMN {column} {definition}")
    post_columns = {row[1] for row in con.execute("PRAGMA table_info(posts)")}
    for column, definition in (("upload_session", "TEXT"), ("upload_offset", "INTEGER NOT NULL DEFAULT 0")):
        if column not in post_columns:
            con.execute(f"ALTER TABLE posts ADD COLUMN {column} {definition}")
    con.commit()
    return con


def file_fingerprint(file: Path) -> str:
    digest = sha256()
    with file.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_metadata(video: Path) -> dict:
    sidecar = video.with_suffix(".json")
    return json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}


def probe(video: Path) -> dict:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-show_entries", "format=duration",
        "-of", "json", str(video),
    ], check=True, capture_output=True, text=True, timeout=30)
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    seconds = float(data["format"]["duration"])
    return {"width": stream["width"], "height": stream["height"], "duration_seconds": seconds}


def validate(video: Path, kind: str = "short") -> dict:
    if video.suffix.lower() != ".mp4":
        raise ValueError("MVP requires .mp4 (H.264/AAC recommended)")
    p = probe(video)
    duration, width, height = p["duration_seconds"], p["width"], p["height"]
    if kind == "short":
        if not 4 <= duration <= 60:
            raise ValueError("Use 4–60 seconds for shared short-form posts")
        if width < 540 or height < 960 or abs(width / height - 9 / 16) > 0.035:
            raise ValueError("Use vertical 9:16 short video, at least 540×960")
    elif kind == "long":
        if not 4 <= duration <= 12 * 3600 or min(width, height) < 360:
            raise ValueError("YouTube long videos must be 4 seconds–12 hours, at least 360p")
        # Square/vertical videos <= 3 min are treated as Shorts by YouTube.
        if duration <= 180 and width <= height:
            raise ValueError("Square/vertical videos up to 3 minutes are Shorts; use >3 min or landscape")
    else:
        raise ValueError(f"Unknown stream: {kind}")
    return p


def scan(con: sqlite3.Connection) -> int:
    folders = [("short", video_dir())]
    long_folder = long_video_dir()
    if long_folder:
        if long_folder == folders[0][1]:
            raise ValueError("FULL_VIDEO_DIR / YT_LONG_VIDEO_DIR must differ from VIDEO_DIR")
        folders.append(("long", long_folder))
    minimum_age = int(os.getenv("MIN_FILE_AGE_SECONDS", "60"))
    manifest = configured_manifest()
    found = 0
    for kind, folder in folders:
        folder.mkdir(parents=True, exist_ok=True)
        for video in sorted(folder.glob("*.mp4")):
            stat = video.stat()
            if time_module.time() - stat.st_mtime < minimum_age:
                continue
            # Avoid re-hashing multi-GB unchanged episodes on every 5-minute tick.
            latest = con.execute("SELECT file_size,mtime_ns FROM videos WHERE path=? AND kind=? "
                                 "AND stale=0 ORDER BY id DESC LIMIT 1", (str(video), kind)).fetchone()
            if latest and latest["file_size"] == stat.st_size and latest["mtime_ns"] == stat.st_mtime_ns:
                continue
            try:
                if manifest is not None:
                    if video.name not in manifest:
                        raise ValueError("missing manifest entry")
                    validate_manifest_entry(manifest[video.name], kind, video.name)
                validate(video, kind)
                fingerprint = file_fingerprint(video)
            except (ValueError, OSError, subprocess.SubprocessError, KeyError, IndexError) as exc:
                print(f"SKIP {kind}/{video.name}: {exc}")
                continue
            # A replaced file receives a new queue entry; the old fingerprint
            # remains for historical records but can no longer block dispatch.
            con.execute("UPDATE videos SET stale=1 WHERE path=? AND fingerprint<>?",
                        (str(video), fingerprint))
            con.execute("UPDATE videos SET file_size=?,mtime_ns=? WHERE fingerprint=? AND path=?",
                        (stat.st_size, stat.st_mtime_ns, fingerprint, str(video)))
            before = con.total_changes
            con.execute("INSERT OR IGNORE INTO videos(fingerprint,path,title_hint,created_at,kind,file_size,mtime_ns) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (fingerprint, str(video), video.stem, localnow().isoformat(), kind,
                         stat.st_size, stat.st_mtime_ns))
            found += con.total_changes - before
    con.commit()
    print(f"SCAN: {found} new eligible video(s)")
    return found


def extract_frames(video: Path, seconds: float) -> list[bytes]:
    frames = []
    for position in (min(1, seconds / 6), seconds / 2, seconds * 0.85):
        task = subprocess.run([
            "ffmpeg", "-nostdin", "-loglevel", "error", "-ss", str(position),
            "-i", str(video), "-frames:v", "1", "-vf", "scale=360:-2",
            "-f", "image2pipe", "-vcodec", "mjpeg", "-",
        ], capture_output=True, timeout=30, check=True)
        if task.stdout:
            frames.append(task.stdout)
    return frames


def make_caption(video: Path, details: dict, kind: str = "short") -> dict:
    """Only selected keyframes, filename, local sidecar and optional transcript go to AI."""
    extra = video.with_suffix(".txt")
    context = extra.read_text(encoding="utf-8")[:10000] if extra.exists() else ""
    hint = re.sub(r"[_-]+", " ", video.stem).strip()
    metadata = read_metadata(video)
    if kind == "long" and any(k in metadata for k in ("youtube_title", "youtube_description")):
        title, description = metadata.get("youtube_title"), metadata.get("youtube_description")
        if not isinstance(title, str) or not title.strip() or not isinstance(description, str) or not description.strip():
            raise ValueError("Full-episode .json needs nonempty youtube_title and youtube_description")
        fb_desc = metadata.get("facebook_description", description)
        fb_title = metadata.get("facebook_title", title)
        if not isinstance(fb_desc, str) or not fb_desc.strip() or not isinstance(fb_title, str) or not fb_title.strip():
            raise ValueError("facebook_title/facebook_description must be nonempty strings if present")
        return {"title": title.strip()[:100], "youtube": description.strip()[:5000],
                "facebook_title": fb_title.strip()[:255], "facebook": fb_desc.strip()[:60000]}
    if os.getenv("OPENAI_API_KEY", "").strip():
        from openai import OpenAI

        instruction = (
            "You are a Vietnamese full-episode publishing editor. Write one accurate title and separate "
            "Facebook and YouTube descriptions based ONLY on the frames, filename and supplied transcript/context. "
            "Do not fabricate scenes, claims or chapter timestamps. Output ONLY valid JSON strings: "
            "title,youtube,facebook. Keep title <=95 characters and YouTube description <=5000 characters. "
            "Do not add #Shorts to full episodes."
        ) if kind == "long" else (
            "You are a Vietnamese short-video publishing editor. Create platform-specific "
            "titles/captions based ONLY on these 3 frames, the filename and context. "
            "Don't invent claims or unseen dialogue. Output ONLY valid JSON with strings: "
            "title,facebook,tiktok,youtube. Keep title <=95 chars. "
            "Use 2-4 relevant hashtags in each caption, no unrelated engagement bait. "
        )
        content = [{"type": "input_text", "text": instruction + f" Filename: {hint}. Context/transcript: {context}."}]
        for image in extract_frames(video, details["duration_seconds"]):
            content.append({"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(image).decode()})
        answer = OpenAI().responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            input=[{"role": "user", "content": content}],
        ).output_text.strip()
        answer = re.sub(r"^```(?:json)?\s*|\s*```$", "", answer)
        captions = json.loads(answer)
        expected = ("title", "facebook", "youtube") if kind == "long" else ("title", "facebook", "tiktok", "youtube")
        if not isinstance(captions, dict) or not all(isinstance(captions.get(k), str) and captions[k].strip() for k in expected):
            raise ValueError("AI returned incomplete caption JSON; dispatch was not created")
        captions["title"] = captions["title"][:95]
        captions["youtube"] = captions["youtube"][:5000]
        if kind == "long":
            captions["facebook_title"] = captions["title"]
            captions["facebook"] = captions["facebook"][:60000]
        return captions
    title = (context.splitlines()[0] if context.strip() else hint)[:95]
    if kind == "long":
        description = (context.strip() or title)
        return {"title": title, "youtube": description[:5000], "facebook": description[:60000],
                "facebook_title": title}
    return {"title": title, "facebook": title, "tiktok": title, "youtube": title + " #Shorts"}


def long_setting(new_key: str, old_key: str, default: str) -> str:
    """Prefer V3 config but keep existing V2 .env configuration working."""
    return os.getenv(new_key, "").strip() or os.getenv(old_key, default).strip()


def slots(kind: str = "short") -> list[str]:
    if kind not in STREAMS:
        raise ValueError(f"Unknown stream: {kind}")
    key, default = ("POST_TIMES", "09:00") if kind == "short" else ("FULL_POST_TIMES", "")
    configured = (os.getenv(key, default) if kind == "short"
                  else long_setting("FULL_POST_TIMES", "YT_LONG_POST_TIMES", ""))
    values = [v.strip() for v in configured.split(",") if v.strip()]
    if len(values) != len(set(values)):
        raise ValueError(f"{key} contains duplicate times")
    for value in values:
        time.fromisoformat(value)
    if len(values) > 5:
        raise ValueError(f"Keep {key} to 1–5 slots per day")
    return sorted(values)


def platforms(kind: str = "short") -> list[str]:
    if kind == "long":
        result = [p.strip() for p in os.getenv("FULL_PLATFORMS", "youtube").split(",") if p.strip()]
        if not result or len(result) != len(set(result)) or not set(result) <= {"youtube", "facebook"}:
            raise ValueError("FULL_PLATFORMS must contain facebook and/or youtube, without duplicates")
        return result
    if kind != "short":
        raise ValueError(f"Unknown stream: {kind}")
    result = [p.strip() for p in os.getenv("PLATFORMS", "facebook,youtube").split(",") if p.strip()]
    if not result or len(set(result)) != len(result) or not set(result) <= set(TARGETS):
        raise ValueError(f"PLATFORMS must be distinct members of {TARGETS}")
    return result


def validate_manifest_entry(entry: dict, kind: str, filename: str) -> dict:
    media_filename = entry.get("media_filename") if isinstance(entry, dict) else None
    if (not isinstance(entry, dict) or entry.get("kind") != kind or media_filename != filename
            or not isinstance(media_filename, str) or Path(media_filename).name != media_filename):
        raise ValueError(f"Manifest stream or media filename mismatch for {filename}")
    if not isinstance(entry.get("episode_id"), str) or not entry["episode_id"].strip():
        raise ValueError(f"Manifest entry for {filename} needs episode_id")
    targets = entry.get("allowed_targets")
    allowed = {"facebook", "youtube"} if kind == "long" else set(TARGETS)
    if not isinstance(targets, list) or not targets or len(targets) != len(set(targets)) or not set(targets) <= allowed:
        raise ValueError(f"Manifest allowed_targets invalid for {filename}")
    platform_metadata = entry.get("platform_metadata")
    if not isinstance(platform_metadata, dict) or set(platform_metadata) != set(targets) or any(
            not isinstance(platform_metadata[target], dict) or not platform_metadata[target] for target in targets):
        raise ValueError(f"Manifest platform_metadata must define metadata for every allowed target of {filename}")
    for target, fields in platform_metadata.items():
        for key in ("title", "description"):
            if key in fields and (not isinstance(fields[key], str) or not fields[key].strip()):
                raise ValueError(f"Manifest {target}.{key} must be a nonempty string")
        if target == "youtube":
            category = fields.get("category_id", fields.get("categoryId"))
            if category is not None and not str(category).isdigit():
                raise ValueError("Manifest youtube category_id must be numeric")
            audience = fields.get("made_for_kids", fields.get("selfDeclaredMadeForKids"))
            if audience is not None and not isinstance(audience, bool):
                raise ValueError("Manifest YouTube audience field must be true or false")
    return entry


def configured_manifest() -> dict[str, dict] | None:
    value = os.getenv("PUBLISH_MANIFEST", "").strip()
    if not value:
        return None
    raw = json.loads(Path(value).expanduser().read_text(encoding="utf-8"))
    entries = raw.get("videos") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        raise ValueError("Manifest must be a JSON object with a videos array")
    result = {}
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("media_filename"), str):
            raise ValueError("Every manifest item needs media_filename")
        filename = item["media_filename"]
        if filename in result:
            raise ValueError(f"Duplicate manifest media_filename: {filename}")
        result[filename] = item
    return result


def long_post_days() -> set[int]:
    value = long_setting("FULL_POST_DAYS", "YT_LONG_POST_DAYS", "")
    if not value:
        return set(range(7))
    days = [part.strip().lower() for part in value.split(",")]
    if any(day not in WEEKDAYS for day in days) or len(days) != len(set(days)):
        raise ValueError("FULL_POST_DAYS / YT_LONG_POST_DAYS must use distinct mon,tue,wed,thu,fri,sat,sun")
    return {WEEKDAYS[day] for day in days}


def due(now: datetime, kind: str = "short") -> list[str]:
    if kind == "long" and now.weekday() not in long_post_days():
        return []
    grace = timedelta(minutes=int(os.getenv("MISSED_SLOT_GRACE_MINUTES", "25")))
    result = []
    for slot in slots(kind):
        t = time.fromisoformat(slot)
        scheduled = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if scheduled <= now < scheduled + grace:
            result.append(slot)
    return result


def create_dispatch(con: sqlite3.Connection, key: str, now: datetime, kind: str = "short"):
    if kind not in STREAMS:
        raise ValueError(f"Unknown stream: {kind}")
    today = now.date().isoformat()
    if con.execute("SELECT id FROM dispatches WHERE slot_key=?", (key,)).fetchone():
        return
    cap_text = (os.getenv("MAX_DAILY_POSTS", "3") if kind == "short" else
                long_setting("FULL_MAX_DAILY_POSTS", "YT_LONG_MAX_DAILY_POSTS", "1"))
    cap = min(5, max(1, int(cap_text)))
    if con.execute("SELECT COUNT(*) FROM dispatches d JOIN videos v ON d.video_id=v.id "
                   "WHERE d.day=? AND v.kind=?", (today, kind)).fetchone()[0] >= cap:
        print(f"Daily cap reached for {kind}: {cap}")
        return
    video = con.execute("""
        SELECT v.* FROM videos v WHERE v.kind=? AND v.stale=0 AND NOT EXISTS
        (SELECT 1 FROM dispatches d WHERE d.video_id=v.id)
        ORDER BY v.id LIMIT 1
    """, (kind,)).fetchone()
    if not video:
        print(f"No queued {kind} video for {key}")
        return
    path = Path(video["path"])
    if not path.exists() or file_fingerprint(path) != video["fingerprint"]:
        print(f"Video missing/modified; won't publish: {path}")
        return
    info = validate(path, kind)
    metadata = read_metadata(path)
    manifest = configured_manifest()
    if manifest is not None:
        if path.name not in manifest:
            raise ValueError(f"No manifest entry for {path.name}")
        entry = validate_manifest_entry(manifest[path.name], kind, path.name)
        if set(entry["allowed_targets"]) != set(platforms(kind)):
            raise ValueError(f"Manifest targets do not match configured platforms for {path.name}")
        metadata["episode_id"] = entry["episode_id"]
        metadata["allowed_targets"] = entry["allowed_targets"]
        metadata["manifest_platform_metadata"] = entry["platform_metadata"]
    metadata["duration_seconds"] = info["duration_seconds"]
    captions = make_caption(path, info, kind)
    con.execute("INSERT INTO dispatches(slot_key,video_id,day,caption_json,metadata_json,created_at) VALUES (?,?,?,?,?,?)",
                (key, video["id"], today, json.dumps(captions, ensure_ascii=False),
                 json.dumps(metadata, ensure_ascii=False), now.isoformat()))
    dispatch_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    for platform in platforms(kind):
        con.execute("INSERT INTO posts(dispatch_id,platform,status,updated_at) VALUES (?,?,?,?)",
                    (dispatch_id, platform, "queued", now.isoformat()))
    con.commit()
    print(f"DISPATCH {dispatch_id}: {kind}/{path.name}, scheduled {key}")


def post_update(con: sqlite3.Connection, dispatch_id: int, platform: str,
                status: str, remote_id: str | None = None, error: str | None = None):
    con.execute("UPDATE posts SET status=?,remote_id=COALESCE(?,remote_id),error=?,updated_at=? "
                "WHERE dispatch_id=? AND platform=?",
                (status, remote_id, error, localnow().isoformat(), dispatch_id, platform))
    con.commit()


def save_facebook_upload(con: sqlite3.Connection, dispatch_id: int, session_id: str,
                         offset: int, video_id: str | None = None):
    con.execute("UPDATE posts SET upload_session=?,upload_offset=?,remote_id=COALESCE(?,remote_id),updated_at=? "
                "WHERE dispatch_id=? AND platform='facebook'",
                (session_id, offset, video_id, localnow().isoformat(), dispatch_id))
    con.commit()


def redact_error(error: Exception) -> str:
    message = f"{type(error).__name__}: {error}"
    return re.sub(r"(?i)(access_token|upload_token|token|client_secret)=([^&#\s]+)",
                  r"\1=[REDACTED]", message)[:600]


def send_notice(message: str):
    print(message)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        try:
            import requests
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat_id, "text": message[:4000]}, timeout=10).raise_for_status()
        except Exception as exc:
            print(f"Telegram notification failed: {exc}")


def publish_pending(con: sqlite3.Connection, kind: str | None = None):
    rows = con.execute("""
        SELECT p.*,d.caption_json,d.metadata_json,v.path,v.fingerprint,v.kind FROM posts p
        JOIN dispatches d ON p.dispatch_id=d.id JOIN videos v ON d.video_id=v.id
        WHERE p.status IN ('queued','blocked') AND (? IS NULL OR v.kind=?)
        ORDER BY p.dispatch_id,p.platform
    """, (kind, kind)).fetchall()
    for p in rows:
        platform, path = p["platform"], Path(p["path"])
        caption, metadata = json.loads(p["caption_json"]), json.loads(p["metadata_json"])
        # User can supply consent/settings to a previously blocked TikTok job.
        try:
            metadata.update(read_metadata(path))
        except (ValueError, OSError) as exc:
            post_update(con, p["dispatch_id"], platform, "blocked", error=f"Invalid video metadata: {exc}")
            continue
        metadata["duration_seconds"] = json.loads(p["metadata_json"])["duration_seconds"]
        try:
            if not path.exists() or file_fingerprint(path) != p["fingerprint"]:
                raise backends.PreflightError("Video changed or disappeared after being queued")
            if platform == "facebook":
                backends.required("FB_PAGE_ID")
                backends.required("FB_PAGE_ACCESS_TOKEN")
                if os.getenv("FB_ALLOW_PUBLIC_POSTING", "false").lower() != "true":
                    raise backends.PreflightError("Set FB_ALLOW_PUBLIC_POSTING=true to allow public Facebook Page posts")
                # Keep the original Page Reels endpoint for highlights; send full episodes
                # through the Page Videos endpoint. Meta may display all videos as Reels.
                if p["kind"] == "long":
                    backends.facebook_video_preflight(path, metadata.get("duration_seconds"))
                    callback = lambda: backends.facebook_video_publish(path, caption, metadata,
                        {"session_id": p["upload_session"], "offset": p["upload_offset"], "video_id": p["remote_id"]},
                        lambda session, offset, video_id=None: save_facebook_upload(
                            con, p["dispatch_id"], session, offset, video_id))
                else:
                    callback = lambda: backends.facebook_publish(path, caption)
            elif platform == "youtube":
                # This makes sure token refresh works before publishing starts.
                backends.youtube_client()
                callback = lambda: backends.youtube_publish(path, caption, kind=p["kind"], metadata=metadata)
            else:
                mode = os.getenv("TIKTOK_MODE", "off").lower()
                if mode == "api":
                    backends.required("TIKTOK_ACCESS_TOKEN")
                    if metadata.get("tiktok_consent") is not True:
                        raise backends.PreflightError("No explicit per-video TikTok approval (.json sidecar)")
                    if os.getenv("TIKTOK_APP_APPROVED", "false").lower() != "true":
                        raise backends.PreflightError("TikTok app not audited/approved")
                    callback = lambda: backends.tiktok_api_publish(path, caption, metadata)
                elif mode == "adb":
                    from tiktok_adb import publish as adb_publish
                    from tiktok_adb import validate_macro
                    validate_macro()
                    callback = lambda: adb_publish(path, caption["tiktok"])
                else:
                    raise backends.PreflightError("TIKTOK_MODE is off; choose API or calibrated ADB")
        except backends.PreflightError as exc:
            post_update(con, p["dispatch_id"], platform, "blocked", error=str(exc))
            print(f"BLOCKED {platform}: {exc}")
            continue
        # Facebook Page Video transfer errors may resume a known checkpoint;
        # all other ambiguous remote failures remain manual to avoid duplicates.
        post_update(con, p["dispatch_id"], platform, "inflight")
        try:
            status, remote = callback()
            post_update(con, p["dispatch_id"], platform, status, remote_id=remote)
            send_notice(f"{platform}: {status} | {path.name} | remote={remote}")
        except Exception as exc:
            message = redact_error(exc)
            # A known Page Videos session with an acknowledged checkpoint before EOF
            # can safely retry from that exact offset on the next scheduler tick.
            durable = con.execute("SELECT upload_session,upload_offset FROM posts "
                                   "WHERE dispatch_id=? AND platform=?",
                                   (p["dispatch_id"], platform)).fetchone()
            saved_session = durable["upload_session"] if durable else None
            saved_offset = durable["upload_offset"] if durable else -1
            safe_fb_resume = (platform == "facebook" and p["kind"] == "long"
                              and saved_session and 0 <= saved_offset < path.stat().st_size
                              and isinstance(exc, backends.TRANSFER_RETRY_ERRORS))
            if safe_fb_resume:
                post_update(con, p["dispatch_id"], platform, "queued", error=message)
                send_notice(f"RETRY QUEUED facebook: {path.name} — resume saved upload session")
            else:
                post_update(con, p["dispatch_id"], platform, "needs_check", error=message)
                send_notice(f"CHECK MANUALLY {platform}: {path.name} — {message}")


def quarantine_interrupted_uploads(con: sqlite3.Connection):
    # Resume only a known Page Video session with bytes remaining. A session at EOF
    # may have completed FINISH remotely, so it must be reconciled manually.
    columns = {row[1] for row in con.execute("PRAGMA table_info(posts)")}
    if {"platform", "upload_session", "upload_offset", "dispatch_id"} <= columns:
        con.execute("""
            UPDATE posts SET status='queued',error=NULL,updated_at=?
            WHERE status='inflight' AND platform='facebook' AND upload_session IS NOT NULL
              AND upload_offset < COALESCE((SELECT v.file_size FROM dispatches d JOIN videos v ON v.id=d.video_id
                  WHERE d.id=posts.dispatch_id),0)
        """, (localnow().isoformat(),))
    con.execute("""
        UPDATE posts SET status='needs_check',error='Mac process interrupted during remote upload; reconcile manually',
          updated_at=? WHERE status='inflight'
    """, (localnow().isoformat(),))
    con.commit()


def reconcile(con: sqlite3.Connection):
    # Only long-episode Facebook posts have a guaranteed remote video ID here.
    # Shorts/Reels may return a post_id, so do not guess its status endpoint.
    fb_rows = con.execute("""SELECT p.* FROM posts p
        JOIN dispatches d ON p.dispatch_id=d.id
        JOIN videos v ON d.video_id=v.id
        WHERE v.kind='long' AND p.platform='facebook' AND p.status IN ('submitted','needs_check')
              AND p.remote_id IS NOT NULL""").fetchall()
    for item in fb_rows:
        try:
            status = backends.facebook_video_status(item["remote_id"])
            if status in ("published", "failed"):
                post_update(con, item["dispatch_id"], "facebook", status)
                send_notice(f"Facebook full episode {status}: video={item['remote_id']}")
        except Exception as exc:
            # A temporary permission/status error must not change the submission state.
            print(f"Facebook full episode status check failed: {redact_error(exc)}")

    yt_rows = con.execute("SELECT * FROM posts WHERE platform='youtube' AND status='submitted' AND remote_id IS NOT NULL").fetchall()
    for item in yt_rows:
        try:
            status = backends.youtube_video_status(item["remote_id"])
            if status in ("published", "failed"):
                post_update(con, item["dispatch_id"], "youtube", status)
                send_notice(f"YouTube {status}: video={item['remote_id']}")
        except Exception as exc:
            print(f"YouTube status check failed: {redact_error(exc)}")

    if os.getenv("TIKTOK_MODE", "off") != "api":
        return
    rows = con.execute("SELECT * FROM posts WHERE platform='tiktok' AND status='submitted' AND remote_id IS NOT NULL").fetchall()
    for item in rows:
        try:
            state, outcome = backends.tiktok_status(item["remote_id"])
            if state in ("published", "failed"):
                post_update(con, item["dispatch_id"], "tiktok", state,
                            error=outcome if state == "failed" else None)
                send_notice(f"TikTok {state}: {outcome}")
        except Exception as exc:
            print(f"TikTok reconciliation temporarily failed: {exc}")


def report(con: sqlite3.Connection):
    entries = con.execute("""
        SELECT d.id,d.slot_key,v.path,v.kind,p.platform,p.status,p.remote_id,p.error FROM dispatches d
        JOIN videos v ON v.id=d.video_id JOIN posts p ON p.dispatch_id=d.id
        ORDER BY d.id DESC,p.platform LIMIT 60
    """).fetchall()
    if not entries:
        print("No dispatches yet")
    for e in entries:
        print(f"#{e['id']} {e['slot_key']} [{e['kind']}] {Path(e['path']).name} | {e['platform']:8} | "
              f"{e['status']:12} | {e['remote_id'] or '-'} | {e['error'] or ''}")


def preview(con: sqlite3.Connection, kind: str = "short"):
    video = con.execute("""
        SELECT v.path FROM videos v WHERE v.kind=? AND v.stale=0 AND NOT EXISTS
        (SELECT 1 FROM dispatches d WHERE d.video_id=v.id) ORDER BY v.id LIMIT 1
    """, (kind,)).fetchone()
    if not video:
        folder = "FULL_VIDEO_DIR (or YT_LONG_VIDEO_DIR)" if kind == "long" else "VIDEO_DIR"
        print(f"No queued {kind} video. Add .mp4 to {folder} and run scan.")
        return
    path = Path(video["path"])
    print("DRY RUN ONLY — nothing will be uploaded:")
    print("Stream:", kind)
    print("Video:", path)
    details = validate(path, kind)
    print("Video info:", details)
    print("Captions:", json.dumps(make_caption(path, details, kind), indent=2, ensure_ascii=False))
    print("Platforms:", platforms(kind))
    print("Posting slots:", slots(kind), os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh"))
    if kind == "long":
        print("Allowed weekdays:", sorted(long_post_days()))


def main():
    parser = argparse.ArgumentParser(description="MacBook: separate full-episode and short-highlight publisher")
    parser.add_argument("command", choices=("scan", "preview", "tick", "run-now", "status", "authorize-youtube", "adb-inspect", "doctor"))
    parser.add_argument("--stream", choices=STREAMS, default="short", help="For preview/run-now only (default: short)")
    args = parser.parse_args()
    if args.command == "doctor":
        from doctor import main as doctor_main
        return doctor_main([])
    if args.command == "authorize-youtube":
        backends.youtube_client(interactive=True)
        print("YouTube OAuth authorized; token.json created")
        return
    if args.command == "adb-inspect":
        from tiktok_adb import inspect
        inspect()
        return
    with exclusive_lock(), db() as con:
        quarantine_interrupted_uploads(con)
        if args.command == "status":
            report(con)
            return
        scan(con)
        if args.command == "scan":
            return
        if args.command == "preview":
            preview(con, args.stream)
            return
        if os.getenv("ENABLE_LIVE_POSTING", "false").lower() != "true":
            raise backends.PreflightError("Live posting disabled. Run `preview`, then set ENABLE_LIVE_POSTING=true")
        now = localnow()
        if args.command == "run-now":
            if args.stream == "long" and not long_video_dir():
                raise backends.PreflightError("Set FULL_VIDEO_DIR (or YT_LONG_VIDEO_DIR) to enable full episodes")
            prefix = "full-manual-" if args.stream == "long" else "manual-"
            create_dispatch(con, prefix + now.strftime("%Y%m%d-%H%M%S-%f"), now, args.stream)
        else:
            for scheduled_time in due(now, "short"):
                create_dispatch(con, now.date().isoformat() + "-" + scheduled_time, now, "short")
            if long_video_dir():
                for scheduled_time in due(now, "long"):
                    create_dispatch(con, "full:" + now.date().isoformat() + "-" + scheduled_time, now, "long")
        publish_pending(con, args.stream if args.command == "run-now" else None)
        reconcile(con)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, backends.PreflightError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
