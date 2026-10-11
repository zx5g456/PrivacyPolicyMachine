from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rq3 import evaluate, run
from rq3.prompts import LIST_FIELDS, STATUS_FIELDS


def response() -> dict:
    fields = {name: {"value": [], "evidence": {}} for name in LIST_FIELDS}
    fields.update({name: {"value": "unclear", "evidence": []} for name in STATUS_FIELDS})
    return {"fields": fields}


class RQ3Tests(unittest.TestCase):
    def test_sample_is_distinct_and_has_multichunk_cases(self) -> None:
        policies = run.load_policies()
        self.assertEqual(len(policies), 15)
        self.assertEqual(len({p["sha256"] for p in policies}), 15)
        counts = [len(run.chunk_policy(p["text"], max_chars=3000, overlap_chars=200)) for p in policies]
        self.assertGreater(sum(n > 1 for n in counts), 0)

    def test_runner_preserves_every_call_and_scores_gold(self) -> None:
        policy = run.load_policies()[3]  # Two chunks.
        args = argparse.Namespace(
            chunk_chars=3000, overlap_chars=200, backend="ollama", model="test-model",
            temperature=0.0, timeout=1.0, ollama_url="http://example.invalid",
        )
        with patch.object(run, "request_model", return_value=(json.dumps(response()), {})) as model:
            result = run.run_job(args, policy, "C4", 1)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["calls"]), 3)
        self.assertEqual(model.call_count, 3)
        self.assertTrue(all(call["elapsed_seconds"] >= 0 for call in result["calls"]))
        self.assertTrue(evaluate.valid_fields(result["final_response"]))
        gold = {name: [] for name in LIST_FIELDS}
        gold.update({name: "unclear" for name in STATUS_FIELDS})
        score = evaluate.score_run(result, policy["text"], gold)
        self.assertEqual((score["tp"], score["fp"], score["fn"]), (0, 0, 0))

    def test_quote_occurrence_is_not_semantic_support(self) -> None:
        answer = response()
        answer["fields"]["dataTypeTags"] = {
            "value": ["location"], "evidence": {"location": ["privacy"]},
        }
        assertions, has_quote, exact = evaluate.quote_stats(answer["fields"], "our privacy policy")
        self.assertEqual((assertions, has_quote, exact), (1, 1, 1))

    def test_tagged_cases_count_missing_model_claims(self) -> None:
        answer = response()
        gold_fields = {name: [] for name in LIST_FIELDS}
        gold_fields.update({name: "unclear" for name in STATUS_FIELDS})
        gold_fields["consentRequired"] = "yes"
        gold = {"P01": {"fields": gold_fields,
                         "condition_fields": ["consentRequired"],
                         "negation_fields": []}}
        run_row = {"policy_id": "P01", "final_response": answer}
        score = {"policy_id": "P01", "schema_valid": True}
        evaluate.apply_tagged_cases([score], [run_row], gold)
        self.assertEqual(score["condition_cases"], 1)
        self.assertEqual(score["condition_correct_count"], 0)

    def test_malformed_status_is_schema_invalid(self) -> None:
        answer = response()
        answer["fields"]["consentRequired"]["value"] = ["yes"]
        self.assertFalse(evaluate.valid_fields(answer))

    def test_manual_review_must_have_exact_source_quote(self) -> None:
        answer = response()
        answer["fields"]["dataTypeTags"] = {
            "value": ["location"], "evidence": {"location": ["fabricated quote"]},
        }
        run_row = {"policy_id": "P01", "config": "C0", "repeat": 1,
                   "final_response": answer}
        score = {"policy_id": "P01", "config": "C0", "repeat": 1,
                 "schema_valid": True}
        reviews = {("P01", "C0", 1): [{
            "field": "dataTypeTags", "value": "location", "evidence": ["fabricated quote"],
            "evidence_valid": True, "assertion_supported": True,
        }]}
        with self.assertRaises(ValueError):
            evaluate.apply_reviews([score], [run_row], reviews, {"P01": "Real policy text"})

    def test_template_update_does_not_overwrite_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manual_review_template.jsonl"
            path.write_text("human edits\n", encoding="utf-8")
            evaluate.write_template(path, "new generated content\n")
            self.assertEqual(path.read_text(encoding="utf-8"), "human edits\n")
            self.assertEqual(len(list(Path(temp).glob("manual_review_template.new-*.jsonl"))), 1)


if __name__ == "__main__":
    unittest.main()
