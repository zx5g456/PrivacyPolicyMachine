from __future__ import annotations

import hashlib
import re
from typing import Any


KEYWORD_RULES = {
    "personal_data": ["personal information", "personal data", "name", "email", "address"],
    "sharing": ["share", "third party", "partner", "affiliate", "vendor"],
    "retention": ["retain", "retention", "delete", "deletion", "storage period"],
    "rights": ["access", "correct", "erase", "opt out", "withdraw consent"],
    "security": ["security", "encrypt", "safeguard", "breach"],
}


def hash_policy(raw_file: str) -> str:
    return hashlib.sha256(raw_file.encode("utf-8")).hexdigest()


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
    return {
        "policyId": policy_id,
        "policyVersion": policy_version,
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
