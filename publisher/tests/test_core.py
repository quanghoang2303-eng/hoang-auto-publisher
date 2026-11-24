import json
import os
from datetime import datetime
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from requests.exceptions import Timeout
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import publisher
import backends
from backends import PreflightError
from tiktok_adb import validate_macro


class PublisherTests(unittest.TestCase):
    def test_due_window_and_missed_slot(self):
        with patch.dict(os.environ, {"POST_TIMES": "09:00,12:00,18:00", "MISSED_SLOT_GRACE_MINUTES": "25"}):
            zone = ZoneInfo("Asia/Ho_Chi_Minh")
            self.assertEqual(publisher.due(datetime(2026, 11, 18, 9, 10, tzinfo=zone)), ["09:00"])
            self.assertEqual(publisher.due(datetime(2026, 11, 18, 9, 26, tzinfo=zone)), [])
            self.assertEqual(publisher.due(datetime(2026, 11, 18, 17, 30, tzinfo=zone)), [])

    def test_invalid_slots_and_platforms(self):
        with patch.dict(os.environ, {"POST_TIMES": "09:00,09:00"}):
            with self.assertRaises(ValueError):
                publisher.slots()
        with patch.dict(os.environ, {"PLATFORMS": "youtube,tiktok,tiktok"}):
            with self.assertRaises(ValueError):
                publisher.platforms()
        with patch.dict(os.environ, {"YT_LONG_POST_TIMES": "19:00,19:00"}):
            with self.assertRaises(ValueError):
                publisher.slots("long")
        with patch.dict(os.environ, {"YT_LONG_POST_DAYS": "mon,unknown"}):
            with self.assertRaises(ValueError):
                publisher.long_post_days()

    def test_dispatch_deduplicates_video_and_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video = root / "sample.mp4"
            video.write_bytes(b"example-test-media")
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            connection.executescript("""
              CREATE TABLE videos(id INTEGER PRIMARY KEY,fingerprint TEXT UNIQUE,path TEXT,title_hint TEXT,created_at TEXT,
                kind TEXT DEFAULT 'short',stale INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE dispatches(id INTEGER PRIMARY KEY,slot_key TEXT UNIQUE,video_id INTEGER UNIQUE,day TEXT,caption_json TEXT,metadata_json TEXT,created_at TEXT);
              CREATE TABLE posts(dispatch_id INTEGER,platform TEXT,status TEXT,remote_id TEXT,error TEXT,updated_at TEXT,PRIMARY KEY(dispatch_id,platform));
            """)
            connection.execute("INSERT INTO videos(fingerprint,path,title_hint,created_at) VALUES (?,?,?,?)",
                               (publisher.file_fingerprint(video), str(video), "sample", "now"))
            fake_caption = {"title": "x", "facebook": "x", "youtube": "x", "tiktok": "x"}
            fixed = datetime(2026, 11, 18, 9, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
            with patch.object(publisher, "validate", return_value={"duration_seconds": 20}), \
                    patch.object(publisher, "make_caption", return_value=fake_caption), \
                    patch.dict(os.environ, {"MAX_DAILY_POSTS": "5", "PLATFORMS": "facebook,youtube"}):
                publisher.create_dispatch(connection, "2026-11-18-09:00", fixed)
                publisher.create_dispatch(connection, "2026-11-18-09:00", fixed)
                publisher.create_dispatch(connection, "2026-11-18-12:00", fixed)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM dispatches").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 2)
            connection.close()

    def test_long_form_validation_avoids_accidental_shorts(self):
        sample = Path("episode.mp4")
        with patch.object(publisher, "probe", return_value={"duration_seconds": 600, "width": 1920, "height": 1080}):
            self.assertEqual(publisher.validate(sample, "long")["duration_seconds"], 600)
            with self.assertRaises(ValueError):
                publisher.validate(sample, "short")
        with patch.object(publisher, "probe", return_value={"duration_seconds": 120, "width": 1080, "height": 1920}):
            with self.assertRaisesRegex(ValueError, "are Shorts"):
                publisher.validate(sample, "long")
        with patch.object(publisher, "probe", return_value={"duration_seconds": 181, "width": 1080, "height": 1920}):
            publisher.validate(sample, "long")
        with patch.object(publisher, "probe", return_value={"duration_seconds": 120, "width": 1920, "height": 1080}):
            publisher.validate(sample, "long")

    def test_long_schedule_independent_of_shorts(self):
        zone = ZoneInfo("Asia/Ho_Chi_Minh")
        monday = datetime(2026, 11, 23, 19, 5, tzinfo=zone)
        tuesday = datetime(2026, 11, 24, 19, 5, tzinfo=zone)
        with patch.dict(os.environ, {"POST_TIMES": "09:00", "YT_LONG_POST_TIMES": "19:00",
                                     "YT_LONG_POST_DAYS": "mon,wed,fri"}):
            self.assertEqual(publisher.due(monday, "long"), ["19:00"])
            self.assertEqual(publisher.due(tuesday, "long"), [])
            self.assertEqual(publisher.due(monday, "short"), [])
            self.assertEqual(publisher.platforms("long"), ["youtube"])

    def test_database_migrates_existing_short_jobs_without_erasure(self):
        with tempfile.TemporaryDirectory() as folder:
            db_file = Path(folder) / "old.sqlite3"
            with sqlite3.connect(db_file) as connection:
                connection.executescript("""
                  CREATE TABLE videos(id INTEGER PRIMARY KEY,fingerprint TEXT NOT NULL UNIQUE,path TEXT NOT NULL,
                    title_hint TEXT NOT NULL,created_at TEXT NOT NULL);
                  CREATE TABLE dispatches(id INTEGER PRIMARY KEY,slot_key TEXT NOT NULL UNIQUE,
                    video_id INTEGER NOT NULL UNIQUE,day TEXT NOT NULL,caption_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,created_at TEXT NOT NULL);
                  CREATE TABLE posts(dispatch_id INTEGER NOT NULL,platform TEXT NOT NULL,status TEXT NOT NULL,
                    remote_id TEXT,error TEXT,updated_at TEXT NOT NULL,
                    PRIMARY KEY(dispatch_id,platform));
                  INSERT INTO videos(fingerprint,path,title_hint,created_at) VALUES ('oldhash','old.mp4','old','now');
                """)
            with patch.object(publisher, "DATABASE", db_file), publisher.db() as connection:
                row = connection.execute("SELECT kind,fingerprint FROM videos").fetchone()
                self.assertEqual(tuple(row), ("short", "oldhash"))
                self.assertIn("kind", [col[1] for col in connection.execute("PRAGMA table_info(videos)")])
                self.assertIn("mtime_ns", [col[1] for col in connection.execute("PRAGMA table_info(videos)")])
                self.assertIn("upload_session", [col[1] for col in connection.execute("PRAGMA table_info(posts)")])
                self.assertIn("upload_offset", [col[1] for col in connection.execute("PRAGMA table_info(posts)")])
            self.assertIsNotNone(connection)
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")

    def test_manifest_rejects_stream_or_target_mismatch(self):
        entry = {"kind":"long", "media_filename":"episode.mp4", "episode_id":"ep-1",
                 "allowed_targets":["youtube"], "platform_metadata":{"youtube":{"category":"27"}}}
        self.assertEqual(publisher.validate_manifest_entry(entry, "long", "episode.mp4"), entry)
        with self.assertRaisesRegex(ValueError, "mismatch"):
            publisher.validate_manifest_entry(entry, "short", "episode.mp4")
        entry["platform_metadata"] = {}
        with self.assertRaisesRegex(ValueError, "platform_metadata"):
            publisher.validate_manifest_entry(entry, "long", "episode.mp4")

    def test_quarantine_resumes_known_partial_session_only(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(publisher, "DATABASE", Path(folder)/"db.sqlite3"):
            with publisher.db() as con:
                con.execute("INSERT INTO videos(fingerprint,path,title_hint,created_at,kind,file_size) VALUES ('h','x','x','now','long',100)")
                con.execute("INSERT INTO dispatches(slot_key,video_id,day,caption_json,metadata_json,created_at) VALUES ('k',1,'d','{}','{}','now')")
                con.execute("INSERT INTO posts(dispatch_id,platform,status,upload_session,upload_offset,updated_at) VALUES (1,'facebook','inflight','sess',40,'now')")
                con.execute("INSERT INTO posts(dispatch_id,platform,status,upload_session,upload_offset,updated_at) VALUES (1,'youtube','inflight',NULL,0,'now')")
                publisher.quarantine_interrupted_uploads(con)
                statuses = dict((r["platform"],r["status"]) for r in con.execute("SELECT platform,status FROM posts"))
                self.assertEqual(statuses, {"facebook":"queued", "youtube":"needs_check"})

    def test_youtube_processed_private_video_is_not_reported_published(self):
        class FakeVideos:
            def list(self, **kwargs):
                return self
            def execute(self):
                return {"items":[{"status":{"uploadStatus":"processed","privacyStatus":"private"},
                                  "processingDetails":{"processingStatus":"succeeded"}}]}
        class FakeClient:
            def videos(self): return FakeVideos()
        with patch.object(backends, "youtube_client", return_value=FakeClient()):
            self.assertEqual(backends.youtube_video_status("yt-private"), "submitted")

    def test_rescan_skips_unchanged_large_file_and_requeues_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shorts = root / "shorts"
            shorts.mkdir()
            video = shorts / "sample.mp4"
            video.write_bytes(b"content-v1")
            with patch.object(publisher, "DATABASE", root / "test.sqlite3"), \
                 patch.object(publisher, "validate", return_value={"duration_seconds": 10}), \
                 patch.dict(os.environ, {"VIDEO_DIR": str(shorts), "YT_LONG_VIDEO_DIR": "",
                                      "MIN_FILE_AGE_SECONDS": "0"}):
                with publisher.db() as connection:
                    self.assertEqual(publisher.scan(connection), 1)
                    with patch.object(publisher, "file_fingerprint", side_effect=AssertionError("should not rehash")):
                        self.assertEqual(publisher.scan(connection), 0)
                    video.write_bytes(b"content-v2-with-new-length")
                    self.assertEqual(publisher.scan(connection), 1)
                    rows = connection.execute("SELECT stale,fingerprint FROM videos ORDER BY id").fetchall()
                    self.assertEqual([row["stale"] for row in rows], [1, 0])

    def test_queue_routing_and_caps_are_isolated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shorts, longs = root / "shorts", root / "youtube_long"
            shorts.mkdir()
            longs.mkdir()
            (shorts / "short1.mp4").write_bytes(b"short-unique")
            (longs / "episode.mp4").write_bytes(b"long-unique")
            test_db = root / "queue.sqlite3"
            fixed = datetime(2026, 11, 23, 19, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
            def fake_validate(path, kind="short"):
                return {"duration_seconds": 600 if kind == "long" else 20, "width": 1920, "height": 1080}
            with patch.object(publisher, "DATABASE", test_db), \
                 patch.object(publisher, "validate", side_effect=fake_validate), \
                 patch.object(publisher, "make_caption", return_value={"title": "x", "youtube": "x", "facebook": "x", "tiktok": "x"}), \
                 patch.dict(os.environ, {"VIDEO_DIR": str(shorts), "YT_LONG_VIDEO_DIR": str(longs),
                                      "MIN_FILE_AGE_SECONDS": "0", "MAX_DAILY_POSTS": "1",
                                      "YT_LONG_MAX_DAILY_POSTS": "1", "PLATFORMS": "facebook,youtube"}):
                with publisher.db() as connection:
                    self.assertEqual(publisher.scan(connection), 2)
                    publisher.create_dispatch(connection, "2026-11-23-19:00", fixed, "short")
                    publisher.create_dispatch(connection, "yt-long:2026-11-23-19:00", fixed, "long")
                    publisher.create_dispatch(connection, "yt-long:2026-11-23-19:05", fixed, "long")
                    posts = connection.execute("""SELECT v.kind,p.platform FROM posts p
                        JOIN dispatches d ON d.id=p.dispatch_id
                        JOIN videos v ON v.id=d.video_id ORDER BY v.kind,p.platform""").fetchall()
                    self.assertEqual([tuple(row) for row in posts],
                                     [("long", "youtube"), ("short", "facebook"), ("short", "youtube")])
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM dispatches").fetchone()[0], 2)

    def test_long_caption_no_shorts_tag_and_manual_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "episode_01.mp4"
            video.write_bytes(b"placeholder")
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                caption = publisher.make_caption(video, {"duration_seconds": 600}, "long")
                self.assertEqual(caption["title"], "episode 01")
                self.assertNotIn("#Shorts", caption["youtube"])
                video.with_suffix(".json").write_text(json.dumps({
                    "youtube_title": "Tập 1 — Học dẫn dắt AI",
                    "youtube_description": "Nội dung series Generation", "youtube_made_for_kids": True
                }), encoding="utf-8")
                caption = publisher.make_caption(video, {"duration_seconds": 600}, "long")
                self.assertEqual(caption["title"], "Tập 1 — Học dẫn dắt AI")
                self.assertEqual(caption["youtube"], "Nội dung series Generation")

    def test_youtube_long_upload_uses_separate_privacy_and_kids_metadata(self):
        captured = {}

        class FakeUpload:
            def __init__(self, path, mimetype, resumable, chunksize):
                captured["path"] = path
                captured["resumable"] = resumable

        class FakeRequest:
            def next_chunk(self, num_retries):
                captured["num_retries"] = num_retries
                return None, {"id": "remote-episode-01"}

        class FakeYouTube:
            def videos(self):
                return self

            def insert(self, part, body, media_body):
                captured["body"] = body
                return FakeRequest()

        http_module = types.ModuleType("googleapiclient.http")
        http_module.MediaFileUpload = FakeUpload
        package_module = types.ModuleType("googleapiclient")
        package_module.http = http_module
        with patch.dict(sys.modules, {"googleapiclient": package_module, "googleapiclient.http": http_module}), \
             patch.object(backends, "youtube_client", return_value=FakeYouTube()), \
             patch.dict(os.environ, {"YT_PRIVACY": "public", "YT_LONG_PRIVACY": "private",
                                      "YT_LONG_CATEGORY_ID": "27", "YT_MADE_FOR_KIDS": "false"}):
            result = backends.youtube_publish(Path("episode.mp4"),
                    {"title": "Episode 01", "youtube": "Nội dung dài"}, kind="long",
                    metadata={"youtube_made_for_kids": True, "manifest_platform_metadata": {
                        "youtube": {"title":"Manifest title", "description":"Manifest description",
                                    "category_id":"24", "made_for_kids":False}}})
        self.assertEqual(result, ("submitted", "remote-episode-01"))
        self.assertEqual(captured["body"]["status"], {"privacyStatus": "private", "selfDeclaredMadeForKids": False})
        self.assertEqual(captured["body"]["snippet"], {"title":"Manifest title", "description":"Manifest description", "categoryId":"24"})
        self.assertTrue(captured["resumable"])
        self.assertEqual(captured["num_retries"], 3)

    def test_manual_long_publish_does_not_flush_queued_short_posts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video_long = root / "long.mp4"
            video_short = root / "short.mp4"
            video_long.write_bytes(b"long")
            video_short.write_bytes(b"short")
            with patch.object(publisher, "DATABASE", root / "test.sqlite3"):
                with publisher.db() as connection:
                    for kind, video in (("long", video_long), ("short", video_short)):
                        connection.execute("INSERT INTO videos(fingerprint,path,title_hint,created_at,kind) "
                                           "VALUES (?,?,?,?,?)", (publisher.file_fingerprint(video), str(video), kind, "now", kind))
                        video_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
                        connection.execute("INSERT INTO dispatches(slot_key,video_id,day,caption_json,metadata_json,created_at) "
                                           "VALUES (?,?,?,?,?,?)", (kind, video_id, "2026-11-23",
                                           json.dumps({"title": kind, "youtube": kind, "facebook": kind}),
                                           json.dumps({"duration_seconds": 200}), "now"))
                        dispatch_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
                        connection.execute("INSERT INTO posts(dispatch_id,platform,status,updated_at) VALUES (?,?,?,?)",
                                           (dispatch_id, "youtube", "queued", "now"))
                    connection.commit()
                    with patch.object(backends, "youtube_client"), \
                         patch.object(backends, "youtube_publish", return_value=("submitted", "remote1")) as mock_upload, \
                         patch.object(publisher, "send_notice"):
                        publisher.publish_pending(connection, "long")
                    mock_upload.assert_called_once()
                    self.assertEqual(mock_upload.call_args.kwargs["kind"], "long")
                    rows = connection.execute("""SELECT v.kind,p.status FROM posts p
                         JOIN dispatches d ON d.id=p.dispatch_id JOIN videos v ON v.id=d.video_id
                         ORDER BY v.kind""").fetchall()
                    self.assertEqual([tuple(row) for row in rows],
                                     [("long", "submitted"), ("short", "queued")])

    def test_adb_macro_fails_closed_without_approval(self):
        with patch.dict(os.environ, {"ADB_MACRO_APPROVED": "false"}):
            with self.assertRaises(PreflightError):
                validate_macro()

    def test_tiktok_sidecar_loading(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            file = root / "example.mp4"
            file.write_bytes(b"fake")
            (root / "example.json").write_text(json.dumps({"tiktok_consent": True}))
            self.assertEqual(publisher.read_metadata(file), {"tiktok_consent": True})

    def test_tiktok_ok_response_with_extra_fields(self):
        class Response:
            def raise_for_status(self):
                return None
            def json(self):
                return {"data": {"publish_id": "abc"}, "error": {"code": "ok", "message": ""}}
        self.assertEqual(backends.checked(Response())["data"]["publish_id"], "abc")

    def test_stale_inflight_is_never_retried_automatically(self):
        with sqlite3.connect(":memory:") as con:
            con.execute("CREATE TABLE posts(status TEXT,error TEXT,updated_at TEXT)")
            con.execute("INSERT INTO posts(status) VALUES ('inflight')")
            publisher.quarantine_interrupted_uploads(con)
            self.assertEqual(con.execute("SELECT status FROM posts").fetchone()[0], "needs_check")

    def test_v3_full_platform_routing_defaults_safe_and_opt_in(self):
        with patch.dict(os.environ, {"FULL_PLATFORMS": "youtube"}):
            self.assertEqual(publisher.platforms("long"), ["youtube"])
        with patch.dict(os.environ, {"FULL_PLATFORMS": "facebook,youtube"}):
            self.assertEqual(publisher.platforms("long"), ["facebook", "youtube"])
        with patch.dict(os.environ, {"FULL_PLATFORMS": "facebook,tiktok"}):
            with self.assertRaises(ValueError):
                publisher.platforms("long")
        with patch.dict(os.environ, {"FULL_PLATFORMS": "facebook,facebook"}):
            with self.assertRaises(ValueError):
                publisher.platforms("long")

    def test_v3_full_caption_has_separate_facebook_text(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "GENERATION_E01.mp4"
            video.write_bytes(b"sample")
            sidecar = video.with_suffix(".json")
            sidecar.write_text(json.dumps({
                "youtube_title": "Tập 01 — Học cùng AI",
                "youtube_description": "YouTube full episode description",
                "facebook_title": "GENERATION | Tập 01",
                "facebook_description": "Nội dung Facebook riêng",
            }, ensure_ascii=False), encoding="utf-8")
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                captions = publisher.make_caption(video, {"duration_seconds": 480}, "long")
            self.assertEqual(captions["title"], "Tập 01 — Học cùng AI")
            self.assertEqual(captions["facebook_title"], "GENERATION | Tập 01")
            self.assertEqual(captions["facebook"], "Nội dung Facebook riêng")
            self.assertNotIn("#Shorts", captions["facebook"])

    def test_v3_facebook_video_upload_is_resumable_and_chunked(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "episode.mp4"
            video.write_bytes(b"1234567890")
            class Response:
                def __init__(self, body): self.body = body
                def raise_for_status(self): pass
                def json(self): return self.body
            replies = [Response({"upload_session_id":"sess1","video_id":"fb-episode-42","start_offset":"0","end_offset":"4"}),
                       Response({"start_offset":"4","end_offset":"8"}), Response({"start_offset":"8","end_offset":"10"}),
                       Response({"start_offset":"10","end_offset":"10"}),
                       Response({"video_id":"fb-episode-42"})]
            saved = []
            with patch.dict(os.environ, {"FB_PAGE_ACCESS_TOKEN":"fake-private-token", "FB_PAGE_ID":"12345",
                    "FB_GRAPH_VERSION":"v27.0", "FB_FULL_MAX_BYTES":"1000", "FB_ALLOW_PUBLIC_POSTING":"true",
                    "FB_UPLOAD_CHUNK_BYTES":"4"}), patch.object(backends.requests, "post", side_effect=replies) as request:
                status, ident = backends.facebook_video_publish(video,
                    {"title":"YouTube title", "facebook_title":"Fallback FB title", "youtube":"YouTube description", "facebook":"Fallback FB description"},
                    metadata={"manifest_platform_metadata":{"facebook":{"title":"Manifest FB title","description":"Manifest FB description"}}},
                    upload_state={}, save_state=lambda session, offset, video_id=None: saved.append((session,offset,video_id)))
            self.assertEqual((status, ident), ("submitted", "fb-episode-42"))
            self.assertEqual(request.call_count, 5)
            self.assertEqual(request.call_args_list[0].kwargs["data"]["upload_phase"], "start")
            self.assertEqual([call.kwargs["data"]["start_offset"] for call in request.call_args_list[1:3]], ["0", "4"])
            self.assertEqual(request.call_args_list[-1].kwargs["data"]["upload_phase"], "finish")
            self.assertEqual(request.call_args_list[-1].kwargs["data"]["title"], "Manifest FB title")
            self.assertEqual(request.call_args_list[-1].kwargs["data"]["description"], "Manifest FB description")
            self.assertEqual(saved[-1], ("sess1", 10, "fb-episode-42"))

    def test_facebook_retries_timed_out_chunk_at_same_offset(self):
        class Response:
            def __init__(self, body): self.body = body
            def raise_for_status(self): pass
            def json(self): return self.body
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "episode.mp4"
            video.write_bytes(b"1234")
            replies = [Response({"upload_session_id":"sess","video_id":"fb-1","start_offset":"0","end_offset":"4"}),
                       Timeout("response lost after acceptance"),
                       Response({"start_offset":"4","end_offset":"4"}),
                       Response({"video_id":"fb-1"})]
            with patch.dict(os.environ, {"FB_PAGE_ACCESS_TOKEN":"test", "FB_PAGE_ID":"1",
                    "FB_ALLOW_PUBLIC_POSTING":"true", "FB_UPLOAD_CHUNK_BYTES":"4"}), \
                 patch.object(backends.requests, "post", side_effect=replies) as request:
                status, ident = backends.facebook_video_publish(video, {"title":"T", "youtube":"Y"})
            self.assertEqual((status, ident), ("submitted", "fb-1"))
            transfer_calls = [c for c in request.call_args_list if c.kwargs.get("data", {}).get("upload_phase") == "transfer"]
            self.assertEqual(len(transfer_calls), 2)
            self.assertEqual([c.kwargs["data"]["start_offset"] for c in transfer_calls], ["0", "0"])
            self.assertEqual([c.kwargs["data"]["upload_session_id"] for c in transfer_calls], ["sess", "sess"])

    def test_facebook_exhausted_chunk_retries_returns_queued_for_same_session(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video = root / "episode.mp4"
            video.write_bytes(b"1234")
            with patch.object(publisher, "DATABASE", root / "db.sqlite3"), \
                 patch.dict(os.environ, {"FB_PAGE_ID":"1", "FB_PAGE_ACCESS_TOKEN":"test",
                    "FB_ALLOW_PUBLIC_POSTING":"true", "FB_UPLOAD_CHUNK_BYTES":"4", "FB_UPLOAD_CHUNK_RETRIES":"0"}), \
                 publisher.db() as con:
                con.execute("INSERT INTO videos(fingerprint,path,title_hint,created_at,kind,file_size) VALUES (?,?,?,?,?,?)",
                            (publisher.file_fingerprint(video), str(video), "ep", "now", "long", 4))
                con.execute("INSERT INTO dispatches(slot_key,video_id,day,caption_json,metadata_json,created_at) VALUES (?,?,?,?,?,?)",
                            ("full:today", 1, "today", json.dumps({"title":"T","facebook":"F","youtube":"Y"}),
                             json.dumps({"duration_seconds":10}), "now"))
                con.execute("INSERT INTO posts(dispatch_id,platform,status,upload_session,upload_offset,updated_at) VALUES (1,'facebook','queued','sess',0,'now')")
                con.commit()
                def request(url, data, timeout):
                    if data["upload_phase"] == "transfer": raise backends.Timeout("lost response")
                    raise AssertionError("saved session must avoid START and FINISH")
                with patch.object(backends.requests, "post", side_effect=request), patch.object(publisher, "send_notice"):
                    publisher.publish_pending(con, "long")
                    row = con.execute("SELECT status,upload_session,upload_offset FROM posts WHERE platform='facebook'").fetchone()
                self.assertEqual(tuple(row), ("queued", "sess", 0))

    def test_facebook_first_run_retry_exhaustion_queues_saved_session_and_resumes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video = root / "episode.mp4"
            video.write_bytes(b"12345678")
            with patch.object(publisher, "DATABASE", root / "db.sqlite3"), \
                 patch.dict(os.environ, {"FB_PAGE_ID":"1", "FB_PAGE_ACCESS_TOKEN":"test",
                    "FB_ALLOW_PUBLIC_POSTING":"true", "FB_UPLOAD_CHUNK_BYTES":"4", "FB_UPLOAD_CHUNK_RETRIES":"0"}), \
                 publisher.db() as con:
                con.execute("INSERT INTO videos(fingerprint,path,title_hint,created_at,kind,file_size) VALUES (?,?,?,?,?,?)",
                            (publisher.file_fingerprint(video), str(video), "ep", "now", "long", 8))
                con.execute("INSERT INTO dispatches(slot_key,video_id,day,caption_json,metadata_json,created_at) VALUES (?,?,?,?,?,?)",
                            ("full:today", 1, "today", json.dumps({"title":"T","facebook":"F","youtube":"Y"}),
                             json.dumps({"duration_seconds":10}), "now"))
                con.execute("INSERT INTO posts(dispatch_id,platform,status,updated_at) VALUES (1,'facebook','queued','now')")
                con.commit()
                start_response = types.SimpleNamespace(
                    raise_for_status=lambda: None,
                    json=lambda: {"upload_session_id":"new-session","video_id":"fb-1","start_offset":"0","end_offset":"4"})
                def first_run_request(url, data, timeout):
                    if data["upload_phase"] == "start": return start_response
                    if data["upload_phase"] == "transfer": raise backends.Timeout("lost chunk response")
                    raise AssertionError("FINISH must not be called after failed transfer")
                with patch.object(backends.requests, "post", side_effect=first_run_request), \
                     patch.object(publisher, "send_notice"):
                    publisher.publish_pending(con, "long")
                row = con.execute("SELECT status,upload_session,upload_offset FROM posts WHERE platform='facebook'").fetchone()
                self.assertEqual(tuple(row), ("queued", "new-session", 0))

                def resumed_request(url, data, timeout):
                    if data["upload_phase"] == "transfer":
                        self.assertEqual(data["upload_session_id"], "new-session")
                        if data["start_offset"] == "0":
                            return types.SimpleNamespace(raise_for_status=lambda: None,
                                json=lambda: {"start_offset":"4","end_offset":"8"})
                        self.assertEqual(data["start_offset"], "4")
                        return types.SimpleNamespace(raise_for_status=lambda: None,
                            json=lambda: {"start_offset":"8","end_offset":"8"})
                    if data["upload_phase"] == "finish":
                        return types.SimpleNamespace(raise_for_status=lambda: None,
                            json=lambda: {"video_id":"fb-1"})
                    raise AssertionError("resume must not create a second upload session")
                with patch.object(backends.requests, "post", side_effect=resumed_request) as resumed, \
                     patch.object(publisher, "send_notice"):
                    publisher.publish_pending(con, "long")
                self.assertEqual([call.kwargs["data"]["upload_phase"] for call in resumed.call_args_list],
                                 ["transfer", "transfer", "finish"])
                final = con.execute("SELECT status,upload_session,upload_offset FROM posts WHERE platform='facebook'").fetchone()
                self.assertEqual(tuple(final), ("submitted", "new-session", 8))

    def test_facebook_rejects_bad_provider_offsets_without_finishing(self):
        class Response:
            def __init__(self, body): self.body = body
            def raise_for_status(self): pass
            def json(self): return self.body
        scenarios = [
            [Response({"upload_session_id":"s","start_offset":"0","end_offset":"11"})],
            [Response({"upload_session_id":"s","start_offset":"0","end_offset":"4"}),
             Response({"start_offset":"3","end_offset":"8"})],
            [Response({"upload_session_id":"s","start_offset":"0","end_offset":"4"}),
             Response({"start_offset":"4","end_offset":"11"})],
            [Response({"upload_session_id":"s","start_offset":"0","end_offset":"4"}),
             Response({"start_offset":"2","end_offset":"4"})],
        ]
        for replies in scenarios:
            with self.subTest(replies=replies), tempfile.TemporaryDirectory() as folder:
                video = Path(folder) / "episode.mp4"
                video.write_bytes(b"0123456789")
                with patch.dict(os.environ, {"FB_PAGE_ACCESS_TOKEN":"test", "FB_PAGE_ID":"1",
                        "FB_ALLOW_PUBLIC_POSTING":"true", "FB_UPLOAD_CHUNK_BYTES":"4"}), \
                     patch.object(backends.requests, "post", side_effect=replies) as request:
                    with self.assertRaises(RuntimeError):
                        backends.facebook_video_publish(video, {"title":"T","youtube":"Y"})
                    self.assertFalse(any(call.kwargs.get("data", {}).get("upload_phase") == "finish"
                                         for call in request.call_args_list))

    def test_facebook_rejects_out_of_range_saved_offset_before_network(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "episode.mp4"
            video.write_bytes(b"123")
            with patch.dict(os.environ, {"FB_PAGE_ACCESS_TOKEN":"test", "FB_PAGE_ID":"1",
                    "FB_ALLOW_PUBLIC_POSTING":"true"}), patch.object(backends.requests, "post") as request:
                with self.assertRaisesRegex(PreflightError, "Saved Facebook upload offset"):
                    backends.facebook_video_publish(video, {"title":"T","youtube":"Y"},
                                                    upload_state={"session_id":"s","offset":4})
                request.assert_not_called()

    def test_v3_facebook_video_upload_rejects_large_file_before_api(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "huge.mp4"
            video.write_bytes(b"too-long")
            with patch.dict(os.environ, {"FB_PAGE_ACCESS_TOKEN": "fake", "FB_PAGE_ID": "123",
                                      "FB_FULL_MAX_BYTES": "4"}), \
                 patch.object(backends.requests, "post") as mock_post:
                with self.assertRaisesRegex(PreflightError, "safety limit"):
                    backends.facebook_video_publish(video, {"title": "x", "facebook": "x"})
                mock_post.assert_not_called()

    def test_v3_full_dispatch_creates_both_posts_and_publishes_each_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            episode = root / "episode.mp4"
            episode.write_bytes(b"genuine-for-test-only")
            with patch.object(publisher, "DATABASE", root / "db.sqlite3"), \
                 patch.object(publisher, "validate", return_value={"duration_seconds": 480}), \
                 patch.dict(os.environ, {"FULL_PLATFORMS": "facebook,youtube", "FB_PAGE_ID": "testpage",
                                      "FB_PAGE_ACCESS_TOKEN": "fake-token", "FB_ALLOW_PUBLIC_POSTING": "true", "FULL_MAX_DAILY_POSTS": "1"}):
                with publisher.db() as con:
                    con.execute("INSERT INTO videos(fingerprint,path,title_hint,created_at,kind) VALUES (?,?,?,?,?)",
                                (publisher.file_fingerprint(episode), str(episode), "episode", "now", "long"))
                    with patch.object(publisher, "make_caption", return_value={
                        "title": "Tập 01", "facebook_title": "FB Tập 01", "facebook": "Tập 01 đầy đủ",
                        "youtube": "YouTube description"}), \
                         patch.object(backends, "youtube_client"), \
                         patch.object(backends, "facebook_video_publish", return_value=("submitted", "fb123")) as fb_call, \
                         patch.object(backends, "youtube_publish", return_value=("submitted", "yt123")) as yt_call, \
                         patch.object(publisher, "send_notice"):
                        fixed = datetime(2026, 11, 23, 19, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
                        publisher.create_dispatch(con, "full:2026-11-23-19:00", fixed, "long")
                        publisher.publish_pending(con, "long")
                        publisher.publish_pending(con, "long")
                    fb_call.assert_called_once()
                    yt_call.assert_called_once()
                    results = con.execute("SELECT platform,status,remote_id FROM posts ORDER BY platform").fetchall()
                    self.assertEqual([tuple(r) for r in results], [
                        ("facebook", "submitted", "fb123"), ("youtube", "submitted", "yt123")])

    def test_v3_fb_long_failure_never_retries_or_blocks_youtube(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            episode = root / "episode.mp4"
            episode.write_bytes(b"example")
            with patch.object(publisher, "DATABASE", root / "db.sqlite3"), \
                 patch.dict(os.environ, {"FB_PAGE_ID": "123", "FB_PAGE_ACCESS_TOKEN": "fake", "FB_ALLOW_PUBLIC_POSTING": "true"}):
                with publisher.db() as con:
                    con.execute("INSERT INTO videos(fingerprint,path,title_hint,created_at,kind) VALUES (?,?,?,?,?)",
                                (publisher.file_fingerprint(episode), str(episode), "ep", "now", "long"))
                    con.execute("INSERT INTO dispatches(slot_key,video_id,day,caption_json,metadata_json,created_at) "
                                "VALUES (?,?,?,?,?,?)", ("full:today", 1, "2026-11-23",
                                json.dumps({"title": "Ep", "facebook": "text", "youtube": "text"}),
                                json.dumps({"duration_seconds": 480}), "now"))
                    con.executemany("INSERT INTO posts(dispatch_id,platform,status,updated_at) VALUES (1,?,?,?)",
                                    [("facebook", "queued", "now"), ("youtube", "queued", "now")])
                    con.commit()
                    with patch.object(backends, "facebook_video_publish", side_effect=RuntimeError("upload uncertain")) as fb, \
                         patch.object(backends, "youtube_client"), \
                         patch.object(backends, "youtube_publish", return_value=("submitted", "yt-1")) as yt, \
                         patch.object(publisher, "send_notice"):
                        publisher.publish_pending(con, "long")
                        publisher.publish_pending(con, "long")
                    fb.assert_called_once()
                    yt.assert_called_once()
                    actual = dict((r["platform"], r["status"]) for r in con.execute("SELECT platform,status FROM posts"))
                    self.assertEqual(actual, {"facebook": "needs_check", "youtube": "submitted"})

    def test_v3_facebook_full_status_only_marks_published_on_confirmation(self):
        class Resp:
            def __init__(self, body):
                self.body = body
            def raise_for_status(self):
                pass
            def json(self):
                return self.body
        with patch.dict(os.environ, {"FB_PAGE_ACCESS_TOKEN": "fake"}):
            for response_data, expected in [
                ({"status": {"video_status": "processing"}}, "submitted"),
                ({"status": {"video_status": "ready"}}, "submitted"),
                ({"status": {"publishing_phase": {"publish_status": "published"}}}, "published"),
                ({"is_published": True}, "published"),
                ({"status": {"video_status": "error"}}, "failed"),
            ]:
                with patch.object(backends.requests, "get", return_value=Resp(response_data)) as call:
                    self.assertEqual(backends.facebook_video_status("fb987"), expected)
                    self.assertIn("/fb987", call.call_args.args[0])

    def test_v3_preflight_oversize_keeps_job_blocked_before_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            episode = root / "episode.mp4"
            episode.write_bytes(b"0123456789")
            with patch.object(publisher, "DATABASE", root / "db.sqlite3"), \
                 patch.dict(os.environ, {"FB_PAGE_ID": "123", "FB_PAGE_ACCESS_TOKEN": "fake",
                                      "FB_FULL_MAX_BYTES": "5", "FB_ALLOW_PUBLIC_POSTING": "true"}):
                with publisher.db() as con:
                    con.execute("INSERT INTO videos(fingerprint,path,title_hint,created_at,kind) VALUES (?,?,?,?,?)",
                                (publisher.file_fingerprint(episode), str(episode), "ep", "now", "long"))
                    con.execute("INSERT INTO dispatches(slot_key,video_id,day,caption_json,metadata_json,created_at) "
                                "VALUES (?,?,?,?,?,?)", ("full:today", 1, "2026-11-23",
                                json.dumps({"title": "Ep", "facebook": "text", "youtube": "text"}),
                                json.dumps({"duration_seconds": 480}), "now"))
                    con.execute("INSERT INTO posts(dispatch_id,platform,status,updated_at) VALUES (1,'facebook','queued','now')")
                    con.commit()
                    with patch.object(backends, "facebook_video_publish") as call:
                        publisher.publish_pending(con, "long")
                        call.assert_not_called()
                    self.assertEqual(con.execute("SELECT status FROM posts").fetchone()[0], "blocked")


if __name__ == "__main__":
    unittest.main()
