from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any


KEYWORD_RULES = {
    "personal_data": ["personal information", "personal data", "name", "email", "address"],
    "sharing": ["share", "third party", "partner", "affiliate", "vendor"],
    "retention": ["retain", "retention", "delete", "deletion", "storage period"],
    "rights": ["access", "correct", "erase", "opt out", "withdraw consent"],
    "security": ["security", "encrypt", "safeguard", "breach"],
}

METADATA_RULES = {
    "data_type_tags": {
        "location": ["location", "gps", "geolocation"],
        "voice_recording": ["voice", "audio", "recording", "microphone"],
        "eye_tracking": ["eye tracking", "gaze"],
        "device_id": ["device id", "device identifier", "identifier"],
        "payment_info": ["payment", "credit card", "billing"],
        "contact_info": ["email", "phone", "address"],
    },
    "data_source_types": {
        "user_provided": ["provide", "submit", "enter", "account"],
        "device_sensor": ["sensor", "device", "camera", "microphone"],
        "third_party_login": ["google login", "facebook login", "single sign-on", "third party login"],
        "cookies": ["cookie", "tracking technology"],
        "xr_headset_sensor": ["xr headset", "vr headset", "ar headset", "headset"],
    },
    "collection_context": {
        "during_payment": ["payment", "purchase", "billing"],
        "account_registration": ["register", "sign up", "create an account"],
        "service_usage": ["use our service", "use the app", "interact"],
        "customer_support": ["support", "contact us"],
    },
    "processing_purpose": {
        "advertising": ["advertising", "ads", "marketing"],
        "analytics": ["analytics", "measure", "improve"],
        "payment_processing": ["payment processing", "process payment", "billing"],
        "service_provision": ["provide", "operate", "deliver"],
        "security": ["security", "fraud", "protect"],
    },
    "third_party_sources": {
        "google_login": ["google login", "google account"],
        "facebook_login": ["facebook login", "facebook account"],
        "payment_processor": ["payment processor", "stripe", "paypal"],
    },
    "downstream_stakeholders": {
        "cloud_provider": ["cloud provider", "hosting provider", "aws", "azure", "google cloud"],
        "analytics_provider": ["analytics provider", "google analytics"],
        "advertising_partner": ["advertising partner", "ad network"],
        "payment_processor": ["payment processor", "stripe", "paypal"],
    },
    "third_party_purpose": {
        "payment_processing": ["payment processing", "process payment"],
        "analytics": ["analytics", "measure"],
        "advertising": ["advertising", "ads"],
        "service_delivery": ["provide services", "service provider"],
    },
    "regulatory_framework": {
        "GDPR": ["gdpr", "general data protection regulation"],
        "CCPA": ["ccpa", "california consumer privacy act"],
        "COPPA": ["coppa", "children's online privacy protection"],
        "HIPAA": ["hipaa"],
    },
}

# Review status is generated automatically for now. A future manual review UI can
# overwrite auto_extracted/needs_review with confirmed, rejected, or edited.
REVIEW_AUTO_EXTRACTED = "auto_extracted"
REVIEW_NEEDS_REVIEW = "needs_review"
REVIEW_CONFIRMED = "confirmed"
REVIEW_REJECTED = "rejected"
REVIEW_EDITED = "edited"
REVIEW_STATUSES = {
    REVIEW_AUTO_EXTRACTED,
    REVIEW_NEEDS_REVIEW,
    REVIEW_CONFIRMED,
    REVIEW_REJECTED,
    REVIEW_EDITED,
}


def hash_policy(raw_file: str) -> str:
    return hashlib.sha256(raw_file.encode("utf-8")).hexdigest()


def normalize_policy_text(raw_file: str) -> str:
    normalized = unicodedata.normalize("NFKC", raw_file).casefold()
    return "".join(
        char
        for char in normalized
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )


def _matches(lower: str, rules: dict[str, list[str]]) -> list[str]:
    return [label for label, keywords in rules.items() if any(keyword in lower for keyword in keywords)]


def _sentences(raw_file: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", raw_file).strip()
    if not normalized:
        return []
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|(?<=:)\s+", normalized)
        if sentence.strip()
    ]


def _matching_sentences(sentences: list[str], keywords: list[str], limit: int = 2) -> list[str]:
    matches = []
    for sentence in sentences:
        lower_sentence = sentence.lower()
        if any(keyword in lower_sentence for keyword in keywords):
            matches.append(sentence)
        if len(matches) >= limit:
            break
    return matches


def _rule_evidence(raw_file: str, rules: dict[str, dict[str, list[str]]]) -> dict[str, dict[str, list[str]]]:
    sentences = _sentences(raw_file)
    evidence = {}
    for field, field_rules in rules.items():
        field_evidence = {}
        for label, keywords in field_rules.items():
            matches = _matching_sentences(sentences, keywords)
            if matches:
                field_evidence[label] = matches
        evidence[field] = field_evidence
    return evidence


