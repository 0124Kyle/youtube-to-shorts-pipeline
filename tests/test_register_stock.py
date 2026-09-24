import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from register_stock import register


class RegisterStockTests(unittest.TestCase):
    def test_reviewed_video_is_registered_once_and_tags_can_be_extended(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "reviewed.mp4"
            source.write_bytes(b"reviewed video bytes")
            source.with_suffix(".source.json").write_text('{"provider":"Pexels"}', encoding="utf-8")
            catalog = root / "assets" / "catalog.json"
            catalog.parent.mkdir()
            catalog.write_text('{"clips":[]}', encoding="utf-8")
            with patch("register_stock._duration_video", return_value=6.0):
                target = register(source, ["房貸"], catalog)
                self.assertEqual(register(source, ["月付"], catalog), target)
            contents = json.loads(catalog.read_text(encoding="utf-8"))
            self.assertEqual(len(contents["clips"]), 1)
            self.assertEqual(contents["clips"][0]["tags"], ["房貸", "月付"])
            self.assertEqual(json.loads(target.with_suffix(".source.json").read_text())["provider"], "Pexels")


if __name__ == "__main__":
    unittest.main()
