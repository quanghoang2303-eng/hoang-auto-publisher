# Mac Auto Publisher V3 — Tập đầy đủ (Facebook + YouTube) và highlight (Reels + Shorts)

**Bắt đầu bằng:** `HUONG_DAN_V3_VIDEO_DAI_VA_HIGHLIGHT.md` (tiếng Việt).

Run two independent local queues: 1–5 daily vertical **highlights** to Facebook **Page** Reels / YouTube Shorts (TikTok optional), plus scheduled **full episodes** to both Facebook Page Videos and YouTube regular videos from a separate folder. The Mac scheduler (`launchd`) processes both queues in one process. This is an MVP, not a hosted service.

## Important limitations

- **TikTok:** TikTok's Content Posting API guidelines explicitly reject personal/internal uploader utilities as eligible API clients and require that users preview/control/consent to what is posted. Public Direct Post is gated behind review. A per-video JSON flag in this MVP is only a technical guard, **not a substitute for TikTok-compliant UX/review**. Assume `TIKTOK_MODE=off` unless your use case qualifies. Android ADB relies on UI automation and may violate platform terms or break after app updates; test with a separate account, and never bypass security challenges.
- **Facebook:** The Page must be controlled by a person with the `CREATE_CONTENT` task; use a valid Page Access Token with `pages_manage_posts`, `pages_read_engagement`, `pages_show_list` as applicable, plus app review/access if required. The Reel Publishing API accepts a video for processing and may not instantly display it publicly.
- **YouTube:** `videos.insert` works for both Shorts and regular videos with the same `youtube.upload` scope. Square/vertical videos up to 3 minutes are usually Shorts; the shared short-form queue deliberately accepts only 4–60 seconds and 9:16. Long-form accepts landscape videos, or square/vertical videos **longer than 3 minutes**. YouTube OAuth token authorization is a one-time interactive action, refresh may require renewed permission.
- ADB cannot guarantee publication from a button press. Its result is `submitted_unverified`; verify the TikTok profile occasionally.
- Videos containing third-party music can trigger copyright restrictions. Do not treat successful upload as proof that the video is public or monetizable.
- Mac must be **awake**, connected to the Internet and (for ADB) to an unlocked Android device. A sleeping Mac will miss scheduled windows.
- YouTube resumable uploads retry temporary chunk errors up to 3 times **during the same process**. No automatic re-upload after an ambiguous crash/network failure: `needs_check` means manually inspect the platform before retrying. This avoids accidental duplicates; it does not provide mathematical exactly-once delivery.

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

Back up your existing `mac-reels-publisher/state/`, `.env`, `token.json`, and `client_secret.json` before replacing code. Copy the **code and `.env.example`**, not the existing state or secrets, from the new ZIP into the existing project folder; add the new `FULL_*` options to your existing `.env` without overwriting the original credentials; old `YT_LONG_*` keys remain compatible. The first run migrates the SQLite `videos` table by adding `kind='short'` to existing entries. Existing dispatches, status history, and deduplication fingerprints are preserved. Do not run two separate copies of the same project against the same SQLite database.

## Facebook Page setup

