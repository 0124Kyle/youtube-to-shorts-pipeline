import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.pipeline import run
from src.youtube import parse_video_id


ID = "KjAI9r8tnOs"
URL = f"https://www.youtube.com/watch?v={ID}"


class PipelineTests(unittest.TestCase):
    def test_accepts_video_urls_and_rejects_lookalikes(self):
        self.assertEqual(parse_video_id(URL), ID)
        self.assertEqual(parse_video_id(f"https://youtu.be/{ID}?t=10"), ID)
        self.assertEqual(parse_video_id(f"https://www.youtube.com/shorts/{ID}"), ID)
        for bad in ("https://youtube.com.evil.test/watch?v=" + ID, "file:///etc/passwd", "https://www.youtube.com/playlist?list=x", "https://www.youtube.com/watch?v=bad", "https://www.youtube.com/watch?v=" + ID + "&v=" + ID):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_video_id(bad)

    def test_repeat_uses_cache_and_changed_settings_reuses_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)

            def fake_download(video_id, directory):
                audio = directory / "audio.webm"
                audio.write_bytes(b"test audio")
                return audio, {"video_id": video_id, "source_url": URL, "title": "Demo"}

            fake_text = {"language": "en", "language_probability": 0.9, "segments": [{"start": 0.1, "end": 0.9, "text": "Hello"}]}
            with patch("src.pipeline.download_audio", side_effect=fake_download) as download, patch("src.pipeline.transcribe", return_value=fake_text) as stt:
                path, cached = run(URL, base)
                self.assertFalse(cached)
                self.assertEqual(json.loads(path.read_text())["segments"][0]["start"], 0.1)
                self.assertTrue(run(URL, base)[1])
                self.assertFalse(run(URL, base, model="medium")[1])
                self.assertFalse(run(URL, base, model="medium", force=True)[1])
                self.assertEqual(download.call_count, 1)
                self.assertEqual(stt.call_count, 3)

    def test_failed_transcription_is_not_cached(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / ID
            directory.mkdir()
            (directory / "audio.m4a").write_bytes(b"test audio")
            with patch("src.pipeline.transcribe", side_effect=RuntimeError("bad audio")):
                with self.assertRaisesRegex(RuntimeError, "bad audio"):
                    run(URL, Path(temp))
            self.assertFalse((directory / "transcript.json").exists())


if __name__ == "__main__":
    unittest.main()
