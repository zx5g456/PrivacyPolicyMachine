import unittest

from server.processor import (
    canonical_metadata_bytes,
    canonical_on_chain_metadata_bytes,
    generate_report,
    hash_policy_bytes,
    on_chain_metadata,
    registered_metadata_match,
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

    def test_on_chain_projection_excludes_all_review_information(self):
        metadata = {
            "policyId": "policy-1",
            "retentionPolicy": "yes",
            "riskFlags": ["unclear_retention", "review_recommended"],
            "metadataEvidence": {"retentionPolicy": ["Seven years."]},
            "metadataDetails": {"retentionPolicy": "Seven-year period."},
            "metadataAssessment": {
                "retentionPolicy": {"reviewStatus": "human_edited", "confidence": None}
            },
            "humanReview": {"editedFields": ["retentionPolicy"]},
            "reviewerNotes": "Do not publish",
        }

        public = on_chain_metadata(metadata)

        self.assertEqual(
            public,
            {
                "policyId": "policy-1",
                "retentionPolicy": "yes",
                "riskFlags": ["unclear_retention"],
            },
        )
        self.assertNotIn(b"Seven years", canonical_on_chain_metadata_bytes(metadata))
        self.assertNotIn(b"human_edited", canonical_on_chain_metadata_bytes(metadata))
        self.assertIn("humanReview", metadata)

    def test_metadata_match_accepts_new_and_legacy_formats_but_not_changed_content(self):
        metadata = {
            "policyId": "policy-1",
            "retentionPolicy": "yes",
            "humanReview": {"reviewStatus": "human_edited"},
        }
        public = canonical_on_chain_metadata_bytes(metadata)
        legacy = canonical_metadata_bytes(metadata)

        self.assertEqual(registered_metadata_match(public, metadata), ("governance_only", public))
        self.assertEqual(registered_metadata_match(legacy, metadata), ("legacy_full", legacy))
        self.assertEqual(registered_metadata_match(b"{}", metadata)[0], "mismatch")


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
