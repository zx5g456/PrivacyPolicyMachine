import unittest

from server.processor import (
    REVIEW_NEEDS_REVIEW,
    _confidence_for_evidence,
    _is_complex_sentence,
    _keyword_is_negated,
    canonical_metadata_bytes,
    extract_metadata,
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


class NegationDetectionTests(unittest.TestCase):
    def test_detects_negation_before_and_after_keyword(self):
        self.assertTrue(_keyword_is_negated("We do not share personal data.", "share"))
        self.assertTrue(_keyword_is_negated("Sharing is not permitted.", "sharing"))

    def test_ignores_distant_negation_and_not_only(self):
        self.assertFalse(
            _keyword_is_negated(
                "We do not currently operate abroad, but our providers share data.",
                "share",
            )
        )
        self.assertFalse(_keyword_is_negated("We not only encrypt data but also audit access.", "encrypt"))

    def test_negated_yes_no_field_is_no_and_requires_review(self):
        metadata = extract_metadata("We do not encrypt personal data.", "policy-1", None)

        self.assertEqual(metadata["encryptionApplied"], "no")
        assessment = metadata["metadataAssessment"]["encryptionApplied"]
        self.assertEqual(assessment["confidence"], 0.5)
        self.assertEqual(assessment["reviewStatus"], REVIEW_NEEDS_REVIEW)

    def test_metadata_uses_camel_case_and_keeps_independent_details(self):
        policy = (
            "We personalize the service and use account data for marketing. "
            "We encrypt personal data in transit with TLS 1.2 and at rest with AES-256."
        )

        metadata = extract_metadata(policy, "policy-1", "2026-08-30T10:00:00")

        self.assertEqual(metadata["policyVersion"], "2026-08-30T10:00:00")
        self.assertIn("personalization", metadata["permittedUsage"])
        self.assertIn("marketing", metadata["permittedUsage"])
        self.assertNotEqual(metadata["permittedUsage"], metadata["processingPurpose"])
        self.assertIn("TLS 1.2", metadata["metadataDetails"]["encryptionApplied"])
        self.assertIn("reviewStatus", metadata["metadataAssessment"]["encryptionApplied"])
        self.assertNotIn("policy_version", metadata)
        self.assertNotIn("permitted_usage", metadata)


class ConfidenceTests(unittest.TestCase):
    def test_complex_sentence_reduces_confidence(self):
        simple = "We use encryption."
        complex_sentence = (
            "Although we use encryption, which protects records in transit, "
            "we may change the safeguards if a provider requires it."
        )

        self.assertTrue(_is_complex_sentence(complex_sentence))
        self.assertLess(
            _confidence_for_evidence([complex_sentence], ["encryption"], "yes"),
            _confidence_for_evidence([simple], ["encryption"], "yes"),
        )


if __name__ == "__main__":
    unittest.main()
