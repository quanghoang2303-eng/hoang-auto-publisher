# Mac Auto Publisher V3 — Tập đầy đủ (Facebook + YouTube) và highlight (Reels + Shorts)

**Bắt đầu bằng:** `HUONG_DAN_V3_VIDEO_DAI_VA_HIGHLIGHT.md` (tiếng Việt).

Run two independent local queues: 1–5 daily vertical **highlights** to Facebook **Page** Reels / YouTube Shorts (TikTok optional), plus scheduled **full episodes** to both Facebook Page Videos and YouTube regular videos from a separate folder. The Mac scheduler (`launchd`) processes both queues in one process. This is an MVP, not a hosted service.

## Important limitations

- **TikTok:** TikTok's Content Posting API guidelines explicitly reject personal/internal uploader utilities as eligible API clients and require that users preview/control/consent to what is posted. Public Direct Post is gated behind review. A per-video JSON flag in this MVP is only a technical guard, **not a substitute for TikTok-compliant UX/review**. Assume `TIKTOK_MODE=off` unless your use case qualifies. Android ADB relies on UI automation and may violate platform terms or break after app updates; test with a separate account, and never bypass security challenges.
- **Facebook:** Every live post is public. Both Page Reels (highlights) and Page Videos (full episodes) require `ENABLE_LIVE_POSTING=true` **and** `FB_ALLOW_PUBLIC_POSTING=true`. Use a Page Access Token and the Page's `CREATE_CONTENT` task, with the relevant permissions and app review/access. Accepted uploads may need processing before they appear.
- **YouTube:** `videos.insert` works for both Shorts and regular videos with the same `youtube.upload` scope. Square/vertical videos up to 3 minutes are usually Shorts; the shared short-form queue deliberately accepts only 4–60 seconds and 9:16. Long-form accepts landscape videos, or square/vertical videos **longer than 3 minutes**. YouTube OAuth token authorization is a one-time interactive action, refresh may require renewed permission.
- ADB cannot guarantee publication from a button press. Its result is `submitted_unverified`; verify the TikTok profile occasionally.
- Videos containing third-party music can trigger copyright restrictions. Do not treat successful upload as proof that the video is public or monetizable.
- Mac must be **awake**, connected to the Internet and (for ADB) to an unlocked Android device. A sleeping Mac will miss scheduled windows.
- YouTube uses resumable 8 MiB upload chunks and retries temporary chunk errors up to 3 times during the same process. A returned video ID is `submitted`, not proof of publication. Later checks report processed public or unlisted videos as `published` (available according to the selected privacy); an unlisted video is accessible by link and is not publicly discoverable. Private or still-processing videos remain `submitted`, while failed/rejected uploads become `failed`. An interrupted or ambiguous upload becomes `needs_check`; inspect YouTube Studio before retrying.
- Facebook full episodes use resumable start/transfer/finish uploads with the session ID and byte offset saved in SQLite after each accepted chunk. A lost chunk response or temporary network/server error retries the same chunk (default 3 retries, configurable with `FB_UPLOAD_CHUNK_RETRIES`, range 0–10); Meta's returned offsets are validated before advancing. If those retries run out and the known session still has bytes remaining, the post returns to `queued` and the next scheduler tick resumes that same session from the saved offset. `FINISH` is sent once only; an ambiguous finish result becomes `needs_check` for manual Page reconciliation. Facebook highlights still use the Reels start/upload/finish flow.

## Requirements

- MacBook with macOS, Python 3.11+, Homebrew
- Short queue: 1–5 original `.mp4` videos per day, vertical 9:16 (recommended 1080×1920 H.264/AAC), **4–60 s**
- Optional full-episode queue (YouTube + Facebook): landscape 16:9 recommended (1920×1080 H.264/AAC), or vertical over 3 minutes; YouTube channel verification is required for uploads over 15 minutes.
- Optional Android with USB debugging/ADB for TikTok UI testing
- Facebook Developer app + Page Access Token, Google Cloud OAuth Desktop client
- Optional OpenAI API key for image-based caption generation

## Install on the Mac

