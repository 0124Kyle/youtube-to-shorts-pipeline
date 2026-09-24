import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.auto_live import _choose_clips
from src.live import _caption_layout, _caption_overlay


class AutoFootageSelectionTests(unittest.TestCase):
    def test_long_chinese_caption_wraps_and_renders(self):
        caption = "年輕人的購屋選擇與整體房市版圖也面臨重塑。"
        lines, size = _caption_layout(caption)
        self.assertEqual("".join(lines), caption)
        self.assertEqual(len(lines), 2)
        self.assertGreaterEqual(size, 32)
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "caption.png"
            _caption_overlay(caption, output)
            self.assertTrue(output.is_file())

    def test_unrelated_location_script_is_not_filled_with_generic_loan_footage(self):
        clips = [("keys.mp4", ["買房", "鑰匙"], 10), ("calculator.mp4", ["房貸", "月付"], 10)]
        phrases = ["台南安平的新案增加，", "港灣景觀成為賣點。", "房貸也要考量。", "還有當地房價變化。"]
        with self.assertRaisesRegex(ValueError, "matches only 1/4"):
            _choose_clips(phrases, clips)

    def test_matching_story_selects_footage_without_external_lookup(self):
        clips = [("keys.mp4", ["鑰匙"], 10), ("calculator.mp4", ["房貸"], 10)]
        self.assertEqual(_choose_clips(["拿到鑰匙，", "簽下房貸。"], clips), [0, 1])


if __name__ == "__main__":
    unittest.main()
