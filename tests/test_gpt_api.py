import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


GPT_API_PATH = Path(__file__).resolve().parents[1] / "compliance tool" / "gpt_api.py"
SPEC = importlib.util.spec_from_file_location("shared_gpt_api", GPT_API_PATH)
gpt_api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gpt_api)


class GptApiConfigurationTests(unittest.TestCase):
    def test_environment_key_takes_priority_over_legacy_file(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy_file = Path(directory) / "gpt.zshrc"
            legacy_file.write_text("OPENAI_API_KEY=legacy-test-key\n", encoding="utf-8")
            with patch.dict(os.environ, {
                "OPENAI_API_KEY": "mainnet-test-key",
                "GPT_CONFIG_PATH": str(legacy_file),
            }):
                self.assertEqual(gpt_api.load_gpt_api_key(), "mainnet-test-key")

    def test_legacy_file_remains_available_without_environment_key(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy_file = Path(directory) / "gpt.zshrc"
            legacy_file.write_text("OPENAI_API_KEY=legacy-test-key\n", encoding="utf-8")
            with patch.dict(os.environ, {
                "OPENAI_API_KEY": "",
                "GPT_CONFIG_PATH": str(legacy_file),
            }):
                self.assertEqual(gpt_api.load_gpt_api_key(), "legacy-test-key")


if __name__ == "__main__":
    unittest.main()
