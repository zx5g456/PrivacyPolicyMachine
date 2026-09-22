"""Human-review provenance for AI-generated policy metadata."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .processor import LIST_METADATA_FIELDS, STATUS_METADATA_FIELDS


REVIEWABLE_METADATA_FIELDS = (
    *LIST_METADATA_FIELDS,
    *STATUS_METADATA_FIELDS,
    "riskFlags",
)


def apply_human_review(
    metadata: dict[str, Any],
    original_metadata: dict[str, Any],
    *,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    """Record field-level differences between an AI draft and its reviewed form.

    The returned metadata is a deep copy.  Each changed field receives a
    ``human_edited`` assessment and the before/after review snapshots are kept
    in ``humanReview.changes`` so the correction remains auditable.
    """

    reviewed = deepcopy(metadata)
    original = deepcopy(original_metadata)
    changes: dict[str, dict[str, Any]] = {}

    for field_name in REVIEWABLE_METADATA_FIELDS:
        before = _field_snapshot(original, field_name)
        after = _field_snapshot(reviewed, field_name)
        if before == after:
            continue
        changes[field_name] = {"before": before, "after": after}
        _mark_human_edited(reviewed, field_name)

    reviewed["humanReview"] = {
        "reviewStatus": "human_edited" if changes else "human_confirmed",
        "reviewedAt": reviewed_at or datetime.now(timezone.utc).isoformat(),
        "editedFields": list(changes),
        "changes": changes,
    }
    return reviewed


def _field_snapshot(metadata: dict[str, Any], field_name: str) -> dict[str, Any]:
    evidence = metadata.get("metadataEvidence")
    details = metadata.get("metadataDetails")
    return {
        "value": deepcopy(metadata.get(field_name)),
        "evidence": deepcopy(evidence.get(field_name) if isinstance(evidence, dict) else None),
        "details": deepcopy(details.get(field_name) if isinstance(details, dict) else None),
    }


def _mark_human_edited(metadata: dict[str, Any], field_name: str) -> None:
    assessment_by_field = metadata.setdefault("metadataAssessment", {})
    if not isinstance(assessment_by_field, dict):
        assessment_by_field = {}
        metadata["metadataAssessment"] = assessment_by_field

    if field_name in STATUS_METADATA_FIELDS:
        existing = assessment_by_field.get(field_name)
        assessment = deepcopy(existing) if isinstance(existing, dict) else {}
        assessment.update(
            {
                "value": metadata.get(field_name),
                "confidence": None,
                "reviewStatus": "human_edited",
            }
        )
        assessment_by_field[field_name] = assessment
        return

    values = metadata.get(field_name)
    if not isinstance(values, list) or not values:
        assessment_by_field[field_name] = {
            "value": deepcopy(values),
            "confidence": None,
            "reviewStatus": "human_edited",
        }
        return

    existing = assessment_by_field.get(field_name)
    existing_by_value = existing if isinstance(existing, dict) else {}
    assessment_by_field[field_name] = {
        str(value): {
            **(
                deepcopy(existing_by_value.get(str(value)))
                if isinstance(existing_by_value.get(str(value)), dict)
                else {}
            ),
            "confidence": None,
            "reviewStatus": "human_edited",
        }
        for value in values
    }
