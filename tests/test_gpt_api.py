import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch


GPT_API_PATH = Path(__file__).resolve().parents[1] / "compliance tool" / "gpt_api.py"
SPEC = importlib.util.spec_from_file_location("shared_gpt_api", GPT_API_PATH)
gpt_api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gpt_api)


class GptApiConfigurationTests(unittest.TestCase):
    def test_reads_environment_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": " mainnet-test-key "}):
            self.assertEqual(gpt_api.load_gpt_api_key(), "mainnet-test-key")

    def test_missing_environment_key_fails(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY is required"):
                gpt_api.load_gpt_api_key()


if __name__ == "__main__":
    unittest.main()
