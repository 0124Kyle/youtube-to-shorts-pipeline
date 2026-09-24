import contextlib
import io
import os
import sys
import types
import unittest
from unittest.mock import patch

import check_models


class ModelListingTests(unittest.TestCase):
    def test_lists_only_models_available_for_generation(self):
        models = [
            types.SimpleNamespace(name="models/gemini-3.5-flash-lite", supported_actions=["generateContent"]),
            types.SimpleNamespace(name="models/embedding-only", supported_actions=["embedContent"]),
        ]

        class FakeClient:
            def __init__(self, api_key):
                self.api_key = api_key

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def models(self):
                raise AssertionError("unexpected")

        FakeClient.models = property(lambda self: types.SimpleNamespace(list=lambda: iter(models)))
        google = types.ModuleType("google")
        google.genai = types.SimpleNamespace(Client=FakeClient)
        out = io.StringIO()
        with patch.dict(sys.modules, {"google": google, "dotenv": types.SimpleNamespace(load_dotenv=lambda: None)}), patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}), contextlib.redirect_stdout(out):
            self.assertEqual(check_models.main(), 0)
        self.assertIn("gemini-3.5-flash-lite", out.getvalue())
        self.assertNotIn("embedding-only", out.getvalue())


if __name__ == "__main__":
    unittest.main()
