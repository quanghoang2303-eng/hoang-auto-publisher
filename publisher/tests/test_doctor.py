import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import doctor


class DoctorTests(unittest.TestCase):
    def test_targets_reject_invalid_and_duplicate(self):
        with self.assertRaises(ValueError):
            doctor.parse_targets("facebook,facebook", {"facebook", "youtube"}, "PLATFORMS")
        with self.assertRaises(ValueError):
            doctor.parse_targets("youtube,tiktok", {"facebook", "youtube"}, "FULL_PLATFORMS")

    def test_readonly_without_any_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("doctor.shutil.which", return_value="/usr/bin/ffprobe"):
                findings = doctor.report({"VIDEO_DIR": tmp, "PLATFORMS": "facebook,youtube", "FULL_VIDEO_DIR": "", "ENABLE_LIVE_POSTING": "false"}, Path(tmp))
            self.assertFalse(any(x.severity == "FAIL" for x in findings))
            self.assertTrue(any(x.name == "FB_PAGE_ACCESS_TOKEN" and x.severity == "WARN" for x in findings))
            self.assertTrue(any(x.name == "ENABLE_LIVE_POSTING" and x.severity == "WARN" for x in findings))

    def test_strict_catches_unsafe_unconfigured_publishing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("doctor.shutil.which", return_value="/usr/bin/ffprobe"):
                findings = doctor.report({"VIDEO_DIR": tmp, "PLATFORMS": "facebook,youtube", "ENABLE_LIVE_POSTING": "true"}, Path(tmp), strict=True)
            failures = {x.name for x in findings if x.severity == "FAIL"}
            self.assertIn("FB_PAGE_ACCESS_TOKEN", failures)
            self.assertIn("YT_TOKEN_FILE", failures)
            self.assertIn("FB_ALLOW_PUBLIC_POSTING", failures)

    def test_redacts_configured_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("doctor.shutil.which", return_value="/usr/bin/ffprobe"):
                findings = doctor.report({"VIDEO_DIR": tmp, "PLATFORMS": "facebook", "FB_PAGE_ID": "private_page_id", "FB_PAGE_ACCESS_TOKEN": "verysecretvalue", "FB_ALLOW_PUBLIC_POSTING": "true", "ENABLE_LIVE_POSTING": "true"}, Path(tmp))
            printable = " ".join(x.explanation for x in findings)
            self.assertNotIn("verysecretvalue", printable)
            self.assertNotIn("private_page_id", printable)

    def test_manifest_uses_json_without_running_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text(json.dumps({"videos": [{"media_filename": "episode.mp4", "kind": "long", "allowed_targets": ["facebook", "youtube"]}]}))
            with patch("doctor.shutil.which", return_value="/usr/bin/ffmpeg"):
                findings = doctor.report({"VIDEO_DIR": tmp, "PLATFORMS": "facebook", "PUBLISH_MANIFEST": "manifest.json"}, root)
            self.assertTrue(any(x.name == "PUBLISH_MANIFEST" and x.severity == "OK" for x in findings))
            (root / "manifest.json").write_text("invalid json")
            with patch("doctor.shutil.which", return_value="/usr/bin/ffmpeg"):
                broken = doctor.report({"VIDEO_DIR": tmp, "PLATFORMS": "facebook", "PUBLISH_MANIFEST": "manifest.json"}, root)
            self.assertTrue(any(x.name == "PUBLISH_MANIFEST" and x.severity == "FAIL" for x in broken))

    def test_youtube_oauth_files_are_checked_locally(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "token.json").write_text('{"refresh_token":"secretvalue"}')
            (root / "client_secret.json").write_text('{"installed":{"client_id":"id"}}')
            with patch("doctor.shutil.which", return_value="/usr/bin/ffmpeg"):
                findings = doctor.report({"VIDEO_DIR": tmp, "PLATFORMS": "youtube"}, root)
            self.assertTrue(any(x.name == "YT_TOKEN_FILE" and x.severity == "OK" for x in findings))
            self.assertNotIn("secretvalue", repr(findings))


if __name__ == "__main__":
    unittest.main()