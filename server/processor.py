from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any


# These values constrain the structured list fields returned by the AI model.
METADATA_OPTIONS = {
    "dataTypeTags": ("location", "voice_recording", "eye_tracking", "device_id", "payment_info", "contact_info"),
    "dataSourceTypes": ("user_provided", "device_sensor", "third_party_login", "cookies", "xr_headset_sensor"),
    "collectionContext": ("during_payment", "account_registration", "service_usage", "customer_support"),
    "processingPurpose": ("advertising", "analytics", "payment_processing", "service_provision", "security"),
    "permittedUsage": ("service_operation", "personalization", "marketing", "product_improvement"),
    "thirdPartySources": ("google_login", "facebook_login", "payment_processor"),
    "downstreamStakeholders": ("cloud_provider", "analytics_provider", "advertising_partner", "payment_processor", "email_provider"),
    "thirdPartyPurpose": ("payment_processing", "analytics", "advertising", "service_delivery", "authentication", "email_delivery"),
    "regulatoryFramework": ("GDPR", "CCPA", "COPPA", "HIPAA"),
}

LIST_METADATA_FIELDS = tuple(METADATA_OPTIONS)
STATUS_METADATA_FIELDS = (
    "sharingCondition",
    "consentRequired",
    "optOutAvailable",
    "deletionAvailable",
    "requestChannel",
    "retentionPolicy",
    "encryptionApplied",
    "anonymisation",
    "crossBorderTransfer",
    "childDataInvolved",
    "contactChannel",
)

# Only reviewed final values and policy identity are public. Evidence,
# explanations, confidence, and human-review history stay in the local record.
ON_CHAIN_METADATA_FIELDS = (
    "policyId", "policyVersion", "applicationName", "developer",
    "publisherEntity", "policyUrl", "serviceName", "effectiveDate",
    "documentHash", "changeSummary", "uploadMethod",
    "characterCount", "wordCount", "sectionCount", "sections",
    *LIST_METADATA_FIELDS, *STATUS_METADATA_FIELDS, "riskFlags",
)

RISK_FLAG_DETAILS = {
    "unclear_retention": "The policy does not state a clear retention period.",
    "vague_third_party_sharing": "Third-party sharing is described without clear conditions.",
    "no_deletion_method": "The policy does not provide a supported deletion method.",
    "sensitive_data_involved": "The policy covers sensitive data that requires additional safeguards.",
    "review_recommended": "Human review is recommended before trusted registration.",
}


def hash_policy(raw_file: str) -> str:
    return hashlib.sha256(raw_file.encode("utf-8")).hexdigest()


def hash_policy_bytes(raw_file: bytes) -> str:
    return hashlib.sha256(raw_file).hexdigest()


def canonical_metadata_bytes(metadata: dict) -> bytes:
    require_canonical_metadata_keys(metadata)
    return json.dumps(
        metadata,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def on_chain_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Project a complete local governance record onto its public schema."""

    require_canonical_metadata_keys(metadata)
    public = {
        field: metadata[field]
        for field in ON_CHAIN_METADATA_FIELDS
        if field in metadata
    }
    if isinstance(public.get("riskFlags"), list):
        public["riskFlags"] = [
            flag for flag in public["riskFlags"] if flag != "review_recommended"
        ]
    return public


def canonical_on_chain_metadata_bytes(metadata: dict[str, Any]) -> bytes:
    return canonical_metadata_bytes(on_chain_metadata(metadata))


def registered_metadata_match(
    stored_content: bytes, local_metadata: dict[str, Any]
) -> tuple[str, bytes]:
    """Match new public records or older full-metadata records exactly."""

    public = canonical_on_chain_metadata_bytes(local_metadata)
    if stored_content == public:
        return "governance_only", public
    legacy = canonical_metadata_bytes(local_metadata)
    if stored_content == legacy:
        return "legacy_full", legacy
    return "mismatch", public


def require_canonical_metadata_keys(metadata: dict[str, Any]) -> None:
    """Reject snake_case field names in canonical metadata containers."""
    containers = {
        "metadata": metadata,
        "metadataEvidence": metadata.get("metadataEvidence"),
        "metadataDetails": metadata.get("metadataDetails"),
        "metadataAssessment": metadata.get("metadataAssessment"),
    }
    invalid = [
        f"{container_name}.{key}"
        for container_name, container in containers.items()
        if isinstance(container, dict)
        for key in container
        if "_" in key
    ]
    if invalid:
        raise ValueError(
            "metadata keys must use camelCase; invalid keys: " + ", ".join(sorted(invalid))
        )


def normalize_policy_text(raw_file: str) -> str:
    normalized = unicodedata.normalize("NFKC", raw_file).casefold()
    return "".join(
        char
        for char in normalized
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )


def generate_report(metadata: dict[str, Any], hash_code: str) -> dict[str, Any]:
    covered = [
        field_name
        for field_name in (*LIST_METADATA_FIELDS, *STATUS_METADATA_FIELDS)
        if metadata.get(field_name) not in (None, "", "unclear", [])
    ]
    missing = [
        field_name
        for field_name in (*LIST_METADATA_FIELDS, *STATUS_METADATA_FIELDS)
        if field_name not in covered
    ]
    readiness = round((len(covered) / (len(covered) + len(missing))) * 100)
    return {
        "summary": f"Policy for {metadata.get('applicationName', metadata['policyId'])} has {metadata['wordCount']} words and {metadata['sectionCount']} detected sections.",
        "readinessScore": readiness,
        "coveredTopics": covered,
        "missingTopics": missing,
        "hashCode": hash_code,
        "recommendation": "Ready for trusted registration" if readiness >= 60 else "Review missing topics before production use",
    }
