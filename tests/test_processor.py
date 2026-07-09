import unittest

from server.processor import (
    REVIEW_NEEDS_REVIEW,
    _confidence_for_evidence,
    _is_complex_sentence,
    _keyword_is_negated,
    extract_metadata,
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

        self.assertEqual(metadata["encryption_applied"], "no")
        assessment = metadata["metadataAssessment"]["encryption_applied"]
        self.assertEqual(assessment["confidence"], 0.5)
        self.assertEqual(assessment["review_status"], REVIEW_NEEDS_REVIEW)


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