```bash
brew install python ffmpeg android-platform-tools
cd mac-reels-publisher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
mkdir -p "$HOME/Videos/AutoPublisher/inbox"
mkdir -p "$HOME/Videos/AutoPublisher/full_episodes"
```

Edit `.env`:

```ini
VIDEO_DIR=/Users/your_username/Videos/AutoPublisher/inbox
FULL_VIDEO_DIR=/Users/your_username/Videos/AutoPublisher/full_episodes
FULL_PLATFORMS=facebook,youtube
POST_TIMES=09:00,12:00,18:00
MAX_DAILY_POSTS=3
FULL_POST_TIMES=19:00
FULL_POST_DAYS=mon,wed,fri
FULL_MAX_DAILY_POSTS=1
YT_LONG_PRIVACY=private
TIMEZONE=Asia/Ho_Chi_Minh
TIKTOK_MODE=off
PLATFORMS=facebook,youtube
ENABLE_LIVE_POSTING=false
```

**Never commit `.env`, `token.json` or OAuth secrets to Git.** These files are ignored by `.gitignore`.

### Upgrade safely from the Shorts-only version

Back up your existing project state, `.env`, `token.json`, and `client_secret.json` before replacing code. Copy code and `.env.example`, keep your existing state and secrets, and add new `FULL_*` options to the existing `.env` without replacing credentials. Old `YT_LONG_*` settings remain compatible. Startup adds missing SQLite columns to `videos` and `posts`; existing rows, dispatches and fingerprints are preserved. No database reset or credential replacement is needed. Do not run two copies against the same database.

## Facebook Page setup