def _field_evidence(raw_file: str, evidence_rules: dict[str, list[str]]) -> dict[str, list[str]]:
    sentences = _sentences(raw_file)
    return {
        field: _matching_sentences(sentences, keywords)
        for field, keywords in evidence_rules.items()
        if _matching_sentences(sentences, keywords)
    }

# Calculate confidence based on the presence of evidence and keywords. If the value is "unclear", return a low confidence. If there is no evidence, return a medium confidence. If there is evidence and any keyword matches, return a high confidence. Otherwise, return a medium-high confidence.
def _confidence_for_evidence(evidence: list[str], keywords: list[str], value: Any) -> float:
    if value == "unclear":
        return 0.35
    if not evidence:
        return 0.55

    joined = " ".join(evidence).lower()
    if any(keyword in joined for keyword in keywords if " " in keyword or len(keyword) >= 8):
        return 0.9
    return 0.75


def _review_status(confidence: float, value: Any, force_review: bool = False) -> str:
    if force_review or value == "unclear" or confidence < 0.7:
        return REVIEW_NEEDS_REVIEW
    return REVIEW_AUTO_EXTRACTED


def _assessment_entry(confidence: float, value: Any, force_review: bool = False) -> dict[str, Any]:
    return {
        "confidence": confidence,
        "review_status": _review_status(confidence, value, force_review),
    }


def _metadata_assessment(
    metadata: dict[str, list[str]],
    field_values: dict[str, Any],
    metadata_evidence: dict[str, Any],
    risk_flags: list[str],
) -> dict[str, Any]:
    assessment: dict[str, Any] = {}
    for field, labels in metadata.items():
        field_assessment = {}
        for label in labels:
            keywords = METADATA_RULES[field][label]
            evidence = metadata_evidence.get(field, {}).get(label, [])
            confidence = _confidence_for_evidence(evidence, keywords, label)
            field_assessment[label] = _assessment_entry(confidence, label)
        assessment[field] = field_assessment

    evidence_keywords = {
        "sharing_condition": ["share when", "we may share", "with your consent", "as required by law"],
        "consent_required": ["consent", "agree", "permission", "opt in"],
        "opt_out_available": ["opt out", "unsubscribe", "disable", "withdraw"],
        "deletion_available": ["delete your data", "delete your account", "erasure", "remove your data"],
        "request_channel": ["contact us", "email us", "privacy request", "request form"],
        "retention_policy": KEYWORD_RULES["retention"],
        "encryption_applied": ["encrypt", "encryption"],
        "anonymisation": ["anonymous", "anonymized", "anonymised", "de-identified", "aggregate"],
        "cross_border_transfer": ["international", "cross-border", "outside your country", "other countries"],
        "child_data_involved": ["child", "children", "under 13", "minor"],
        "contact_channel": ["contact us", "email", "privacy@"],
    }
    for field, value in field_values.items():
        evidence = metadata_evidence.get(field, [])
        confidence = _confidence_for_evidence(evidence, evidence_keywords.get(field, []), value)
        assessment[field] = _assessment_entry(confidence, value)

    assessment["risk_flags"] = {
        flag: _assessment_entry(0.8, flag, force_review=True)
        for flag in risk_flags
    }
    return assessment


def _yes_no_unclear(lower: str, positive: list[str], negative: list[str] | None = None) -> str:
    if negative and any(term in lower for term in negative):
        return "no"
    if any(term in lower for term in positive):
        return "yes"
    return "unclear"


