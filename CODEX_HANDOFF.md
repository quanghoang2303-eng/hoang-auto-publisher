# Codex handoff — Auto Publisher V3

## Context
This repository hosts the public GitHub Pages OAuth website at the repository root. **Do not move, delete, or replace `index.html`, `privacy.html`, `terms.html`, or `styles.css`.** The Python video publisher is in `publisher/`; it must run locally on macOS. All credentials remain local; do not commit `.env`, `token.json`, `client_secret.json`, logs, databases, or media.

## Existing implemented MVP
- Full episode queue: publish the original long-form episode to a YouTube normal video and Facebook Page Video via separate per-platform records.
- Highlight queue: independently publish vertical short clips as YouTube Shorts and Facebook Reels. TikTok integration remains optional/experimental.
- Scheduling, dry-run, SQLite deduplication, scoped metadata, and tests.
- The direct Facebook full-video multipart adapter currently enforces a **1 GB safety limit**. This is an MVP bound, not a universal platform limit.

## Your development tasks (do not publish to live accounts during tests)
1. Read `publisher/README.md`, `publisher/HUONG_DAN_V3_VIDEO_DAI_VA_HIGHLIGHT.md`, and the code. Audit correctness of Facebook Page Video, Reels, and YouTube APIs against the latest official docs. Fix deprecations and clarify how Facebook may surface full videos as Reels.
2. Add a resumable/chunked Facebook full-video upload path if supported by the current official API; maintain a safe preflight and clear failure state if unsupported. Verify completion status before marking published. Do not assume API 200 means the video is public.
3. Implement idempotent retry/reconciliation after partial upload, network timeouts, and process restarts. Use remote IDs and per-platform durable states; no duplicate posts.
4. Add a full-episode/short-highlight manifest with explicit episode IDs, filenames, metadata and per-channel publication targets, plus guardrails against accidental cross-posting.
5. Preserve existing SQLite state and env compatibility with V2; provide migrations/tests, Windows not required. Ensure `launchd` observes each queue without double dispatch.
6. Add CI-free local test and preflight commands that do not require API credentials. Avoid expensive GitHub Actions jobs; the owner prefers minimal cost.
7. Audit `requirements.txt`, OAuth scopes, token refresh and log redaction. Block any live publish unless `ENABLE_LIVE_POSTING=true`, and add an explicit safety check for Facebook public posting (YouTube private testing is separate).
8. Document manual setup and acceptance tests for Facebook Page and YouTube account verification; no tokens or secrets in PR discussion.

## Acceptance criteria
- `cd publisher && python -m unittest discover -s tests -v` passes on macOS-compatible Python.
- Test videos route full episodes only to `facebook` (Page Videos) and `youtube` (normal videos), and highlights only to Facebook Reels/YouTube Shorts (+ TikTok only if opted in).
- Simulated timeout and restart do not create duplicate remote posts.
- Root GitHub Pages website files have no diff.
- Manual live publishing is opt-in and must be tested only with explicit owner permission and disposable content.

## Baseline tests
V3 ZIP baseline was run offline with `23/23` tests passing; `ResourceWarning` from unclosed SQLite connections was observed in tests and should be cleaned up. No live API upload has been verified.
