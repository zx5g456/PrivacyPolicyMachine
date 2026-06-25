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
    risk_flags = []
    if retention_policy == "unclear":
        risk_flags.append("unclear_retention")
    if metadata["downstream_stakeholders"] and sharing_condition == "unclear":
        risk_flags.append("vague_third_party_sharing")
    if deletion_available != "yes":
        risk_flags.append("no_deletion_method")
    if any(tag in metadata["data_type_tags"] for tag in ["location", "voice_recording", "eye_tracking", "payment_info"]):
        risk_flags.append("sensitive_data_involved")
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
