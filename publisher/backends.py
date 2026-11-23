"""Official-platform publishers. All methods are called ONLY after the local live flag."""
from __future__ import annotations

import os
from pathlib import Path

import requests


class PreflightError(RuntimeError):
    """A required credential, consent, or configuration is missing."""


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise PreflightError(f"Missing {name}")
    return value


def checked(response: requests.Response) -> dict:
    response.raise_for_status()
    data = response.json()
    if data.get("error") and data["error"].get("code") != "ok":
        raise RuntimeError(f"API rejected the request: {data['error']}")
    return data


def facebook_publish(video: Path, caption: dict) -> tuple[str, str]:
    """Page Reels: START -> upload binary -> FINISH. Accepted != publicly visible."""
    token, page = required("FB_PAGE_ACCESS_TOKEN"), required("FB_PAGE_ID")
    version = os.getenv("FB_GRAPH_VERSION", "v27.0")
    endpoint = f"https://graph.facebook.com/{version}/{page}/video_reels"
    session = requests.Session()
    start = checked(session.post(endpoint, data={"access_token": token, "upload_phase": "START"}, timeout=30))
    video_id = str(start["video_id"])
    upload_url = start["upload_url"]
    # Important: no retries here; a timeout may mean a post/upload was accepted.
    with video.open("rb") as handle:
        result = checked(session.post(upload_url, headers={
            "Authorization": f"OAuth {token}",
            "offset": "0", "file_size": str(video.stat().st_size),
            "Content-Type": "application/octet-stream",
        }, data=handle, timeout=(15, 600)))
    if result.get("success") is False:
        raise RuntimeError(f"Facebook upload failed: {result}")
    finish = checked(session.post(endpoint, data={
        "access_token": token, "video_id": video_id, "upload_phase": "FINISH",
        "video_state": "PUBLISHED", "title": caption["title"],
        "description": caption["facebook"],
    }, timeout=60))
    if finish.get("success") is False:
        raise RuntimeError(f"Facebook did not accept FINISH: {finish}")
    return "submitted", str(finish.get("post_id") or video_id)


def facebook_video_preflight(video: Path) -> None:
    """Fail before marking an upload inflight when it is clearly too large."""
    try:
        max_bytes = int(os.getenv("FB_FULL_MAX_BYTES", "1000000000"))
    except ValueError as exc:
        raise PreflightError("FB_FULL_MAX_BYTES must be a positive integer") from exc
    if max_bytes < 1:
        raise PreflightError("FB_FULL_MAX_BYTES must be a positive integer")
    if video.stat().st_size > max_bytes:
        raise PreflightError(
            f"Full episode exceeds Facebook multipart safety limit {max_bytes} bytes; "
            "compress it or implement resumable upload before publishing"
        )


def facebook_video_status(video_id: str) -> str:
    """Conservative status check for full Page Videos; don't infer published from 'ready'."""
    token = required("FB_PAGE_ACCESS_TOKEN")
    version = os.getenv("FB_GRAPH_VERSION", "v27.0")
    response = requests.get(f"https://graph.facebook.com/{version}/{video_id}",
                            params={"access_token": token, "fields": "status,is_published"},
                            timeout=20)
    data = checked(response)
    state = data.get("status") or {}
    if not isinstance(state, dict):
        state = {}
    publishing = state.get("publishing_phase") or {}
    if not isinstance(publishing, dict):
        publishing = {}
    video_state = str(state.get("video_status", "")).lower()
    publish_state = str(publishing.get("publish_status", "")).lower()
    if video_state in {"error", "upload_failed", "expired"} or publish_state in {"error", "failed"}:
        return "failed"
    if data.get("is_published") is True or publish_state == "published":
        return "published"
    return "submitted"

