# Changelog V3 — 2026-11-23

- Added Page Videos adapter `facebook_video_publish` for full-length episodes (`/{page-id}/videos`).
- Kept existing Page Reels adapter for highlights (`/{page-id}/video_reels`).
- Full queue now optionally fans out to both `facebook` and `youtube`, each with its own row in `posts`.
- Added `FULL_VIDEO_DIR`, `FULL_PLATFORMS`, `FULL_POST_TIMES`, `FULL_POST_DAYS`, `FULL_MAX_DAILY_POSTS`; old `YT_LONG_*` work unchanged.
- Facebook full metadata: `facebook_title` and `facebook_description` JSON sidecar, AI or fallback metadata.
- Facebook long multipart size safety cap with preflight. Requests go to `graph.facebook.com` by default; older `graph-video.facebook.com` can be explicitly configured but is deprecated.
- Reconciliation checks remote full-video publication status conservatively; only marks published when confirmed.
- No automatic retry after ambiguous upload failures, no retroactive Facebook publishing of already-dispatched V2 episodes.
- 23 automated offline tests, including new dual-destination and mock-upload cases.

Documentation: `HUONG_DAN_V3_VIDEO_DAI_VA_HIGHLIGHT.md`.