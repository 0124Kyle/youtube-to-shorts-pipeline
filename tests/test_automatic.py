import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.automatic import get_script_footage, run_pipeline
from src.auto_live import render_planned


class OneCommandTests(unittest.TestCase):
    def test_footage_search_uses_ordered_scenes_without_manual_ids_or_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            videos = [
                {"id": i, "duration": 8, "video_files": [{"file_type": "video/mp4", "width": 720,
                 "height": 1280, "link": "https://videos.pexels.com/demo.mp4"}], "url": f"https://www.pexels.com/video/{i}"}
                for i in (11, 22)
            ]
            def download(video, target):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"test video")
                return {"provider": "Pexels", "id": video["id"], "page": video["url"]}

            script = {"candidate_id": "c01", "video_id": "KjAI9r8tnOs",
                      "stock_queries": ["hands doing accounts", "person entering a home"]}
            with patch.dict(os.environ, {"PEXELS_API_KEY": "test-key"}), \
                 patch("src.automatic.pexels_search", return_value=videos) as search, \
                 patch("src.automatic.pexels_download", side_effect=download) as fetched, \
                 patch("src.automatic._duration_video", return_value=8):
                clips = get_script_footage(script, root)
                self.assertEqual([p.name for p in clips], ["pexels_11.mp4", "pexels_22.mp4"])
                self.assertEqual(get_script_footage(script, root), clips)
                self.assertEqual(search.call_count, 2)
                self.assertEqual(fetched.call_count, 2)
            manifest = json.loads((root / "auto-live/KjAI9r8tnOs/c01/footage_sources.json").read_text())
            self.assertEqual([clip["source"]["id"] for clip in manifest["clips"]], [11, 22])

    def test_auto_storyboard_assigns_phrases_without_tag_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script_path = root / "script_c01.json"
            script_path.write_text(json.dumps({"candidate_id": "c01", "video_id": "KjAI9r8tnOs",
                                               "title": "測試", "narration": "甲。乙。丙。丁。",
                                               "source_channel": "來源", "source_url": "https://youtube.com/watch?v=KjAI9r8tnOs",
                                               "source_interval": {"start": 0, "end": 60},
                                               "review_status": "needs_human_review"}))
            clip1, clip2 = root / "first.mp4", root / "second.mp4"
            with patch.dict(os.environ, {"AZURE_SPEECH_KEY": "", "AZURE_SPEECH_REGION": ""}), \
                 patch("src.auto_live._duration_video", return_value=8), \
                 patch("src.auto_live._plan", return_value=root / "storyboard.json") as plan, \
                 patch("src.auto_live.render_live", return_value=(root / "out.mp4", False)):
                render_planned(script_path, [clip1, clip2], root / "work", root / "out", "zh-TW-HsiaoChenNeural", 1.12)
            self.assertEqual(plan.call_args.args[-1], [0, 0, 1, 1])
            self.assertTrue(plan.call_args.kwargs["silent"])

    def test_pipeline_uses_only_current_script_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            url = "https://www.youtube.com/watch?v=KjAI9r8tnOs"
            script = root / "script_c01_new.json"
            script.write_text(json.dumps({"video_id": "KjAI9r8tnOs", "candidate_id": "c01", "title": "測試短片",
                                          "stock_queries": ["one scene", "another scene"]}))
            keys = {"GEMINI_API_KEY": "test", "PEXELS_API_KEY": "test",
                    "AZURE_SPEECH_KEY": "", "AZURE_SPEECH_REGION": ""}
            with patch.dict(os.environ, keys), \
                 patch("src.automatic.transcribe_video", return_value=(root / "transcript.json", False)), \
                 patch("src.automatic.plan_and_generate", return_value=(root / "candidates.json", [script])) as rewrite, \
                 patch("src.automatic.get_script_footage", return_value=[root / "clip.mp4"]) as footage, \
                 patch("src.automatic.render_planned", return_value=(root / "preview.mp4", False)) as render:
                output = run_pipeline(url, root, count=1)
            self.assertEqual(output, [(root / "preview.mp4", False)])
            self.assertEqual(rewrite.call_args.kwargs["top"], 1)
            self.assertEqual(footage.call_count, 1)
            self.assertFalse(render.call_args.kwargs["narrate"])


if __name__ == "__main__":
    unittest.main()
