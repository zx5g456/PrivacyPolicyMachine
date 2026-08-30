from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any


KEYWORD_RULES = {
    "personalData": ["personal information", "personal data", "name", "email", "address"],
    "sharing": ["share", "third party", "partner", "affiliate", "vendor"],
    "retention": ["retain", "retention", "delete", "deletion", "storage period"],
    "rights": ["access", "correct", "erase", "opt out", "withdraw consent"],
    "security": ["security", "encrypt", "safeguard", "breach"],
}

METADATA_RULES = {
    "dataTypeTags": {
        "location": ["location", "gps", "geolocation"],
        "voice_recording": ["voice", "audio", "recording", "microphone"],
        "eye_tracking": ["eye tracking", "gaze"],
        "device_id": ["device id", "device identifier", "identifier"],
        "payment_info": ["payment", "credit card", "billing"],
        "contact_info": ["email", "phone", "address"],
    },
    "dataSourceTypes": {
        "user_provided": ["provide", "submit", "enter", "account"],
        "device_sensor": ["sensor", "device", "camera", "microphone"],
        "third_party_login": ["google login", "facebook login", "single sign-on", "third party login"],
        "cookies": ["cookie", "tracking technology"],
        "xr_headset_sensor": ["xr headset", "vr headset", "ar headset", "headset"],
    },
    "collectionContext": {
        "during_payment": ["payment", "purchase", "billing"],
        "account_registration": ["register", "sign up", "create an account"],
        "service_usage": ["use our service", "use the app", "interact"],
        "customer_support": ["support", "contact us"],
    },
    "processingPurpose": {
        "advertising": ["advertising", "ads", "marketing"],
        "analytics": ["analytics", "measure", "improve"],
        "payment_processing": ["payment processing", "process payment", "billing"],
        "service_provision": ["provide", "operate", "deliver"],
        "security": ["security", "fraud", "protect"],
    },
    "permittedUsage": {
        "service_operation": ["service operation", "operate", "provide services"],
        "personalization": ["personalize", "personalise", "personalization", "tailor", "customize"],
        "marketing": ["marketing", "promotional", "promotion"],
        "product_improvement": ["product improvement", "improve our service", "improve our product", "develop"],
    },
    "thirdPartySources": {
        "google_login": ["google login", "google account"],
        "facebook_login": ["facebook login", "facebook account"],
        "payment_processor": ["payment processor", "stripe", "paypal"],
    },
    "downstreamStakeholders": {
        "cloud_provider": ["cloud provider", "hosting provider", "aws", "azure", "google cloud"],
        "analytics_provider": ["analytics provider", "google analytics"],
        "advertising_partner": ["advertising partner", "ad network"],
        "payment_processor": ["payment processor", "stripe", "paypal"],
        "email_provider": ["email provider", "email delivery", "sendgrid", "mailgun"],
    },
    "thirdPartyPurpose": {
        "payment_processing": ["payment processing", "process payment"],
        "analytics": ["analytics", "measure"],
        "advertising": ["advertising", "ads"],
        "service_delivery": ["provide services", "service provider"],
        "authentication": ["authentication", "authenticate", "single sign-on", "login"],
        "email_delivery": ["email delivery", "deliver email", "send email"],
    },
    "regulatoryFramework": {
        "GDPR": ["gdpr", "general data protection regulation"],
        "CCPA": ["ccpa", "california consumer privacy act"],
        "COPPA": ["coppa", "children's online privacy protection"],
        "HIPAA": ["hipaa"],
    },
}

LIST_METADATA_FIELDS = tuple(METADATA_RULES)
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
REVIEWABLE_METADATA_FIELDS = LIST_METADATA_FIELDS + STATUS_METADATA_FIELDS