def extract_metadata(raw_file: str, policy_id: str, policy_version: str | None) -> dict[str, Any]:
    words = re.findall(r"\b[\w'-]+\b", raw_file)
    sections = [
        line.strip()
        for line in raw_file.splitlines()
        if line.strip() and (line.strip().endswith(":") or line.strip().isupper())
    ]
    lower = raw_file.lower()
    keyword_hits = {
        category: [keyword for keyword in keywords if keyword in lower]
        for category, keywords in KEYWORD_RULES.items()
    }
    metadata = {
        name: _matches(lower, rules)
        for name, rules in METADATA_RULES.items()
    }
    metadata_evidence = _rule_evidence(raw_file, METADATA_RULES)
    consent_required = _yes_no_unclear(lower, ["consent", "agree", "permission", "opt in"])
    opt_out_available = _yes_no_unclear(lower, ["opt out", "unsubscribe", "disable", "withdraw"])
    deletion_available = _yes_no_unclear(lower, ["delete your data", "delete your account", "erasure", "remove your data"])
    encryption_applied = _yes_no_unclear(lower, ["encrypt", "encryption"])
    anonymisation = _yes_no_unclear(lower, ["anonymous", "anonymized", "anonymised", "de-identified", "aggregate"])
    cross_border_transfer = _yes_no_unclear(lower, ["international", "cross-border", "outside your country", "other countries"])
    child_data_involved = _yes_no_unclear(lower, ["child", "children", "under 13", "minor"])
    retention_policy = "mentioned" if keyword_hits["retention"] else "unclear"
    sharing_condition = "mentioned" if any(term in lower for term in ["share when", "we may share", "with your consent", "as required by law"]) else "unclear"
    request_channel = "mentioned" if any(term in lower for term in ["contact us", "email us", "privacy request", "request form"]) else "unclear"
    contact_channel = "mentioned" if any(term in lower for term in ["contact us", "email", "privacy@"]) else "unclear"
    metadata_evidence.update(
        _field_evidence(
            raw_file,
            {
                "sharing_condition": ["share when", "we may share", "with your consent", "as required by law"],
                "consent_required": ["consent", "agree", "permission", "opt in"],
                "opt_out_available": ["opt out", "unsubscribe", "disable", "withdraw"],
                "deletion_available": ["delete your data", "delete your account", "erasure", "remove your data"],
                "request_channel": ["contact us", "email us", "privacy request", "request form"],
                "retention_policy": KEYWORD_RULES["retention"],
                "encryption_applied": ["encrypt", "encryption"],
                "anonymisation": ["anonymous", "anonymized", "anonymised", "de-identified", "aggregate"],
                "cross_border_transfer": ["international", "cross-border", "outside your country", "other countries"],
                "child_data_involved": ["child", "children", "under 13", "minor"],
                "contact_channel": ["contact us", "email", "privacy@"],
            },
        )
    )
    risk_flags = []
    if retention_policy == "unclear":
        risk_flags.append("unclear_retention")
    if metadata["downstream_stakeholders"] and sharing_condition == "unclear":
        risk_flags.append("vague_third_party_sharing")
    if deletion_available != "yes":
        risk_flags.append("no_deletion_method")
    if any(tag in metadata["data_type_tags"] for tag in ["location", "voice_recording", "eye_tracking", "payment_info"]):
        risk_flags.append("sensitive_data_involved")
    field_values = {
        "sharing_condition": sharing_condition,
        "consent_required": consent_required,
        "opt_out_available": opt_out_available,
        "deletion_available": deletion_available,
        "request_channel": request_channel,
        "retention_policy": retention_policy,
        "encryption_applied": encryption_applied,
        "anonymisation": anonymisation,
        "cross_border_transfer": cross_border_transfer,
        "child_data_involved": child_data_involved,
        "contact_channel": contact_channel,
    }
    metadata_assessment = _metadata_assessment(metadata, field_values, metadata_evidence, risk_flags)
    return {
        "policyId": policy_id,
        "policyVersion": policy_version,
        "publisher_entity": "",
        "policy_url": "",
        "service_name": "",
        "effective_date": "",
        "policy_version": policy_version,
        "document_hash": "",
        **metadata,
        "permitted_usage": metadata["processing_purpose"],
        "sharing_condition": sharing_condition,
        "consent_required": consent_required,
        "opt_out_available": opt_out_available,
        "deletion_available": deletion_available,
        "request_channel": request_channel,
        "retention_policy": retention_policy,
        "encryption_applied": encryption_applied,
        "anonymisation": anonymisation,
        "cross_border_transfer": cross_border_transfer,
        "child_data_involved": child_data_involved,
        "change_summary": "",
        "contact_channel": contact_channel,
        "risk_flags": risk_flags,
        "characterCount": len(raw_file),
        "wordCount": len(words),
        "sectionCount": len(sections),
        "sections": sections[:12],
        "keywordHits": keyword_hits,
        "metadataEvidence": metadata_evidence,
        "metadataAssessment": metadata_assessment,
    }


def generate_report(metadata: dict[str, Any], hash_code: str) -> dict[str, Any]:
    covered = [name for name, hits in metadata["keywordHits"].items() if hits]
    missing = [name for name, hits in metadata["keywordHits"].items() if not hits]
    readiness = round((len(covered) / len(KEYWORD_RULES)) * 100)
    return {
        "summary": f"Policy for {metadata.get('applicationName', metadata['policyId'])} has {metadata['wordCount']} words and {metadata['sectionCount']} detected sections.",
        "readinessScore": readiness,
        "coveredTopics": covered,
        "missingTopics": missing,
        "hashCode": hash_code,
        "recommendation": "Ready for trusted registration" if readiness >= 60 else "Review missing topics before production use",
    }
