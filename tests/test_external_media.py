import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.external_media import azure_speech, pexels_download, pexels_search


class ExternalMediaTests(unittest.TestCase):
    def test_pexels_search_uses_portrait_filter_and_cached_response(self):
        payload = {"videos": [{"id": 12, "duration": 8, "video_files": []}]}
        with tempfile.TemporaryDirectory() as folder, patch("src.external_media._open", return_value=io.BytesIO(json.dumps(payload).encode())) as fetch:
            first = pexels_search("home calculator", "secret", Path(folder))
            second = pexels_search("home calculator", "secret", Path(folder))
            self.assertEqual(first, second)
            self.assertEqual(fetch.call_count, 1)
            request = fetch.call_args.args[0]
            self.assertIn("orientation=portrait", request.full_url)
            self.assertEqual(request.get_header("Authorization"), "secret")
            self.assertNotIn("secret", next(Path(folder).glob("*.json")).read_text())

    def test_reviewed_pexels_download_rejects_unexpected_host(self):
        video = {"video_files": [{"file_type": "video/mp4", "width": 720, "height": 1280,
                                  "link": "https://untrusted.example.net/fake.mp4"}]}
        with self.assertRaisesRegex(ValueError, "unexpected media host"):
            pexels_download(video, Path("ignored.mp4"))

    def test_azure_phrase_escapes_ssml_and_never_writes_secret(self):
        with tempfile.TemporaryDirectory() as folder, patch("src.external_media._open", return_value=io.BytesIO(b"mp3 bytes")) as fetch:
            output = Path(folder) / "phrase.mp3"
            azure_speech("房貸 & 生活", output, "private-key", "eastasia")
            self.assertEqual(output.read_bytes(), b"mp3 bytes")
            request = fetch.call_args.args[0]
            self.assertIn("房貸 &amp; 生活".encode(), request.data)
            self.assertEqual(request.get_header("Ocp-apim-subscription-key"), "private-key")
            self.assertNotIn("private-key", output.read_text(encoding="utf-8", errors="ignore"))

    def test_azure_free_tier_rate_limit_can_resume(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch("src.external_media._open", side_effect=[RuntimeError("HTTP 429"), io.BytesIO(b"audio")]) as fetch, \
             patch("src.external_media.time.sleep") as wait:
            output = Path(folder) / "phrase.mp3"
            azure_speech("你好", output, "private-key", "eastasia")
            self.assertEqual(output.read_bytes(), b"audio")
            self.assertEqual(fetch.call_count, 2)
            wait.assert_called_once_with(60)


if __name__ == "__main__":
    unittest.main()
