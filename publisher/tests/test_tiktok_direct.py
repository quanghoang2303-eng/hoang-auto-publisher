import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backends
import tiktok_oauth


def response(access="access", refresh="refresh", open_id="creator"):
    return {"access_token": access, "refresh_token": refresh, "open_id": open_id,
            "scope": "user.info.basic,video.publish", "expires_in": 3600, "refresh_expires_in": 86400}


class TikTokDirectTests(unittest.TestCase):
    def test_refresh_rotates_token_and_persists_privately(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tt.json"
            tiktok_oauth.save(path, tiktok_oauth.normalize(response(), now=0))
            fake = Mock()
            fake.json.return_value = response("new", "rotated")
            with patch.dict(os.environ, {"TIKTOK_TOKEN_FILE": str(path), "TIKTOK_CLIENT_KEY": "key",
                                       "TIKTOK_CLIENT_SECRET": "secret"}), patch.object(tiktok_oauth.requests, "post", return_value=fake):
                self.assertEqual(tiktok_oauth.access_token(now=3601), "new")
            self.assertEqual(tiktok_oauth.load(path)["refresh_token"], "rotated")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_reject_changed_creator_and_missing_scope(self):
        old = tiktok_oauth.normalize(response(), now=0)
        with self.assertRaises(backends.PreflightError):
            tiktok_oauth.normalize(response(open_id="other"), previous=old)
        bad = response()
        bad["scope"] = "user.info.basic"
        with self.assertRaises(backends.PreflightError):
            tiktok_oauth.normalize(bad)

    def metadata(self, video):
        return {"tiktok_consent": True, "tiktok_creator_username": "creator",
                "tiktok_reviewed_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                "tiktok_reviewed_caption": "Reviewed caption", "tiktok_privacy_level": "SELF_ONLY",
                "disable_comment": True, "disable_duet": True, "disable_stitch": True,
                "brand_content_toggle": False, "brand_organic_toggle": False, "is_aigc": True,
                "duration_seconds": 30}

    def test_missing_consent_or_audit_blocks_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = Path(tmp) / "v.mp4"
            v.write_bytes(b"video")
            meta = self.metadata(v)
            with patch.dict(os.environ, {"ENABLE_LIVE_POSTING": "true", "TIKTOK_APP_APPROVED": "false"}):
                with self.assertRaises(backends.PreflightError):
                    backends.tiktok_direct_review(v, meta)
            with patch.dict(os.environ, {"ENABLE_LIVE_POSTING": "true", "TIKTOK_APP_APPROVED": "true"}):
                meta["tiktok_consent"] = False
                with self.assertRaises(backends.PreflightError):
                    backends.tiktok_direct_review(v, meta)

    def test_review_hash_and_explicit_flags(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"ENABLE_LIVE_POSTING": "true", "TIKTOK_APP_APPROVED": "true"}):
            v = Path(tmp) / "v.mp4"
            v.write_bytes(b"video")
            meta = self.metadata(v)
            self.assertEqual(backends.tiktok_direct_review(v, meta)["title"], "Reviewed caption")
            meta["is_aigc"] = "false"
            with self.assertRaises(backends.PreflightError):
                backends.tiktok_direct_review(v, meta)
            meta["is_aigc"] = True
            v.write_bytes(b"modified")
            with self.assertRaises(backends.PreflightError):
                backends.tiktok_direct_review(v, meta)

    def test_persist_publish_id_before_upload_and_require_201(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"ENABLE_LIVE_POSTING": "true", "TIKTOK_APP_APPROVED": "true"}):
            v = Path(tmp) / "v.mp4"
            v.write_bytes(b"video")
            events = []
            creator = {"creator_username": "creator", "privacy_level_options": ["SELF_ONLY"], "max_video_post_duration_sec": 60}
            init = {"publish_id": "post-1", "upload_url": "https://upload.us.tiktokapis.com/video/?secret=abc"}
            def put(*args, **kwargs):
                events.append("upload")
                result = Mock(status_code=201)
                return result
            with patch.object(tiktok_oauth, "access_token", return_value="token"), \
                    patch.object(backends, "_tiktok_json", side_effect=[creator, init]) as api, \
                    patch.object(backends.requests, "put", side_effect=put):
                status, pid = backends.tiktok_api_publish(v, {}, self.metadata(v), lambda x: events.append(x))
            self.assertEqual((status, pid), ("submitted", "post-1"))
            self.assertEqual(events, ["post-1", "upload"])
            self.assertEqual(api.call_args_list[-1].args[1]["post_info"]["title"], "Reviewed caption")


if __name__ == "__main__":
    unittest.main()
