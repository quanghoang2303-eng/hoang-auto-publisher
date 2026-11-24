# Changelog V3 — 2026-11-23

- Added resumable Page Videos upload for full-length episodes (`/{page-id}/videos`) using start/transfer/finish, with SQLite checkpoints for session and byte offset.
- Kept existing Page Reels adapter for highlights (`/{page-id}/video_reels`).
- Full queue now optionally fans out to both `facebook` and `youtube`, each with its own row in `posts`.
- Added `FULL_VIDEO_DIR`, `FULL_PLATFORMS`, `FULL_POST_TIMES`, `FULL_POST_DAYS`, `FULL_MAX_DAILY_POSTS`; old `YT_LONG_*` work unchanged.
- Facebook full metadata can come from the optional `PUBLISH_MANIFEST` or per-video sidecar/AI/fallback. Manifest entries name the episode, exact media filename, targets and platform metadata; configured platform targets must match.
- Facebook long-video preflight enforces configurable byte, duration and chunk limits. Defaults: 1,000,000,000 bytes, 43,200 seconds and 8 MiB per chunk. Both Reels and Page Videos require `ENABLE_LIVE_POSTING=true` and `FB_ALLOW_PUBLIC_POSTING=true`; Facebook posts are public.
- Facebook transfer chunks retry temporary network/server errors up to `FB_UPLOAD_CHUNK_RETRIES` times (default 3, range 0–10), always with the same session and starting offset. After exhaustion, an incomplete known session returns to `queued` for resume on the next scheduler tick. `FINISH` is never retried automatically; ambiguous finish results become `needs_check` for manual reconciliation.
- Reconciliation checks remote full-video publication status conservatively; only marks published when confirmed. YouTube uploads use resumable chunks and remote status polling; `submitted` is not proof of publication.
- SQLite schema changes are additive and retain V2 rows, queue state and credentials. No reset or credential replacement is required.
- Facebook may display longer videos as Reels following its product change; workflow routing remains different for Page Videos and Page Reels.
- 23 automated offline tests, including new dual-destination and mock-upload cases.

Documentation: `HUONG_DAN_V3_VIDEO_DAI_VA_HIGHLIGHT.md`.
