"""Regression tests for resuming an interrupted RQ3 experiment."""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rq3 import evaluate, run
from rq3.prompts import CONFIGS


class RQ3ResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / "experiment"
        self.policy = {
            "policy_id": "P01",
            "source_path": "sources/dataset/test-policy.txt",
            "sha256": run.sha256(b"A short policy."),
            "text": "A short policy.",
        }

    def args(self, **changes: object) -> argparse.Namespace:
        values = {
            "backend": "ollama",
            "model": "qwen3.5:9b",
            "temperature": 0.0,
            "repeats": 1,
            "seed": 7841,
            "chunk_chars": 3000,
            "overlap_chars": 200,
            "timeout": 180.0,
            "ollama_url": "http://127.0.0.1:11434/api/chat",
            "configs": CONFIGS,  # argparse's actual default is a tuple.
            "policy_ids": None,
            "out_dir": self.output,
            "dry_run": False,
            "resume": False,
        }
        values.update(changes)
        return argparse.Namespace(**values)

    def invoke(self, args: argparse.Namespace, model_result: object,
               *, digest: str = "test-digest") -> object:
        with patch.object(run, "arguments", return_value=args), \
             patch.object(run, "load_policies", return_value=[self.policy]), \
             patch.object(run, "model_identity", return_value={"name": args.model, "digest": digest}), \
             patch.object(run, "request_model", side_effect=model_result) as model:
            run.main()
            return model

    def rows(self) -> list[dict]:
        return [json.loads(line) for line in (self.output / "runs.jsonl").read_text().splitlines()
                if line.strip()]

    @staticmethod
    def response(**_kwargs: object) -> tuple[str, dict]:
        return json.dumps({"fields": {}}), {}

    def test_default_config_resume_skips_all_completed_jobs(self) -> None:
        first = self.invoke(self.args(), self.response)
        self.assertEqual(first.call_count, len(CONFIGS))
        second = self.invoke(self.args(resume=True), self.response)
        self.assertEqual(second.call_count, 0)
        self.assertEqual(len(self.rows()), len(CONFIGS))

    def test_completed_job_is_skipped_after_interruption(self) -> None:
        calls = 0

        def interrupt_second_job(**kwargs: object) -> tuple[str, dict]:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt
            return self.response(**kwargs)

        with self.assertRaises(KeyboardInterrupt):
            self.invoke(self.args(configs=["C0", "C1"]), interrupt_second_job)
        self.assertEqual(len(self.rows()), 1)

        resumed = self.invoke(self.args(configs=["C0", "C1"], resume=True), self.response)
        self.assertEqual(resumed.call_count, 1)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual({r["config"] for r in self.rows()}, {"C0", "C1"})

    def test_interrupted_second_chunk_resumes_at_that_call(self) -> None:
        self.policy["text"] = "A" * 4000
        self.policy["sha256"] = run.sha256(self.policy["text"].encode())
        self.assertEqual(len(run.chunk_policy(self.policy["text"], max_chars=3000,
                                              overlap_chars=200)), 2)
        calls = 0

        def interrupt_second_call(**kwargs: object) -> tuple[str, dict]:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt
            return self.response(**kwargs)

        with self.assertRaises(KeyboardInterrupt):
            self.invoke(self.args(configs=["C0"]), interrupt_second_call)
        resumed = self.invoke(self.args(configs=["C0"], resume=True), self.response)
        self.assertEqual(resumed.call_count, 2)  # Second extraction and merge only.
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["status"], "ok")
        self.assertEqual(len(self.rows()[0]["calls"]), 3)

    def test_torn_final_jsonl_line_is_recovered(self) -> None:
        self.invoke(self.args(configs=["C0"]), self.response)
        with (self.output / "runs.jsonl").open("a", encoding="utf-8") as file:
            file.write('{"policy_id":"P01"')
        resumed = self.invoke(self.args(configs=["C0"], resume=True), self.response)
        self.assertEqual(resumed.call_count, 0)
        self.assertEqual(len(self.rows()), 1)

    def test_changed_experiment_setting_is_rejected(self) -> None:
        self.invoke(self.args(configs=["C0"]), self.response)
        for changed in ({"temperature": 0.5},
                        {"ollama_url": "http://other-host:11434/api/chat"}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.invoke(self.args(configs=["C0"], resume=True, **changed),
                            self.response)
        with self.assertRaises(ValueError):
            self.invoke(self.args(configs=["C0"], resume=True), self.response,
                        digest="a-different-model-digest")

    def test_resume_requires_an_existing_run(self) -> None:
        with self.assertRaises((FileNotFoundError, ValueError)):
            self.invoke(self.args(configs=["C0"], resume=True), self.response)
        self.assertFalse((self.output / "run_metadata.json").exists())

    def test_output_directory_lock_rejects_concurrent_runner(self) -> None:
        self.output.mkdir()
        path = self.output / "run.lock"
        with run.exclusive_run_lock(path):
            with self.assertRaisesRegex(RuntimeError, "Another runner"):
                with run.exclusive_run_lock(path):
                    pass
        with run.exclusive_run_lock(path):
            pass

    def test_failed_job_is_retried_with_preserved_attempt_history(self) -> None:
        def unavailable(**_kwargs: object) -> tuple[str, dict]:
            raise OSError("model temporarily unavailable")

        with self.assertRaises(RuntimeError):
            self.invoke(self.args(configs=["C0"]), unavailable)
        self.assertEqual(self.rows()[0]["status"], "failed")
        resumed = self.invoke(self.args(configs=["C0"], resume=True), self.response)
        self.assertEqual(resumed.call_count, 1)
        self.assertEqual([(r["attempt"], r["status"]) for r in self.rows()],
                         [(1, "failed"), (2, "ok")])

    def test_invalid_model_output_is_terminal_for_schema_scoring(self) -> None:
        def invalid_json(**_kwargs: object) -> tuple[str, dict]:
            return "this is not JSON", {}

        self.invoke(self.args(configs=["C0"]), invalid_json)
        self.assertEqual(self.rows()[0]["status"], "invalid_output")
        resumed = self.invoke(self.args(configs=["C0"], resume=True), self.response)
        self.assertEqual(resumed.call_count, 0)
        self.assertEqual(len(self.rows()), 1)

    def test_evaluator_uses_one_canonical_row_after_retry(self) -> None:
        def unavailable(**_kwargs: object) -> tuple[str, dict]:
            raise OSError("model temporarily unavailable")

        with self.assertRaises(RuntimeError):
            self.invoke(self.args(configs=["C0"]), unavailable)
        self.invoke(self.args(configs=["C0"], resume=True), self.response)
        canonical = evaluate.canonical_runs(self.rows())
        self.assertEqual(len(canonical), 1)
        self.assertEqual((canonical[0]["attempt"], canonical[0]["status"]), (2, "ok"))

        with self.assertRaises(ValueError):
            evaluate.canonical_runs([self.rows()[0], self.rows()[0]])
        with self.assertRaises(ValueError):
            evaluate.canonical_runs([self.rows()[1], dict(self.rows()[1], attempt=3)])

    def test_duplicate_configuration_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.invoke(self.args(configs=["C0", "C0"]), self.response)


if __name__ == "__main__":
    unittest.main()
