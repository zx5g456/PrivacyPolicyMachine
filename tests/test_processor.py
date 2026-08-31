import unittest

from server.processor import (
    canonical_metadata_bytes,
    generate_report,
    hash_policy_bytes,
    require_canonical_metadata_keys,
)


class AuditHashTests(unittest.TestCase):
    def test_metadata_serialization_is_canonical(self):
        first = {"b": 2, "a": "内容"}
        second = {"a": "内容", "b": 2}

        self.assertEqual(canonical_metadata_bytes(first), canonical_metadata_bytes(second))
        self.assertEqual(
            hash_policy_bytes(canonical_metadata_bytes(first)),
            hash_policy_bytes(canonical_metadata_bytes(second)),
        )

    def test_snake_case_metadata_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "retention_policy"):
            require_canonical_metadata_keys(
                {
                    "policyVersion": "2026-08-30T10:00:00",
                    "metadataDetails": {"retention_policy": "Seven years."},
                }
            )


class ReportTests(unittest.TestCase):
    def test_report_scores_ai_extracted_fields(self):
        report = generate_report(
            {
                "policyId": "policy-1",
                "wordCount": 12,
                "sectionCount": 1,
                "permittedUsage": ["service_operation"],
                "retentionPolicy": "no",
            },
            "hash",
        )

        self.assertIn("permittedUsage", report["coveredTopics"])
        self.assertIn("retentionPolicy", report["coveredTopics"])
        self.assertIn("sharingCondition", report["missingTopics"])
        self.assertGreater(report["readinessScore"], 0)


if __name__ == "__main__":
    unittest.main()