RISK_FLAG_DETAILS = {
    "unclear_retention": "The policy does not state a clear retention period.",
    "vague_third_party_sharing": "Third-party sharing is described without clear conditions.",
    "no_deletion_method": "The policy does not provide a supported deletion method.",
    "sensitive_data_involved": "The policy covers sensitive data that requires additional safeguards.",
    "review_recommended": "Human review is recommended before trusted registration.",
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

NEGATION_TERMS = {
    "no",
    "not",
    "never",
    "neither",
    "nor",
    "without",
    "cannot",
    "can't",
    "don't",
    "doesn't",
    "didn't",
    "won't",
    "isn't",
    "aren't",
}
NEGATION_WINDOW = 4
COMPLEX_SENTENCE_WORDS = 30
COMPLEX_CLAUSE_MARKERS = {
    "although",
    "because",
    "but",
    "except",
    "however",
    "if",
    "unless",
    "whereas",
    "while",
    "which",
    "who",
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


def require_canonical_metadata_keys(metadata: dict[str, Any]) -> None:
    """Reject snake_case field names in canonical metadata containers."""
    containers = {
        "metadata": metadata,
        "metadataEvidence": metadata.get("metadataEvidence"),
        "metadataDetails": metadata.get("metadataDetails"),
        "metadataAssessment": metadata.get("metadataAssessment"),
        "keywordHits": metadata.get("keywordHits"),
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


def _tokens(text: str) -> list[str]:
    return re.findall(r"\b[\w']+\b", text.casefold())


def _keyword_is_negated(text: str, keyword: str, window: int = NEGATION_WINDOW) -> bool:
    """Return whether a negation occurs close to a keyword occurrence."""
    text_tokens = _tokens(text)
    keyword_tokens = _tokens(keyword)
    if not keyword_tokens:
        return False

    width = len(keyword_tokens)
    for start in range(len(text_tokens) - width + 1):
        if text_tokens[start:start + width] != keyword_tokens:
            continue
        nearby = text_tokens[max(0, start - window):min(len(text_tokens), start + width + window)]
        for index, token in enumerate(nearby):
            if token not in NEGATION_TERMS:
                continue
            # "not only X" introduces an addition, rather than negating X.
            if token == "not" and index + 1 < len(nearby) and nearby[index + 1] == "only":
                continue
            return True
    return False


def _evidence_has_negated_keyword(evidence: list[str], keywords: list[str]) -> bool:
    return any(
        _keyword_is_negated(sentence, keyword)
        for sentence in evidence
        for keyword in keywords
    )


def _is_complex_sentence(sentence: str) -> bool:
    tokens = _tokens(sentence)
    clause_markers = sum(token in COMPLEX_CLAUSE_MARKERS for token in tokens)
    punctuation_clauses = len(re.findall(r"[,;:]", sentence))
    return (
        len(tokens) >= COMPLEX_SENTENCE_WORDS
        or clause_markers >= 2
        or clause_markers >= 1 and punctuation_clauses >= 2
    )


# Calculate confidence based on the presence of evidence and keywords. If the value is "unclear", return a low confidence. If there is no evidence, return a medium confidence. If there is evidence and any keyword matches, return a high confidence. Otherwise, return a medium-high confidence.
def _confidence_for_evidence(evidence: list[str], keywords: list[str], value: Any) -> float:
    if value == "unclear":
        return 0.35
    if not evidence:
        return 0.55

    joined = " ".join(evidence).lower()
    if any(keyword in joined for keyword in keywords if " " in keyword or len(keyword) >= 8):
        confidence = 0.9
    else:
        confidence = 0.75

    if _evidence_has_negated_keyword(evidence, keywords):
        confidence -= 0.25
    if any(_is_complex_sentence(sentence) for sentence in evidence):
        confidence -= 0.15
    return round(max(0.0, confidence), 2)


def _review_status(confidence: float, value: Any, force_review: bool = False) -> str:
    if force_review or value == "unclear" or confidence < 0.7:
        return REVIEW_NEEDS_REVIEW
    return REVIEW_AUTO_EXTRACTED


def _assessment_entry(confidence: float, value: Any, force_review: bool = False) -> dict[str, Any]:
    return {
        "confidence": confidence,
        "reviewStatus": _review_status(confidence, value, force_review),
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
        "sharingCondition": ["share when", "we may share", "with your consent", "as required by law"],
        "consentRequired": ["consent", "agree", "permission", "opt in"],
        "optOutAvailable": ["opt out", "unsubscribe", "disable", "withdraw"],
        "deletionAvailable": ["delete your data", "delete your account", "erasure", "remove your data"],
        "requestChannel": ["contact us", "email us", "privacy request", "request form"],
        "retentionPolicy": KEYWORD_RULES["retention"],
        "encryptionApplied": ["encrypt", "encryption"],
        "anonymisation": ["anonymous", "anonymized", "anonymised", "de-identified", "aggregate"],
        "crossBorderTransfer": ["international", "cross-border", "outside your country", "other countries"],
        "childDataInvolved": ["child", "children", "under 13", "minor"],
        "contactChannel": ["contact us", "email", "privacy@"],
    }
    for field, value in field_values.items():
        evidence = metadata_evidence.get(field, [])
        confidence = _confidence_for_evidence(evidence, evidence_keywords.get(field, []), value)
        assessment[field] = _assessment_entry(confidence, value)

    assessment["riskFlags"] = {
        flag: _assessment_entry(0.8, flag, force_review=True)
        for flag in risk_flags
    }
    return assessment


def _evidence_lines(evidence: Any) -> list[str]:
    if isinstance(evidence, str):
        return [evidence] if evidence.strip() else []
    if isinstance(evidence, list):
        return [str(item) for item in evidence if str(item).strip()]
    if isinstance(evidence, dict):
        return [line for value in evidence.values() for line in _evidence_lines(value)]
    return []


def _metadata_details(metadata_evidence: dict[str, Any], risk_flags: list[str]) -> dict[str, str]:
    details = {
        field: " ".join(dict.fromkeys(_evidence_lines(metadata_evidence.get(field))))
        for field in REVIEWABLE_METADATA_FIELDS
    }
    details["riskFlags"] = " ".join(RISK_FLAG_DETAILS[flag] for flag in risk_flags)
    return details


def _yes_no_unclear(lower: str, positive: list[str], negative: list[str] | None = None) -> str:
    if negative and any(term in lower for term in negative):
        return "no"
    sentences = _sentences(lower)
    found_negated = False
    for sentence in sentences:
        for term in positive:
            if term not in sentence:
                continue
            if _keyword_is_negated(sentence, term):
                found_negated = True
            else:
                return "yes"
    if found_negated:
        return "no"
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
    retention_policy = "yes" if keyword_hits["retention"] else "unclear"
    sharing_condition = "yes" if any(term in lower for term in ["share when", "we may share", "with your consent", "as required by law"]) else "unclear"
    request_channel = "yes" if any(term in lower for term in ["contact us", "email us", "privacy request", "request form"]) else "unclear"
    contact_channel = "yes" if any(term in lower for term in ["contact us", "email", "privacy@"]) else "unclear"
    metadata_evidence.update(
        _field_evidence(
            raw_file,
            {
                "sharingCondition": ["share when", "we may share", "with your consent", "as required by law"],
                "consentRequired": ["consent", "agree", "permission", "opt in"],
                "optOutAvailable": ["opt out", "unsubscribe", "disable", "withdraw"],
                "deletionAvailable": ["delete your data", "delete your account", "erasure", "remove your data"],
                "requestChannel": ["contact us", "email us", "privacy request", "request form"],
                "retentionPolicy": KEYWORD_RULES["retention"],
                "encryptionApplied": ["encrypt", "encryption"],
                "anonymisation": ["anonymous", "anonymized", "anonymised", "de-identified", "aggregate"],
                "crossBorderTransfer": ["international", "cross-border", "outside your country", "other countries"],
                "childDataInvolved": ["child", "children", "under 13", "minor"],
                "contactChannel": ["contact us", "email", "privacy@"],
            },
        )
    )
    risk_flags = []
    if retention_policy == "unclear":
        risk_flags.append("unclear_retention")
    if metadata["downstreamStakeholders"] and sharing_condition == "unclear":
        risk_flags.append("vague_third_party_sharing")
    if deletion_available != "yes":
        risk_flags.append("no_deletion_method")
    if any(tag in metadata["dataTypeTags"] for tag in ["location", "voice_recording", "eye_tracking", "payment_info"]):
        risk_flags.append("sensitive_data_involved")
    if risk_flags:
        risk_flags.append("review_recommended")
    field_values = {
        "sharingCondition": sharing_condition,
        "consentRequired": consent_required,
        "optOutAvailable": opt_out_available,
        "deletionAvailable": deletion_available,
        "requestChannel": request_channel,
        "retentionPolicy": retention_policy,
        "encryptionApplied": encryption_applied,
        "anonymisation": anonymisation,
        "crossBorderTransfer": cross_border_transfer,
        "childDataInvolved": child_data_involved,
        "contactChannel": contact_channel,
    }
    metadata_assessment = _metadata_assessment(metadata, field_values, metadata_evidence, risk_flags)
    metadata_details = _metadata_details(metadata_evidence, risk_flags)
    return {
        "policyId": policy_id,
        "policyVersion": policy_version,
        "publisherEntity": "",
        "policyUrl": "",
        "serviceName": "",
        "effectiveDate": "",
        "documentHash": "",
        **metadata,
        "sharingCondition": sharing_condition,
        "consentRequired": consent_required,
        "optOutAvailable": opt_out_available,
        "deletionAvailable": deletion_available,
        "requestChannel": request_channel,
        "retentionPolicy": retention_policy,
        "encryptionApplied": encryption_applied,
        "anonymisation": anonymisation,
        "crossBorderTransfer": cross_border_transfer,
        "childDataInvolved": child_data_involved,
        "changeSummary": "",
        "contactChannel": contact_channel,
        "riskFlags": risk_flags,
        "characterCount": len(raw_file),
        "wordCount": len(words),
        "sectionCount": len(sections),
        "sections": sections[:12],
        "keywordHits": keyword_hits,
        "metadataEvidence": metadata_evidence,
        "metadataDetails": metadata_details,
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