def facebook_video_publish(video: Path, caption: dict, metadata: dict | None = None) -> tuple[str, str]:
    """Upload a full episode using Meta's Page Videos endpoint (not the Reels upload phase).

    This conservative MVP supports multipart uploads up to a configurable size limit.
    If the HTTP result is uncertain, publisher.py marks it needs_check; it NEVER retries
    publication blindly. Meta may present all Facebook videos in its Reels experience.
    """
    token, page = required("FB_PAGE_ACCESS_TOKEN"), required("FB_PAGE_ID")
    version = os.getenv("FB_GRAPH_VERSION", "v27.0")
    facebook_video_preflight(video)
    title = str(caption.get("facebook_title") or caption["title"]).strip()[:255]
    description = str(caption.get("facebook") or caption["youtube"]).strip()
    if not title or not description:
        raise PreflightError("Full Facebook video needs nonempty title and description")
    # Use dedicated video host, not graph.facebook.com/video_reels.
    # Meta's current Video API guidance uses graph.facebook.com; old graph-video
    # host is deprecated. Configurable only for compatibility with Meta rollouts.
    host = os.getenv("FB_VIDEO_UPLOAD_HOST", "graph.facebook.com").strip()
    if host not in {"graph.facebook.com", "graph-video.facebook.com"}:
        raise PreflightError("FB_VIDEO_UPLOAD_HOST must be a recognized Meta Graph host")
    url = f"https://{host}/{version}/{page}/videos"
    # requests.post(files=...) buffers the ENTIRE video into RAM. Use
    # requests-toolbelt MultipartEncoder to stream the file in bounded memory.
    # No implicit retries: a timeout can mean Facebook has already accepted it.
    from requests_toolbelt.multipart.encoder import MultipartEncoder

    with video.open("rb") as handle:
        form = MultipartEncoder(fields={
            "access_token": token, "title": title,
            "description": description[:60000], "published": "true",
            "source": (video.name, handle, "video/mp4"),
        })
        response = requests.post(
            url,
            data=form,
            headers={"Content-Type": form.content_type},
            timeout=(30, 1800),
        )
    result = checked(response)
    video_id = result.get("id") or result.get("video_id")
    if not video_id:
        raise RuntimeError("Facebook Page Videos returned no video ID; check remotely before retry")
    return "submitted", str(video_id)


YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _yt_paths() -> tuple[Path, Path]:
    return Path(os.getenv("YT_CLIENT_SECRET_FILE", "client_secret.json")), Path(os.getenv("YT_TOKEN_FILE", "token.json"))


def youtube_client(interactive: bool = False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    secret, token = _yt_paths()
    credentials = Credentials.from_authorized_user_file(str(token), YOUTUBE_SCOPES) if token.exists() else None
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        elif interactive:
            if not secret.exists():
                raise PreflightError(f"Missing {secret}; create a Google OAuth Desktop client first")
            credentials = InstalledAppFlow.from_client_secrets_file(str(secret), YOUTUBE_SCOPES).run_local_server(port=0)
        else:
            raise PreflightError("YouTube not authorized: run `python publisher.py authorize-youtube` once")
        token.write_text(credentials.to_json(), encoding="utf-8")
        try:
            os.chmod(token, 0o600)
        except OSError:
            pass
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def youtube_publish(video: Path, caption: dict, kind: str = "short", metadata: dict | None = None) -> tuple[str, str]:
    from googleapiclient.http import MediaFileUpload

    if kind not in {"short", "long"}:
        raise PreflightError(f"Unknown YouTube stream: {kind}")
    metadata = metadata or {}
    youtube = youtube_client()
    privacy = (os.getenv("YT_LONG_PRIVACY", "").strip() if kind == "long" else "") or os.getenv("YT_PRIVACY", "public")
    if privacy not in {"public", "private", "unlisted"}:
        raise PreflightError("YT_PRIVACY / YT_LONG_PRIVACY must be public, private, or unlisted")
    status = {"privacyStatus": privacy}
    # Do not silently classify the user's videos under children's-content rules.
    per_video = metadata.get("youtube_made_for_kids")
    if per_video is not None and not isinstance(per_video, bool):
        raise PreflightError("youtube_made_for_kids in the .json sidecar must be true or false")
    made_for_kids = os.getenv("YT_MADE_FOR_KIDS", "").strip().lower()
    if per_video is not None:
        status["selfDeclaredMadeForKids"] = per_video
    elif made_for_kids in ("true", "false"):
        status["selfDeclaredMadeForKids"] = made_for_kids == "true"
    elif made_for_kids:
        raise PreflightError("YT_MADE_FOR_KIDS must be true, false, or left empty")
    category = os.getenv("YT_LONG_CATEGORY_ID", "27") if kind == "long" else "22"
    if not category.isdigit():
        raise PreflightError("YT_LONG_CATEGORY_ID must be a YouTube numeric category ID")
    body = {
        "snippet": {"title": caption["title"][:100], "description": caption["youtube"][:5000], "categoryId": category},
        "status": status,
    }
    media = MediaFileUpload(str(video), mimetype="video/mp4", resumable=True, chunksize=8 * 1024 * 1024)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    result = None
    while result is None:
        # Chunk-level retries within a live resumable session. Interrupted/uncertain uploads
        # still move to needs_check; never blindly create a second remote video.
        _, result = request.next_chunk(num_retries=3)
    return "submitted", result["id"]


def _tiktok_json(url: str, body: dict) -> dict:
    token = required("TIKTOK_ACCESS_TOKEN")
    result = checked(requests.post(f"https://open.tiktokapis.com{url}", json=body, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
    }, timeout=30))
    if result.get("error", {}).get("code") != "ok":
        raise RuntimeError(f"TikTok API error: {result.get('error')}")
    return result["data"]


