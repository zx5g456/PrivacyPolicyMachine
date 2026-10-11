"""Frozen prompt variants for the RQ3 parallel comparison."""

from __future__ import annotations

from server.processor import METADATA_OPTIONS, STATUS_METADATA_FIELDS


CONFIGS = ("C0", "C1", "C2", "C3", "C4")
LIST_FIELDS = tuple(METADATA_OPTIONS)
STATUS_FIELDS = tuple(STATUS_METADATA_FIELDS)
ALL_FIELDS = LIST_FIELDS + STATUS_FIELDS
STATUS_MEANINGS = {
    "sharingCondition": "yes if it states conditions or limits for third-party sharing; no if it explicitly says data is not shared; otherwise unclear",
    "consentRequired": "whether consent is required for a stated processing activity",
    "optOutAvailable": "whether a user can opt out of a stated processing activity",
    "deletionAvailable": "whether a user can request or perform data deletion",
    "requestChannel": "whether a channel is given for privacy or data-rights requests",
    "retentionPolicy": "whether a data retention or deletion rule is stated",
    "encryptionApplied": "whether encryption of data is stated",
    "anonymisation": "whether anonymisation or de-identification is stated",
    "crossBorderTransfer": "whether cross-border data transfer is stated",
    "childDataInvolved": "whether the service collects or processes children's data",
    "contactChannel": "whether a privacy-related contact channel is provided",
}

TASK = """Extract the policy metadata using only the supplied privacy policy text.
For list fields, use only the allowed labels. For status fields, use yes, no, or unclear.
Use no only for an explicit denial; use unclear when the policy does not say.
Do not use outside knowledge. Return one JSON object with a fields object.
Each list field has value (array of allowed labels) and evidence (mapping labels to quote arrays).
Each status field has value (yes/no/unclear) and evidence (quote array).
Evidence quotations, if provided, must be exact contiguous text from the source.
Empty list values use []; absent status information uses unclear.
Allowed list labels:
""" + "\n".join(f"- {key}: {', '.join(values)}" for key, values in METADATA_OPTIONS.items()) + "\nStatus field meanings:\n" + "\n".join(f"- {key}: {STATUS_MEANINGS[key]}" for key in STATUS_FIELDS)

STRUCTURE = """Format constraint: The top-level object must contain exactly the key fields.
The fields object must contain every field named above, with no additional fields.
Every list field must be {"value": [allowed_label, ...], "evidence": {"allowed_label": ["exact quote", ...]}}.
Every status field must be {"value": "yes|no|unclear", "evidence": ["exact quote", ...]}.
Use empty arrays or objects where appropriate. Do not output Markdown or commentary."""

EVIDENCE = """Evidence-first procedure: Before assigning each nonempty list label or yes/no
status, locate a source quotation that directly supports it. Copy that quotation
verbatim into the matching evidence slot. If no supporting text can be located,
leave the list label out or set the status to unclear. Do not infer from a topic
heading, outside knowledge, or a merely related quotation."""

MERGE_BASE = """Combine the chunk outputs into one policy-level JSON object in the
same fields format. Deduplicate list labels. Return one value per status field.
Use only the supplied chunk results and source chunks; do not add new claims."""

MERGE_CHECK = """Cross-chunk consistency procedure: Before producing the policy-level
result, compare every field across all chunks. Deduplicate repeated findings;
check that a quote supporting a finding was actually present in its source chunk.
If chunks appear to disagree, distinguish a real contradiction from a difference
in scope, exception, or condition. Preserve all relevant quotations. For an
unresolved yes/no conflict, output unclear. Never let the last chunk silently
override an earlier chunk."""


def extraction_prompt(config: str, chunk_text: str, index: int, count: int) -> str:
    if config not in CONFIGS:
        raise ValueError(f"Unknown configuration: {config}")
    blocks = [TASK]
    if config in {"C1", "C4"}:
        blocks.append(STRUCTURE)
    if config in {"C2", "C4"}:
        blocks.append(EVIDENCE)
    blocks.append(f"Policy chunk {index + 1} of {count}:\n<policy_chunk>\n{chunk_text}\n</policy_chunk>")
    return "\n\n".join(blocks)


def merge_prompt(config: str, chunk_results: list[dict]) -> str:
    import json

    if config not in CONFIGS:
        raise ValueError(f"Unknown configuration: {config}")
    blocks = [TASK]
    if config in {"C1", "C4"}:
        blocks.append(STRUCTURE)
    if config in {"C2", "C4"}:
        blocks.append(EVIDENCE)
    blocks.append(MERGE_BASE)
    if config in {"C3", "C4"}:
        blocks.append(MERGE_CHECK)
    blocks.append("Chunk results:\n" + json.dumps(chunk_results, ensure_ascii=False))
    return "\n\n".join(blocks)
