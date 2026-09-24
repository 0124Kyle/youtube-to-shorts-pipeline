import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from src.rewrite import DEFAULT_MODEL, correct_source_terms, make_candidates, make_prompt, plan_and_generate


class RewriteTests(unittest.TestCase):
    def test_known_policy_errors_are_corrected_only_for_this_source(self):
        spoken = "星期安2.0上路，新加坡政策，親親愛有寬限，新西安還款，新清安，新陳安"
        original = spoken
        corrected, changes = correct_source_terms(spoken, "KjAI9r8tnOs")
        self.assertEqual(corrected, "新青安2.0上路，新青安政策，新青安有寬限，新青安還款，新青安，新青安")
        self.assertEqual(len(changes), 6)
        self.assertEqual(spoken, original)
        self.assertEqual(correct_source_terms(spoken, "some-other-video"), (spoken, []))

    def test_candidate_preserves_raw_transcript_and_marks_corrected_prompt(self):
        spoken = "用新西安貸款，五年後開始還本金。" * 8
        plan = make_candidates([{"start": 0, "end": 60, "text": spoken}], "房貸", 1, "KjAI9r8tnOs")
        candidate = plan["candidates"][0]
        self.assertEqual(candidate["text"], spoken)
        self.assertIn("新青安", candidate["corrected_text"])
        self.assertEqual(candidate["asr_corrections"][0]["occurrences"], 8)
        prompt = make_prompt(candidate, {"title": "房貸", "channel": "頻道", "source_url": "https://example.com"})
        self.assertIn("使用者已確認本片政策名稱", prompt)
        self.assertNotIn("新西安", prompt)

    def test_candidate_plan_spreads_api_calls(self):
        segments = [
            {"start": float(t), "end": float(t + 30), "text": ("台北房貸1000萬元，房價與收入差距。" if t < 300 else "台南安平重劃區房價每坪40萬元。" if t < 600 else "台中房貸負擔率45%，市場變化。") * 3}
            for t in range(0, 900, 30)
        ]
        plan = make_candidates(segments, "房價 房貸 負擔", 3)
        chosen = [next(c for c in plan["candidates"] if c["id"] == key) for key in plan["suggested_ids"]]
        self.assertEqual(len(chosen), 3)
        self.assertEqual(len({"台北" if c["start"] < 300 else "台南" if c["start"] < 600 else "台中" for c in chosen}), 3)

    def test_cached_response_avoids_second_api_call_even_if_json_invalid(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            transcript = base / "transcript.json"
            metadata = base / "metadata.json"
            transcript.write_text(json.dumps({"video_id": "KjAI9r8tnOs", "segments": [
                {"start": float(t), "end": float(t + 30), "text": "台北租屋負擔和購屋預算需要衡量，每個家庭的條件不同。" * 3}
                for t in range(0, 150, 30)
            ]}, ensure_ascii=False), encoding="utf-8")
            metadata.write_text(json.dumps({"video_id": "KjAI9r8tnOs", "source_url": "https://www.youtube.com/watch?v=KjAI9r8tnOs", "channel": "HEALTH 2.0", "title": "房價新聞"}), encoding="utf-8")
            dotenv = types.SimpleNamespace(load_dotenv=lambda: None)
            with patch.dict(sys.modules, {"dotenv": dotenv}), patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
                with patch("src.rewrite.call_gemini", return_value=("{invalid", {"input_tokens": 100, "output_tokens": 30})) as api:
                    with self.assertRaisesRegex(ValueError, "saved for review"):
                        plan_and_generate(transcript, metadata, base / "rewrite", True, top=1)
                    with self.assertRaisesRegex(ValueError, "saved for review"):
                        plan_and_generate(transcript, metadata, base / "rewrite", True, top=1)
                    self.assertEqual(api.call_count, 1)

    def test_output_has_source_and_review_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            transcript, metadata = base / "transcript.json", base / "metadata.json"
            transcript.write_text(json.dumps({"video_id": "KjAI9r8tnOs", "segments": [
                {"start": 0, "end": 60, "text": "台北市有家庭在考慮購屋，先評估收入與貸款負擔。" * 5},
            ]}, ensure_ascii=False), encoding="utf-8")
            metadata.write_text(json.dumps({"video_id": "KjAI9r8tnOs", "source_url": "https://www.youtube.com/watch?v=KjAI9r8tnOs", "channel": "HEALTH 2.0"}), encoding="utf-8")
            draft = json.dumps({"title": "房貸要算清楚", "hook": "買房前你算過未來月付嗎？", "body": "借款1000萬元時，家庭仍要衡量之後每月的還款能力。", "visual_plan": ["計算每月預算的雙手", "走進公寓的背影"], "stock_queries": ["hands using calculator at home", "person entering apartment"], "review_notes": ["數字需回聽"]}, ensure_ascii=False)
            with patch.dict(sys.modules, {"dotenv": types.SimpleNamespace(load_dotenv=lambda: None)}), patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch("src.rewrite.call_gemini", return_value=(draft, {"input_tokens": 300, "output_tokens": 100})) as api:
                _, paths = plan_and_generate(transcript, metadata, base / "rewrite", True, top=1)
                _, again = plan_and_generate(transcript, metadata, base / "rewrite", True, top=1)
                self.assertEqual(paths, again)
                self.assertEqual(api.call_count, 1)
            result = json.loads(paths[0].read_text(encoding="utf-8"))
            self.assertIn("根據 HEALTH 2.0 發布的報導", result["narration"])
            self.assertEqual(result["review_status"], "needs_human_review")
            self.assertTrue(any("數字" in note for note in result["review_notes"]))
            self.assertIsNotNone(result["estimated_paid_equivalent_usd"])
            self.assertEqual(result["model"], DEFAULT_MODEL)


if __name__ == "__main__":
    unittest.main()