def tiktok_status(publish_id: str) -> tuple[str, str]:
    data = _tiktok_json("/v2/post/publish/status/fetch/", {"publish_id": publish_id})
    state = data.get("status", "UNKNOWN")
    if state == "PUBLISH_COMPLETE":
        return "published", publish_id
    if state == "FAILED":
        return "failed", f"{publish_id} | {data.get('fail_reason', 'unspecified')}"
    return "submitted", publish_id


def tiktok_api_publish(video: Path, caption: dict, metadata: dict) -> tuple[str, str]:
    """Designed for a reviewed client with creator UI, explicit consent per post."""
    if metadata.get("tiktok_consent") is not True:
        raise PreflightError("TikTok requires explicit consent per post; set tiktok_consent in the .json sidecar after review")
    if os.getenv("TIKTOK_APP_APPROVED", "false").lower() != "true":
        raise PreflightError("Direct Post public requires an approved/audited TikTok developer app")
    info = _tiktok_json("/v2/post/publish/creator_info/query/", {})
    privacy = metadata.get("tiktok_privacy_level")
    if not privacy or privacy not in info.get("privacy_level_options", []):
        raise PreflightError("Select a privacy level offered by TikTok creator_info in the .json sidecar")
    if info.get("max_video_post_duration_sec", 0) < metadata.get("duration_seconds", 0):
        raise PreflightError("Video longer than TikTok creator's allowed maximum")
    size = video.stat().st_size
    # The last chunk may include a remainder (up to 128 MB).
    chunk = min(10_000_000, size)
    count = max(1, size // chunk)
    initialized = _tiktok_json("/v2/post/publish/video/init/", {
        "post_info": {
            "title": caption["tiktok"][:2200], "privacy_level": privacy,
            "disable_comment": bool(metadata.get("disable_comment", False)),
            "disable_duet": bool(metadata.get("disable_duet", False)),
            "disable_stitch": bool(metadata.get("disable_stitch", False)),
            "brand_content_toggle": bool(metadata.get("brand_content_toggle", False)),
            "brand_organic_toggle": bool(metadata.get("brand_organic_toggle", False)),
            "is_aigc": bool(metadata.get("is_aigc", False)),
        },
        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count},
    })
    upload_url, publish_id = initialized["upload_url"], initialized["publish_id"]
    with video.open("rb") as handle:
        for index in range(count):
            start = handle.tell()
            length = chunk if index < count - 1 else size - start
            payload = handle.read(length)
            response = requests.put(upload_url, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(payload)),
                "Content-Range": f"bytes {start}-{start + len(payload) - 1}/{size}",
            }, data=payload, timeout=(15, 300))
            response.raise_for_status()
    return "submitted", publish_id