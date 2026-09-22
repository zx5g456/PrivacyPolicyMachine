import unittest

from server.review import apply_human_review


def metadata_fixture():
    return {
        "retentionPolicy": "unclear",
        "riskFlags": ["unclear_retention", "review_recommended"],
        "metadataEvidence": {
            "retentionPolicy": [],
            "riskFlags": {},
        },
        "metadataDetails": {
            "retentionPolicy": "No period was extracted.",
            "riskFlags": "Retention needs review.",
        },
        "metadataAssessment": {
            "retentionPolicy": {
                "value": "unclear",
                "confidence": 0.5,
                "reviewStatus": "needs_review",
            },
            "riskFlags": {
                "unclear_retention": {
                    "confidence": 0.8,
                    "reviewStatus": "needs_review",
                },
                "review_recommended": {
                    "confidence": 0.8,
                    "reviewStatus": "needs_review",
                },
            },
        },
    }


class HumanReviewTests(unittest.TestCase):
    def test_changed_field_is_recorded_and_marked_human_edited(self):
        original = metadata_fixture()
        reviewed = metadata_fixture()
        reviewed["retentionPolicy"] = "yes"
        reviewed["metadataEvidence"]["retentionPolicy"] = [
            "We retain account records for seven years."
        ]
        reviewed["metadataDetails"]["retentionPolicy"] = (
            "Account records are retained for seven years."
        )

        result = apply_human_review(
            reviewed,
            original,
            reviewed_at="2026-09-22T00:00:00+00:00",
        )

        self.assertEqual(result["humanReview"]["reviewStatus"], "human_edited")
        self.assertEqual(result["humanReview"]["editedFields"], ["retentionPolicy"])
        change = result["humanReview"]["changes"]["retentionPolicy"]
        self.assertEqual(change["before"]["value"], "unclear")
        self.assertEqual(change["after"]["value"], "yes")
        self.assertEqual(
            result["metadataAssessment"]["retentionPolicy"]["reviewStatus"],
            "human_edited",
        )
        self.assertIsNone(
            result["metadataAssessment"]["retentionPolicy"]["confidence"]
        )
        self.assertEqual(original["retentionPolicy"], "unclear")

    def test_unchanged_draft_is_recorded_as_human_confirmed(self):
        original = metadata_fixture()

        result = apply_human_review(
            original,
            original,
            reviewed_at="2026-09-22T00:00:00+00:00",
        )

        self.assertEqual(result["humanReview"]["reviewStatus"], "human_confirmed")
        self.assertEqual(result["humanReview"]["editedFields"], [])
        self.assertEqual(result["humanReview"]["changes"], {})
        self.assertEqual(
            result["metadataAssessment"]["retentionPolicy"]["reviewStatus"],
            "needs_review",
        )


if __name__ == "__main__":
    unittest.main()
