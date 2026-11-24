# Task 1 report — publisher reliability

## Completed
- Replaced full-episode Facebook multipart buffering with the Page Videos resumable start/transfer/finish flow. Chunk size, file size, and duration have validated configuration settings.
- Persisted Facebook upload session, last acknowledged offset, and remote video ID in additive SQLite columns. Restart resumes a known partial transfer; an interrupted transfer at end-of-file moves to `needs_check` to avoid repeating an uncertain finish. Reconciliation can inspect known Facebook IDs in submitted or needs-check states.
- Added an independent `FB_ALLOW_PUBLIC_POSTING=true` gate for Facebook Reels and Page Videos, in addition to the global live-posting flag.
- Added YouTube remote status checks. A private processed video remains submitted; failed processing is recorded as failed.
- Added optional JSON manifest validation for episode ID, stream kind, media filename, allowed targets, and per-target metadata. Legacy directory/env scanning remains enabled when no manifest is configured.
- Added additive migrations and SQLite connections that close when used as context managers. Removed requests-toolbelt because the publisher no longer uses multipart encoding.
- Added offline coverage for migration, connection close, manifest validation, restart quarantine, Facebook chunk offsets, YouTube private status, and existing routing/deduplication behavior.

## Verification
- `git diff --check`: passed.
- `PYTHONPATH=/private/tmp/auto-publisher-test-stubs python3 -m unittest discover -s tests -v`: 26 tests passed. The temporary stub only supplies `dotenv.load_dotenv`; the host has no `python` executable and does not have python-dotenv installed, so the exact brief command could not run in this environment. No upload calls were made by tests.
- The first attempt using `python3 -m unittest ...` without the stub failed at import because `dotenv` is absent.

## Concerns / limitations
- The environment prevented validating the live Meta/YouTube API protocol. Network behavior and provider-specific status fields remain unverified offline.
- If Facebook FINISH times out after the remote video ID/session are saved, the job remains `needs_check`; it will reconcile by the remote video ID and will not create a second post.

## Fix round 1 — blind review findings

- Manifest platform fields now override caption fallbacks at the Facebook FINISH request and YouTube `videos.insert` body. YouTube manifest metadata can set title, description, numeric category, and `made_for_kids`; absent fields continue using sidecar captions and environment category/audience settings.
- Manifest validation rejects path-bearing media filenames and validates supplied title, description, category, and audience field values.
- Facebook now validates persisted offsets and provider `start_offset`/`end_offset` against the media size, the submitted chunk boundary, and forward progress. It sends FINISH only after the confirmed offset reaches the exact file size.
- Focused tests in `publisher/tests/test_core.py` verify manifest metadata reaches both platform API payloads, and malformed provider offsets or an out-of-range saved offset stop before FINISH/network use.
- Exact command: `PYTHONPATH=/private/tmp/auto-publisher-test-stubs python3 -m unittest discover -s tests -v` (run from `publisher`). Output: `Ran 28 tests in 0.091s` and `OK`. The temporary stub provides only `dotenv.load_dotenv`, absent from the host Python environment. No live upload was attempted.