1. Go to [Meta for Developers](https://developers.facebook.com/), create/select an app with Page functionality. Request the appropriate Page permissions, and check app review/business verification requirements for your account.
2. Obtain a **Page Access Token**, not merely a user token, from the authorized Page. Have the `CREATE_CONTENT` Page task and required Page permissions.
3. Set `FB_PAGE_ID` and `FB_PAGE_ACCESS_TOKEN` in `.env`.
4. Highlights use `/{page_id}/video_reels` (`START`, upload, `FINISH`). Full episodes use `/{page_id}/videos` in resumable `start`, `transfer`, `finish` phases. Defaults are a 1,000,000,000-byte limit (`FB_FULL_MAX_BYTES`), 43,200-second duration limit (`FB_FULL_MAX_DURATION_SECONDS`) and 8 MiB chunks (`FB_UPLOAD_CHUNK_BYTES`). These are configurable safety limits; preflight blocks oversized/overlong files before upload. Facebook posts are public, and both flags `ENABLE_LIVE_POSTING=true` and `FB_ALLOW_PUBLIC_POSTING=true` are required. Facebook may display longer videos as Reels after its product change, even though the workflow routes highlights and full episodes differently.

Meta official resources:
- https://developers.facebook.com/docs/graph-api/reference/page/video_reels
- https://developers.facebook.com/docs/graph-api/reference/page/videos/
- https://www.postman.com/meta/facebook/documentation/r56bjfd/facebook-api



### V3: Important Facebook behavior

Meta announced in June 2025 that Facebook may present longer videos as Reels regardless of length or orientation. The app still routes full episodes through Page Videos and highlights through Page Reels. See `HUONG_DAN_V3_VIDEO_DAI_VA_HIGHLIGHT.md` for Mac setup, per-platform metadata, migration and safety steps.

## YouTube setup

1. Create a project at [Google Cloud Console](https://console.cloud.google.com/), enable **YouTube Data API v3**.
2. Configure OAuth consent screen, create a **Desktop app** OAuth client, download JSON to `client_secret.json` in this folder (keep private).
3. Run **once** in Terminal (browser login will open):

```bash
python publisher.py authorize-youtube
```

4. The app saves `token.json` locally for refresh. Confirm the Google account/channel is the correct destination. You may need to add your account as an OAuth test user and handle testing-mode refresh-token expiry.

Google official docs:
- https://developers.google.com/youtube/data/guides/uploading_a_video
- https://developers.google.com/youtube/data/reference/rest/v3/videos/insert

## Full-episode auto posting: Facebook Page + YouTube (V3)

The **separate** full-episode queue is enabled when `FULL_VIDEO_DIR` (or the old `YT_LONG_VIDEO_DIR`) is set. `FULL_POST_TIMES` is independent of Shorts' `POST_TIMES`; `FULL_POST_DAYS` accepts `mon,tue,wed,thu,fri,sat,sun` (blank means daily). Its daily cap is `FULL_MAX_DAILY_POSTS` (1–5). `FULL_PLATFORMS=facebook,youtube` sends a distinct post job to each destination. **For safe upgrades from V2, the default without FULL_PLATFORMS is youtube only.** TikTok is never a full-episode destination. If both streams trigger at the same minute, the single scheduler handles highlights first and full episodes second. Both Facebook destinations are public and need both live-posting flags.

Facebook Page Videos uses resumable start/transfer/finish uploads. `FB_FULL_MAX_BYTES` defaults to 1,000,000,000 bytes, `FB_FULL_MAX_DURATION_SECONDS` to 43,200 seconds (12 hours), and `FB_UPLOAD_CHUNK_BYTES` to 8,388,608 bytes (8 MiB). Session and accepted byte offset are checkpointed to SQLite after each chunk, allowing a partial transfer to resume. Temporary transfer network/server errors retry the same chunk up to `FB_UPLOAD_CHUNK_RETRIES` times (default 3). If retries exhaust while the saved session has bytes remaining, the post is queued for the next scheduler tick, which resumes the same session at the checkpointed offset. `FINISH` is sent once; an ambiguous result is marked `needs_check` and must be reconciled manually before retry. The app polls full-video status and marks it published only when Meta explicitly confirms publication. Meta may present longer videos as Reels; routing still uses Page Videos for full episodes and Page Reels for highlights.

Start with `YT_LONG_PRIVACY=private` until upload processing is confirmed in YouTube Studio, then choose `public` or `unlisted` for the intended audience. `YT_PRIVACY` controls highlights (default `public`); `YT_LONG_PRIVACY` overrides it for full episodes (default `private`). YouTube OAuth uses the `youtube.upload` scope. The local token is refreshed by the Google client when possible; rerun `authorize-youtube` if refresh is revoked or expired. `YT_LONG_CATEGORY_ID` defaults to `27` (Education) and `YT_MADE_FOR_KIDS` applies to both queues unless overridden per-video; decide the audience accurately for your actual film.

Suggested file layout (the `.txt` and `.json` sidecars are optional):

```text
~/Videos/AutoPublisher/
  inbox/
    short_01.mp4
  full_episodes/
    tap_01.mp4
    tap_01.txt          # optional transcript/context for AI or fallback description
    tap_01.json         # optional exact metadata/audience override
```

To provide precise title/description without relying on three AI keyframes, create a same-named `.json` sidecar:

```json
{
  "videos": [
    {
      "kind": "long",
      "episode_id": "GEN-S01-E01",
      "media_filename": "GENERATION_S01_E01.mp4",
      "allowed_targets": ["facebook", "youtube"],
      "platform_metadata": {
        "facebook": {"title": "GENERATION — Tập 01 đầy đủ", "description": "Tập 01 của Biệt Đội AI Nhí."},
        "youtube": {"title": "GENERATION | Tập 01", "description": "Tập đầy đủ số 01.", "category_id": 27, "made_for_kids": true}
      }
    },
    {
      "kind": "short",
      "episode_id": "GEN-S01-E01-H01",
      "media_filename": "GENERATION_S01_E01_H01.mp4",
      "allowed_targets": ["facebook", "youtube"],
      "platform_metadata": {
        "facebook": {"title": "GENERATION | Trích đoạn 01", "description": "Một đoạn ngắn từ tập 01."},
        "youtube": {"title": "GENERATION | Trích đoạn 01", "description": "Highlight của tập 01."}
      }
    }
  ]
}
```

Save this JSON outside the watched folders and set `PUBLISH_MANIFEST=/absolute/path/manifest.json`. Each entry needs a unique explicit `episode_id`, exact `media_filename`, `kind`, `allowed_targets`, and nonempty `platform_metadata` for every target. `kind` is `long` or `short`; metadata accepts per-platform `title` and `description` (YouTube also accepts numeric `category_id` and boolean `made_for_kids`). The configured `FULL_PLATFORMS` or `PLATFORMS` must match that entry's target set exactly. When `PUBLISH_MANIFEST` is empty, the app uses the existing sidecar/AI/filename fallback. With a manifest configured, every scanned/dispatched media file must have a matching manifest entry.

Use `youtube_made_for_kids` **only after assessing the video audience**. If `youtube_title` or `youtube_description` is supplied, both must be supplied and nonempty. These overrides take precedence over AI. Otherwise, with `OPENAI_API_KEY`, the app samples three frames plus optional `.txt` context and generates long-form title/description; it does not transcribe audio, generate thumbnails, create chapters/timestamps, or add to playlists. Without an API key, it derives the title from the filename or the first `.txt` line, and uses the `.txt` content as description. For full episodes, supply a transcript or reviewed metadata to avoid hallucinated summaries.

Commands:

```bash
python publisher.py scan
python publisher.py preview --stream long  # dry-run; uploads NOTHING
python publisher.py preview                # existing short-form preview
# REAL PUBLISHING: after reviewing config, credentials and public Facebook behavior,
# setting ENABLE_LIVE_POSTING=true and FB_ALLOW_PUBLIC_POSTING=true as needed:
python publisher.py run-now --stream long  # posts one long-form video now
python publisher.py status
```

The existing `launchd` job invokes `python publisher.py tick` every five minutes and dispatches **both** independent streams; no second LaunchAgent is needed. An already-dispatched video's fingerprint is never re-queued; moving the exact same file between folders won't post it twice. Long-form can be horizontal even when it is shorter than three minutes, but square/vertical files up to three minutes are rejected to prevent accidental Shorts classification. YouTube supports up to 12 hours or 256 GB per upload (whichever limit comes first); channels need the relevant feature enabled for videos over 15 minutes.

## AI caption setup

Optional: set `OPENAI_API_KEY` to use the OpenAI Responses API. For each **short** video, the app samples **three video frames** using FFmpeg, optionally reads a same-named `.txt` context/transcript, and asks AI to generate **four** items: `title`, `facebook`, `tiktok`, `youtube`. Full-episode AI metadata produces `title`, `youtube` and `facebook` descriptions; a supplied long-form `.json` override bypasses AI. It does **not** transcribe audio automatically. Avoid assuming visual keyframes explain all speech; for talking-head videos, attach a transcript/context file:

```text
inbox/
  video_001.mp4
  video_001.txt              # optional transcript / context
```

Without an API key, captions are derived from the filename or `.txt`, not semantic video analysis. Budget for AI API usage separately.

## TikTok options

### Recommended for personal workflow: automatic preparation, manual Studio scheduling

TikTok's official Direct Post guidelines exclude utilities built solely for the owner's or team's accounts. For this local personal publisher, use `TIKTOK_MODE=manual` instead of assuming that API approval or unattended Android posting is available.

Set `PLATFORMS=facebook,youtube,tiktok` and `TIKTOK_MODE=manual` when ready to include highlights. Keep full episodes restricted to Facebook and YouTube. On each approved short dispatch, the scheduler creates a deterministic local package under `state/tiktok_outbox/dispatch-XXXXXXXX/` with `video.mp4`, `caption.txt` and `review.json` (including the AI-generated-content flag, if supplied). The shared scheduler still requires `ENABLE_LIVE_POSTING=true` and may publish to other configured platforms; use normal preview first. No TikTok network calls, uploads or button presses occur in manual mode. A package is `awaiting_manual`, not published.

Open TikTok Studio (https://www.tiktok.com/tiktokstudio), review the package, select your account, privacy, disclosures (including AI-generated content where appropriate), and manually publish or schedule using the available native features. Once the actual video is visible, record the owner's confirmation:

```bash
python publisher.py tiktok-confirm --dispatch-id 123 --permalink 'https://www.tiktok.com/@account/video/123456789'
```

`published_manual` means the owner recorded the real permalink; the app has not verified it with TikTok. Repeated confirmation with the same URL is safe; a different URL or reuse across jobs is rejected. Existing review packages are immutable to avoid accidental duplicates. Do not delete one after an ambiguous publish without checking TikTok Studio. Files in the default state directory are ignored by Git. If you change the outbox directory, use a local folder outside the repo.

The older Android macro is retained for inspection/legacy reference, but the scheduler no longer executes its unattended publication action. Direct Post is reserved for genuinely eligible reviewed applications with compliant UI; a config flag alone is not approval.

Official guidelines: https://developers.tiktok.com/docs/en/content-sharing-guidelines



### Mode 1: Official Direct Post API (only if your case qualifies)

TikTok Direct Post needs an approved app, `video.publish`, a TikTok OAuth user token, and a user-compliant UX (account identity, preview, privacy selection, interaction settings, disclosure, express consent). This command-line MVP is **not a ready-to-submit compliant TikTok developer app**. Don't enable it solely to bypass TikTok's review process.

For a qualified app/integration, set:

```ini
TIKTOK_MODE=api
TIKTOK_APP_APPROVED=true
TIKTOK_ACCESS_TOKEN=...
```

For each video, the publisher expects a reviewed, manually supplied sidecar:

```json
{
  "tiktok_consent": true,
  "tiktok_privacy_level": "PUBLIC_TO_EVERYONE",
  "disable_comment": false,
  "disable_duet": false,
  "disable_stitch": false,
  "is_aigc": false,
  "brand_content_toggle": false,
  "brand_organic_toggle": false
}
```

The program queries TikTok creator info, checks allowed privacy/duration, initializes `FILE_UPLOAD`, uploads the video in sequential HTTP chunks, and polls posting status on later scheduler ticks. OAuth token refresh is **not yet implemented**; replace expired tokens through your app's standard OAuth lifecycle.

Official references:
- https://developers.tiktok.com/docs/en/content-posting-api-get-started
- https://developers.tiktok.com/docs/en/content-sharing-guidelines
- https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post

### Legacy Android ADB prototype (diagnostics only; live publishing disabled)

If you deliberately choose TikTok UI automation for your own device, test it thoroughly and respect TikTok account restrictions. No app-private data extraction or bypassing security challenges is included.

1. Connect and unlock the spare Android; enable USB debugging. Run `adb devices` and authorize the Mac on the phone.
2. Sign into TikTok, set a consistent UI language and screen resolution, and ensure no popup is showing.
3. Set `TIKTOK_MODE=adb` in `.env`, then run `python publisher.py adb-inspect`. The command saves `state/adb_screen.png` and prints visible UI text/element coordinates.
4. Copy `tiktok_steps.example.json` to `tiktok_steps.json` and **calibrate all selectors and coordinates** for your TikTok version. The included file is deliberately incomplete and **has no final publication action**.
5. A valid final macro must have an `assert_text` guard before a final `{"action":"publish_text","text":"Post"}` step. For a Vietnamese interface that may be `Đăng`. Test on a private/throwaway account before trusting it with public posts.
6. Only after successful manual checks set `ADB_MACRO_APPROVED=true` in `.env`. ADB publication returns `submitted_unverified` because button taps cannot reliably confirm that a post is publicly visible.

To enable manual review or an eligible API integration, change `PLATFORMS=facebook,youtube,tiktok`. ADB posting is disabled in the scheduler. The safe default excludes TikTok.

Supported actions: `sleep`, `tap_text`, `tap_desc`, `tap_xy`, `set_text`, `assert_text`, `publish_text`. `set_text` supports `{caption}` interpolation. ADB pushes media to `/sdcard/Movies/AutoPublisher/`, opens TikTok, then plays the calibrated macro. If a selector is missing, the macro stops and saves a debug screenshot.

## Offline preflight before enabling automatic posting

Run `python publisher.py doctor` to examine local folder paths, ffmpeg binaries, configured targets, OAuth file presence, basic manifest JSON structure, and Facebook's public-post safety flag. It makes **no network calls**, does not refresh OAuth or upload video, never prints secrets, and does not touch SQLite. Warnings in normal mode are informational.

Run `python doctor.py --strict` for a readiness check that exits nonzero when required settings/files are missing, or live publishing is still disabled. **Passing this check does not prove token validity or remote publication.** Test actual platform permissions only with owner approval.

```bash
python publisher.py doctor
python doctor.py --strict
python publisher.py preview --stream long
```

## Run safely

Copy one video into the inbox, then:

```bash
python publisher.py scan       # verify video constraints and deduplicate by SHA256
python publisher.py preview    # show planned caption/platforms; uploads NOTHING
python publisher.py status
python -m unittest discover -s tests -v
```

When credentials are ready, set `ENABLE_LIVE_POSTING=true` in `.env`; Facebook also requires `FB_ALLOW_PUBLIC_POSTING=true`. Start with an isolated test Page/channel and a safe test video. **`run-now` publishes for real** and uses one daily quota slot:

```bash
python publisher.py run-now
python publisher.py status
```

`tick` is the scheduled command. On every invocation it:

1. Scans `VIDEO_DIR` and optionally `FULL_VIDEO_DIR` (old `YT_LONG_VIDEO_DIR` still accepted), rejecting invalid or recently modified videos.
2. Selects at most one undispatched video per due slot **per stream**.
3. Creates/caches platform captions, persists dispatch and per-platform queue rows in SQLite.
4. Attempts each enabled platform. `submitted` means API accepted; `published` is only used after TikTok confirms completion. If uncertain, stops without retrying and sets `needs_check`.
5. On later runs, attempts only `queued`/`blocked` jobs; checks TikTok submitted statuses.

Unchanged files are not re-hashed every five minutes (important for large episodes). If you replace an existing video file before dispatch, the old fingerprint is marked stale and the new content gets a new queue entry; this does **not** authorize re-uploading an already-posted version. Do not move/delete queued video files until all posts are complete.

## Set macOS schedule (every 5 minutes)

```bash
python install_launchd.py
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/local.macreelspublisher.plist"
launchctl print gui/$(id -u)/local.macreelspublisher
```

The job polls every 5 minutes; both schedules use the `.env` timezone (`Asia/Ho_Chi_Minh`). By default, a missed slot is only eligible for 25 minutes; if the Mac sleeps longer, that slot is skipped to prevent a burst of late posts. With `POST_TIMES=09:00,12:00,18:00`, you get **up to 3 short videos/day**, one video dispatched to each enabled short-form destination per slot. The new `FULL_POST_TIMES` and `FULL_POST_DAYS` set the independent full-episode schedule. Adjust daily caps to 1–5 as needed.

Logs: `state/scheduler.log`, `state/scheduler_error.log`; database: `state/publisher.sqlite3`. Optional Telegram alerts via `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

## Common status values

| Status | Meaning | Next action |
|---|---|---|
| `queued` | Ready to try | Automatic at next tick |
| `blocked` | Missing credential/consent/config | Fix setup; next tick will retry preflight |
| `inflight` | Upload started | If app crashed, **manually reconcile** before retry |
| `submitted` | API accepted | Check visibility/processing; TikTok API polled |
| `published` | TikTok reports PUBLISH_COMPLETE | Done |
| `submitted_unverified` | Legacy ADB macro ran | Check TikTok profile |
| `awaiting_manual` | TikTok package prepared locally | Review and publish/schedule in Studio |
| `published_manual` | Owner confirmed TikTok permalink | Not independently API verified |
| `needs_check` | Uncertain after a remote call | Check platform; do not blindly retry |
| `failed` | TikTok reported failure | Check reason; retry only after investigation |

## Scope and future improvements

This is a working integration skeleton, **not verified against your accounts/devices**. API documentation and offline tests do not prove that the live Page/channel grants access or that a post will publish. Full Facebook videos and YouTube videos are polled remotely; highlights do not have a remote Facebook status check in this version. `needs_check` cases require manual reconciliation. For 1–5/day, **SQLite + launchd** is sufficient; n8n and paid orchestration are optional.
