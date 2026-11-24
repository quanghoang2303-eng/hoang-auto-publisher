import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tiktok_outbox as outbox
from backends import PreflightError


class TikTokOutboxTests(unittest.TestCase):
    def test_package_is_idempotent_and_contains_manifest_caption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "highlight.mp4"
            video.write_bytes(b"sample bytes")
            h = hashlib.sha256(video.read_bytes()).hexdigest()
            meta = {"episode_id": "E01-H01", "is_aigc": True,
                    "manifest_platform_metadata": {"tiktok": {"description": "Tiếng Việt"}}}
            a = outbox.prepare(video, {"tiktok": "fallback"}, meta, 1, h, root=root / "out")
            b = outbox.prepare(video, {"tiktok": "fallback"}, meta, 1, h, root=root / "out")
            self.assertEqual(a, b)
            self.assertEqual(a[0], "awaiting_manual")
            folder = Path(a[1])
            self.assertEqual((folder / "caption.txt").read_text(), "Tiếng Việt\n")
            self.assertTrue(json.loads((folder / "review.json").read_text())["is_aigc"])
            self.assertEqual(len(list((root / "out").iterdir())), 1)

    def test_changed_asset_or_caption_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "highlight.mp4"
            video.write_bytes(b"a")
            h = hashlib.sha256(b"a").hexdigest()
            outbox.prepare(video, {"tiktok": "one"}, {}, 1, h, root=root / "out")
            with self.assertRaises(PreflightError):
                outbox.prepare(video, {"tiktok": "two"}, {}, 1, h, root=root / "out")
            video.write_bytes(b"b")
            with self.assertRaises(PreflightError):
                outbox.prepare(video, {"tiktok": "one"}, {}, 1, h, root=root / "out")

    def test_missing_disclosure_not_silently_set_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "clip.mp4"
            video.write_bytes(b"a")
            _, dest = outbox.prepare(video, {"tiktok": "caption"}, {}, 1, hashlib.sha256(b"a").hexdigest(), root=root / "out")
            self.assertIsNone(json.loads((Path(dest) / "review.json").read_text())["is_aigc"])

    def test_confirm_url_validation(self):
        for url in ("https://example.com/@x/video/123", "https://www.tiktok.com.evil.test/@x/video/123",
                    "http://www.tiktok.com/@x/video/123", "https://www.tiktok.com/@x"):
            with self.assertRaises(PreflightError):
                outbox.checked_post_url(url)
        self.assertEqual(outbox.checked_post_url("https://www.tiktok.com/@x/video/123?foo=x"), "https://www.tiktok.com/@x/video/123")

    def test_confirmation_is_idempotent_and_rejects_duplicate_url(self):
        with sqlite3.connect(":memory:") as con:
            con.row_factory = sqlite3.Row
            con.execute("CREATE TABLE posts(dispatch_id INTEGER,platform TEXT,status TEXT,remote_id TEXT,error TEXT,updated_at TEXT)")
            con.executemany("INSERT INTO posts VALUES (?,'tiktok','awaiting_manual',NULL,NULL,'now')", [(1,), (2,)])
            url = "https://www.tiktok.com/@x/video/123"
            outbox.confirm(con, 1, url)
            outbox.confirm(con, 1, url)
            self.assertEqual(con.execute("SELECT status FROM posts WHERE dispatch_id=1").fetchone()[0], "published_manual")
            with self.assertRaises(PreflightError):
                outbox.confirm(con, 2, url)
            with self.assertRaises(PreflightError):
                outbox.confirm(con, 1, "https://www.tiktok.com/@x/video/999")
            self.assertEqual(con.execute("SELECT status FROM posts WHERE dispatch_id=2").fetchone()[0], "awaiting_manual")


if __name__ == "__main__":
    unittest.main()
