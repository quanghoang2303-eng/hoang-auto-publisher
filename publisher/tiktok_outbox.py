"""Local TikTok review packages; no network, account login or automated UI posting."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit

from backends import PreflightError


def outbox_root() -> Path:
    return Path(os.getenv("TIKTOK_OUTBOX_DIR", "state/tiktok_outbox")).expanduser().resolve()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def prepare(video: Path, caption: dict, metadata: dict, dispatch_id: int,
            fingerprint: str, *, root: Path | None = None) -> tuple[str, str]:
    """Create one immutable local package per dispatch; retry never creates a second package."""
    if not isinstance(dispatch_id, int) or dispatch_id < 1:
        raise PreflightError("Invalid TikTok dispatch ID")
    if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise PreflightError("Invalid TikTok video fingerprint")
    if video.suffix.lower() != ".mp4" or not video.is_file():
        raise PreflightError("TikTok review requires an existing MP4")
    target = metadata.get("manifest_platform_metadata", {}).get("tiktok", {})
    text = target.get("description") or caption.get("tiktok")
    if not isinstance(text, str) or not text.strip():
        raise PreflightError("TikTok caption is missing")
    if len(text) > 2200:
        raise PreflightError("TikTok caption exceeds the 2200 character review limit")
    aigc = target.get("is_aigc", metadata.get("is_aigc"))
    if aigc is not None and not isinstance(aigc, bool):
        raise PreflightError("TikTok is_aigc must be true or false")
    if digest(video) != fingerprint:
        raise PreflightError("TikTok video changed after queueing")
    root = root or outbox_root()
    root.mkdir(parents=True, exist_ok=True)
    dest = root / f"dispatch-{dispatch_id:08d}"
    record = {
        "dispatch_id": dispatch_id, "sha256": fingerprint,
        "episode_id": metadata.get("episode_id"),
        "original_filename": video.name, "media": "video.mp4",
        "caption": text.strip(), "is_aigc": aigc,
        "state": "awaiting_manual",
        "instructions": "Review video, caption, AI disclosure, account and privacy in TikTok Studio. Publish/schedule manually. Confirm only after it is actually visible."
    }
    if dest.exists():
        try:
            old = json.loads((dest / "review.json").read_text(encoding="utf-8"))
            valid = old == record and digest(dest / "video.mp4") == fingerprint
            valid = valid and (dest / "caption.txt").read_text(encoding="utf-8") == text.strip() + "\n"
        except (OSError, ValueError):
            valid = False
        if not valid:
            raise PreflightError("Existing TikTok review package differs; inspect before replacing")
        return "awaiting_manual", str(dest)
    tmp = Path(tempfile.mkdtemp(prefix=".tiktok-", dir=root))
    try:
        shutil.copyfile(video, tmp / "video.mp4")
        if digest(tmp / "video.mp4") != fingerprint:
            raise PreflightError("TikTok review copy failed integrity check")
        (tmp / "caption.txt").write_text(text.strip() + "\n", encoding="utf-8")
        (tmp / "review.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.rename(dest)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)
    return "awaiting_manual", str(dest)


def checked_post_url(value: str) -> str:
    """Accept a canonical video permalink, not arbitrary URLs or short links."""
    parsed = urlsplit(value.strip())
    if (parsed.scheme != "https" or parsed.netloc.lower() not in {"www.tiktok.com", "tiktok.com"}
            or not re.fullmatch(r"/@[A-Za-z0-9._]+/video/[0-9]+/?", parsed.path)):
        raise PreflightError("Use the actual https://www.tiktok.com/@account/video/ID permalink")
    return "https://www.tiktok.com" + parsed.path.rstrip("/")


def confirm(con, dispatch_id: int, permalink: str) -> None:
    """Record the owner's manual confirmation; this does not query TikTok."""
    link = checked_post_url(permalink)
    row = con.execute("SELECT status FROM posts WHERE dispatch_id=? AND platform='tiktok'",
                      (dispatch_id,)).fetchone()
    if row is None or row["status"] not in {"awaiting_manual", "published_manual"}:
        raise PreflightError("Only an existing TikTok manual-review job can be confirmed")
    existing = con.execute("SELECT dispatch_id FROM posts WHERE platform='tiktok' AND remote_id=?",
                           (link,)).fetchone()
    if existing and existing["dispatch_id"] != dispatch_id:
        raise PreflightError("This TikTok permalink is already recorded for another dispatch")
    if row["status"] == "published_manual":
        previous = con.execute("SELECT remote_id FROM posts WHERE dispatch_id=? AND platform='tiktok'",
                               (dispatch_id,)).fetchone()
        if previous["remote_id"] != link:
            raise PreflightError("TikTok job already confirmed with a different permalink")
        return
    con.execute("UPDATE posts SET status='published_manual',remote_id=?,error=NULL,updated_at=datetime('now') "
                "WHERE dispatch_id=? AND platform='tiktok'", (link, dispatch_id))
    con.commit()