1. Go to [Meta for Developers](https://developers.facebook.com/), create/select an app with Page functionality. Request the appropriate Page permissions, and check app review/business verification requirements for your account.
2. Obtain a **Page Access Token**, not merely a user token, from the authorized Page. Have the `CREATE_CONTENT` Page task and required Page permissions.
3. Set `FB_PAGE_ID` and `FB_PAGE_ACCESS_TOKEN` in `.env`.
4. For **highlights** the code uses `/{page_id}/video_reels` (`START`, upload, `FINISH`). For **full episodes** it uses `POST /{page_id}/videos` with streamed multipart `source`, `title` and `description`; default 1 GB safety cap via `FB_FULL_MAX_BYTES` (no resumable implementation yet). Facebook may display both as Reels due to its 2025 video unification.

Meta official resources:
- https://developers.facebook.com/docs/graph-api/reference/page/video_reels
- https://developers.facebook.com/docs/graph-api/reference/page/videos/
- https://www.postman.com/meta/facebook/documentation/r56bjfd/facebook-api



### V3: Important Facebook behavior

Meta announced in June 2025 that all Facebook videos are shared as Reels regardless of length or orientation. Thus `full_episodes/` versus `inbox/` is a **workflow/marketing distinction**, not a promise of distinct Facebook UI post types. Use `FULL_PLATFORMS=facebook,youtube` only after testing the Page token and posting a non-sensitive episode. See `HUONG_DAN_V3_VIDEO_DAI_VA_HIGHLIGHT.md` for Mac setup, per-platform metadata, migration and safety steps.

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

The **separate** full-episode queue is enabled when `FULL_VIDEO_DIR` (or the old `YT_LONG_VIDEO_DIR`) is set. `FULL_POST_TIMES` is independent of Shorts' `POST_TIMES`; `FULL_POST_DAYS` accepts `mon,tue,wed,thu,fri,sat,sun` (blank means daily). Its daily cap is `FULL_MAX_DAILY_POSTS` (1–5). `FULL_PLATFORMS=facebook,youtube` sends a distinct post job to each destination. **For safe upgrades from V2, the default without FULL_PLATFORMS is youtube only.** TikTok is never a full-episode destination. If both streams trigger at the same minute, the single scheduler handles highlights first and full episodes second.

Facebook Page Videos uses a multipart upload for files within `FB_FULL_MAX_BYTES` (default 1,000,000,000 bytes). Meta's asynchronous response is not proof of public visibility; check the Page. Files above the cap are blocked **before upload**. For large files, implement/resume Meta's chunked upload API rather than increasing the cap blindly. The Facebook full-episode status is polled and only reported as `published` if Meta explicitly confirms publication. Meta's post-2025 product may label both long episodes and highlights as Reels.

Start with `YT_LONG_PRIVACY=private` until a complete upload is confirmed in YouTube Studio, then change it to `public` for unattended publishing. `YT_LONG_CATEGORY_ID` defaults to `27` (Education) and `YT_MADE_FOR_KIDS` applies to both queues unless overridden per-video; decide the audience accurately for your actual film (cartoon does not automatically mean made for kids, but child-directed material requires the correct setting).

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
  "youtube_title": "GENERATION - Tập 01 | Học cách dẫn dắt AI",
  "youtube_description": "Giới thiệu tập 01 của series giáo dục AI. Đăng ký để xem tập tiếp theo.",
  "youtube_made_for_kids": true
}
```

Use `youtube_made_for_kids` **only after assessing the video audience**. If `youtube_title` or `youtube_description` is supplied, both must be supplied and nonempty. These overrides take precedence over AI. Otherwise, with `OPENAI_API_KEY`, the app samples three frames plus optional `.txt` context and generates long-form title/description; it does not transcribe audio, generate thumbnails, create chapters/timestamps, or add to playlists. Without an API key, it derives the title from the filename or the first `.txt` line, and uses the `.txt` content as description. For full episodes, supply a transcript or reviewed metadata to avoid hallucinated summaries.

Commands:

```bash
python publisher.py scan
python publisher.py preview --stream long  # dry-run; uploads NOTHING
python publisher.py preview                # existing short-form preview
# After reviewing config, credentials, and enabling live posting:
python publisher.py run-now --stream long  # publishes one long-form video now
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

### Mode 2: Android ADB prototype (UI experimental)

If you deliberately choose TikTok UI automation for your own device, test it thoroughly and respect TikTok account restrictions. No app-private data extraction or bypassing security challenges is included.

1. Connect and unlock the spare Android; enable USB debugging. Run `adb devices` and authorize the Mac on the phone.
2. Sign into TikTok, set a consistent UI language and screen resolution, and ensure no popup is showing.
3. Set `TIKTOK_MODE=adb` in `.env`, then run `python publisher.py adb-inspect`. The command saves `state/adb_screen.png` and prints visible UI text/element coordinates.
4. Copy `tiktok_steps.example.json` to `tiktok_steps.json` and **calibrate all selectors and coordinates** for your TikTok version. The included file is deliberately incomplete and **has no final publication action**.
5. A valid final macro must have an `assert_text` guard before a final `{"action":"publish_text","text":"Post"}` step. For a Vietnamese interface that may be `Đăng`. Test on a private/throwaway account before trusting it with public posts.
6. Only after successful manual checks set `ADB_MACRO_APPROVED=true` in `.env`. ADB publication returns `submitted_unverified` because button taps cannot reliably confirm that a post is publicly visible.

To activate either TikTok mode, also change `PLATFORMS=facebook,youtube,tiktok`. The safe default excludes TikTok until it is configured.

Supported actions: `sleep`, `tap_text`, `tap_desc`, `tap_xy`, `set_text`, `assert_text`, `publish_text`. `set_text` supports `{caption}` interpolation. ADB pushes media to `/sdcard/Movies/AutoPublisher/`, opens TikTok, then plays the calibrated macro. If a selector is missing, the macro stops and saves a debug screenshot.

## Run safely

Copy one video into the inbox, then:

```bash
python publisher.py scan       # verify video constraints and deduplicate by SHA256
python publisher.py preview    # show planned caption/platforms; uploads NOTHING
python publisher.py status
python -m unittest discover -s tests -v
```

When credentials are ready, set `ENABLE_LIVE_POSTING=true` in `.env` and start with an isolated test Page/channel. **`run-now` publishes for real** and uses one daily quota slot:

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
| `submitted_unverified` | ADB macro ran | Check TikTok profile |
| `needs_check` | Uncertain after a remote call | Check platform; do not blindly retry |
| `failed` | TikTok reported failure | Check reason; retry only after investigation |

## Scope and future improvements

This is a working integration skeleton, **not battle-tested against your accounts/devices**. To move to production: implement token rotation and secrets storage, genuine per-video TikTok UI/compliance if API approval is possible, robust remote post status checks for Facebook/YouTube, alerts and recovery CLI for `needs_check`, database backup, and Mac sleep/power recovery. For 1–5/day, **SQLite + launchd** is sufficient; n8n and paid orchestration are optional.