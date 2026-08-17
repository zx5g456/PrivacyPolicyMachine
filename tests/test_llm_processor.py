import json
import unittest

from server.llm_models import (
    ExtractedField,
    LLMConnectionError,
    PolicyChunkExtraction,
)
from server.llm_processor import (
    PolicyLLMProcessor,
    chunk_policy,
    validate_evidence,
)


def extraction_json(**overrides):
    """Create a complete all-field response for fake model clients."""
    list_field = {"value": [], "evidence": {}, "details": "", "needs_review": False}
    status_field = {
            "value": "unclear",
            "evidence": [],
            "details": "",
            "needs_review": True,
    }
    fields = {
        **{name: dict(list_field) for name in (
            "data_type_tags", "data_source_types", "collection_context",
            "processing_purpose", "third_party_sources", "downstream_stakeholders",
            "third_party_purpose", "regulatory_framework",
        )},
        **{name: dict(status_field) for name in (
            "sharing_condition", "consent_required", "opt_out_available",
            "deletion_available", "request_channel", "retention_policy",
            "encryption_applied", "anonymisation", "cross_border_transfer",
            "child_data_involved", "contact_channel",
        )},
    }
    fields.update({
        name: value.model_dump() if hasattr(value, "model_dump") else value
        for name, value in overrides.items()
    })
    return json.dumps(fields)


def extraction_model(**overrides):
    return PolicyChunkExtraction.model_validate_json(extraction_json(**overrides))


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def chat(self, **_kwargs):
        response = self.responses[self.calls]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


class ChunkingTests(unittest.TestCase):
    def test_chunks_are_exact_slices_and_respect_limit(self):
        policy = ("First paragraph explains sharing.\n\n" * 30) + "Final paragraph."
        chunks = chunk_policy(policy, max_chars=500, overlap_chars=50)

        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertEqual(chunk.text, policy[chunk.start:chunk.end])
            self.assertLessEqual(len(chunk.text), 500)
        self.assertEqual(chunks[-1].end, len(policy))


class EvidenceTests(unittest.TestCase):
    def test_list_field_keeps_supported_values_with_verbatim_evidence(self):
        source = "We collect precise geolocation to provide the service."
        extraction = extraction_model(
            data_type_tags={
                "value": ["location", "invented_type"],
                "evidence": {
                    "location": [source],
                    "invented_type": [source],
                },
                "details": "Location data is collected.",
                "needs_review": False,
            }
        )

        validated, errors = validate_evidence(extraction, source, chunk_index=0)

        self.assertEqual(validated.data_type_tags.value, ["location"])
        self.assertEqual(validated.data_type_tags.evidence["location"], [source])
        self.assertTrue(validated.data_type_tags.needs_review)
        self.assertIn("unsupported value", errors[0])

    def test_invalid_evidence_is_removed_and_claim_is_downgraded(self):
        source = "We do not sell personal information."
        extraction = extraction_model(
            sharing_condition=ExtractedField(
                value="no",
                evidence=["We never sell personal information."],
            ),
            retention_policy=ExtractedField(value="unclear"),
            cross_border_transfer=ExtractedField(value="unclear"),
            child_data_involved=ExtractedField(value="unclear"),
        )

        validated, errors = validate_evidence(extraction, source, chunk_index=0)

        self.assertEqual(validated.sharing_condition.value, "unclear")
        self.assertTrue(validated.sharing_condition.needs_review)
        self.assertEqual(validated.sharing_condition.evidence, [])
        self.assertEqual(len(errors), 1)

    def test_exact_but_irrelevant_evidence_is_rejected(self):
        source = "We make virtual reality games and applications."
        extraction = extraction_model(
            sharing_condition=ExtractedField(value="unclear"),
            retention_policy=ExtractedField(value="unclear"),
            cross_border_transfer=ExtractedField(value="unclear"),
            child_data_involved=ExtractedField(value="no", evidence=[source]),
        )

        validated, errors = validate_evidence(extraction, source, chunk_index=0)

        self.assertEqual(validated.child_data_involved.value, "unclear")
        self.assertTrue(validated.child_data_involved.needs_review)
        self.assertIn("not relevant", errors[0])

    def test_negative_claim_requires_an_explicit_denial(self):
        source = "You can request to have uploaded content deleted at any time."
        extraction = extraction_model(
            sharing_condition=ExtractedField(value="unclear"),
            retention_policy=ExtractedField(value="no", evidence=[source]),
            cross_border_transfer=ExtractedField(value="unclear"),
            child_data_involved=ExtractedField(value="unclear"),
        )

        validated, errors = validate_evidence(extraction, source, chunk_index=0)

        self.assertEqual(validated.retention_policy.value, "unclear")
        self.assertEqual(len(errors), 1)


class ProcessorTests(unittest.TestCase):
    def test_retries_transient_failure_and_returns_valid_analysis(self):
        policy = "We retain account records for seven years."
        client = FakeClient([
            LLMConnectionError("temporary failure"),
            extraction_json(
                retention_policy={
                    "value": "yes",
                    "evidence": [policy],
                    "details": "A seven-year period is disclosed.",
                    "needs_review": False,
                }
            ),
        ])
        processor = PolicyLLMProcessor(
            client=client,
            retries=1,
            retry_delay_seconds=0,
            sleep=lambda _seconds: None,
        )

        result = processor.analyze(policy)

        self.assertEqual(client.calls, 2)
        self.assertEqual(result.fields.retention_policy.value, "yes")
        self.assertEqual(result.successful_chunk_count, 1)

    def test_invalid_json_is_retried(self):
        client = FakeClient(["not json", extraction_json()])
        processor = PolicyLLMProcessor(
            client=client,
            retries=1,
            retry_delay_seconds=0,
            sleep=lambda _seconds: None,
        )

        result = processor.analyze("No relevant policy terms are stated.")

        self.assertEqual(client.calls, 2)
        self.assertEqual(result.fields.sharing_condition.value, "unclear")


if __name__ == "__main__":
    unittest.main()
