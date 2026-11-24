# Final fix report

## Changes
- Removed the committed internal artifact `.superpowers/sdd/auto-publisher-v3/task-1-report.md` from the branch.
- Added bounded retries for Facebook Page Video transfer timeouts, connection errors, chunked-response errors, and temporary HTTP statuses (408, 425, 429, 500, 502, 503, 504). Default: 3 retries; `FB_UPLOAD_CHUNK_RETRIES` accepts 0–10.
- Repeated transfer requests use the same upload session and byte offset. Returned offsets are validated before checkpoint advancement.
- After retries exhaust, a known session with an incomplete durable checkpoint returns to `queued`; the next scheduler run resumes that same session. Ambiguous `FINISH` remains `needs_check`; `FINISH` is not retried.
- Updated README, changelog, Vietnamese operations guide, and `.env.example`.

## Checks
- Standard command `python3 -m unittest discover -s tests -v`: could not import because `python-dotenv` is absent from the environment.
- Offline suite with an in-memory `dotenv.load_dotenv` stub: `Ran 30 tests ... OK`.
- `git diff --check`: passed.
- Root Pages check `git diff --quiet -- index.html privacy.html terms.html styles.css`: exit 0 (untouched).
- Artifact check `test ! -e .superpowers/sdd/auto-publisher-v3/task-1-report.md`: exit 0.
- No live publishing or external account upload performed.

## Re-review fix
- The failure handler now reads the durable Facebook session and offset back from SQLite after the callback fails, so a session created on the current attempt qualifies for safe queue-and-resume.
- Added regression coverage for first-run START saving a session, exhausted chunk retries returning the row to `queued`, and the following run reusing that session through successful FINISH without issuing another START.
- Focused command: `PYTHONPATH=tests python3 -m unittest test_core.PublisherTests.test_facebook_first_run_retry_exhaustion_queues_saved_session_and_resumes` with an in-memory `dotenv.load_dotenv` stub: `Ran 1 test ... OK`.
- Full offline suite with the same stub: `Ran 31 tests ... OK`.
- `git diff --check`: passed. No live post performed.
