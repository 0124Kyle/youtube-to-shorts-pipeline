import contextlib
import io
import sys
import types
import unittest
from unittest.mock import patch

import run_pipeline


class CliDiagnosticsTests(unittest.TestCase):
    def test_pipeline_import_error_names_actual_missing_module(self):
        output = io.StringIO()
        args = ["run_pipeline.py", "--url", "https://www.youtube.com/watch?v=KjAI9r8tnOs"]
        with patch.object(sys, "argv", args), \
             patch.dict(sys.modules, {"dotenv": types.SimpleNamespace(load_dotenv=lambda: None)}), \
             patch("run_pipeline.run_pipeline", side_effect=ModuleNotFoundError("No module named 'some_dependency'")), \
             contextlib.redirect_stderr(output):
            self.assertEqual(run_pipeline.main(), 1)
        self.assertIn("some_dependency", output.getvalue())
        self.assertIn(sys.executable, output.getvalue())

    def test_check_does_not_call_pipeline(self):
        with patch.object(sys, "argv", ["run_pipeline.py", "--check"]), \
             patch("run_pipeline.check_environment", return_value=0) as check, \
             patch("run_pipeline.run_pipeline") as pipeline:
            self.assertEqual(run_pipeline.main(), 0)
            check.assert_called_once()
            pipeline.assert_not_called()


if __name__ == "__main__":
    unittest.main()
