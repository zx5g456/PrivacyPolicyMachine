"""Local-LLM analysis for privacy policies.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from pydantic import ValidationError

from .llm_client import (
    DEFAULT_MODEL,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    ChatClient,
    OllamaChatClient,
)
from .llm_models import (
    ExtractedField,
    ExtractedListField,
    LLMConnectionError,
    LLMProcessorError,
    LLMResponseError,
    LLMTimeoutError,
    PolicyAnalysis,
    PolicyChunk,
    PolicyChunkExtraction,
)
from .processor import METADATA_RULES


DEFAULT_CHUNK_CHARS = 6_000
DEFAULT_OVERLAP_CHARS = 400


FIELD_NAMES = tuple(PolicyChunkExtraction.model_fields)
LIST_FIELD_NAMES = tuple(METADATA_RULES)
STATUS_FIELD_NAMES = tuple(name for name in FIELD_NAMES if name not in LIST_FIELD_NAMES)

# These terms are not used to perform the extraction.  They are a conservative
# guardrail: a quote about an unrelated topic cannot support a model claim just
# because the quote happens to exist in the source document.
EVIDENCE_TERMS = {
    "sharingCondition": ("share", "sharing", "third party", "disclose", "sell", "共享", "第三方", "披露", "出售"),
    "retentionPolicy": ("retain", "retention", "store", "storage", "delete", "erase", "保存", "保留", "存储", "删除"),
    "crossBorderTransfer": ("international", "cross-border", "country", "countries", "overseas", "transfer", "跨境", "境外", "国家", "传输"),
    "childDataInvolved": ("child", "children", "minor", "under 13", "under 16", "age", "儿童", "未成年人", "年龄"),
    "consentRequired": ("consent", "agree", "permission", "opt in", "同意", "许可"),
    "optOutAvailable": ("opt out", "unsubscribe", "withdraw", "disable", "退出", "撤回", "取消订阅"),
    "deletionAvailable": ("delete", "deletion", "erase", "erasure", "remove", "删除", "清除"),
    "requestChannel": ("contact", "email", "request", "form", "联系", "邮箱", "申请"),
    "encryptionApplied": ("encrypt", "encryption", "加密"),
    "anonymisation": ("anonymous", "anonymized", "anonymised", "de-identified", "aggregate", "匿名", "去标识"),
    "contactChannel": ("contact", "email", "phone", "address", "联系", "邮箱", "电话", "地址"),
}

EXPLICIT_NO_PATTERNS = {
    "sharingCondition": ("do not share", "does not share", "never share", "do not sell", "不会共享", "不共享", "不会出售", "不出售"),
    "retentionPolicy": ("do not retain", "does not retain", "not retained", "do not store", "not stored", "不保留", "不会保留", "不存储", "不会存储"),
    "crossBorderTransfer": ("do not transfer", "not transferred", "no international", "not outside", "不跨境", "不会跨境", "不传输至境外"),
    "childDataInvolved": ("not intended for children", "do not collect from children", "does not collect from children", "no children", "exclude children", "不面向儿童", "不收集儿童", "不涉及儿童", "不面向未成年人"),
    "consentRequired": ("without consent", "consent is not required", "无需同意", "不需要同意"),
    "optOutAvailable": ("cannot opt out", "no opt out", "无法退出", "不能退出"),
    "deletionAvailable": ("cannot delete", "do not delete", "no right to deletion", "无法删除", "不能删除"),
    "requestChannel": ("cannot submit", "no request channel", "无法申请", "没有申请渠道"),
    "encryptionApplied": ("not encrypted", "do not encrypt", "未加密", "不加密"),
    "anonymisation": ("not anonymized", "not anonymised", "do not anonymize", "未匿名", "不匿名"),
    "contactChannel": ("cannot contact", "no contact", "无法联系", "没有联系方式"),
}




def chunk_policy(
    policy_text: str,
    *,
    max_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[PolicyChunk]:
    """Split a policy into overlapping exact slices near natural boundaries.

    Character limits are predictable and inexpensive.  The Ollama context is
    still set separately because character counts are only a token estimate.
    Offsets allow every returned quotation to be checked against the source.
    """

    if not policy_text or not policy_text.strip():
        raise ValueError("Policy text is required")
    if max_chars < 500:
        raise ValueError("max_chars must be at least 500")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be between 0 and max_chars - 1")

    chunks: list[PolicyChunk] = []
    start = 0
    text_length = len(policy_text)
    while start < text_length:
        hard_end = min(start + max_chars, text_length)
        end = hard_end
        if hard_end < text_length:
            # Prefer paragraph, line, or sentence boundaries in the latter half
            # of the window.  Falling back to a space avoids cutting a word.
            lower_bound = start + max_chars // 2
            candidates = [
                policy_text.rfind("\n\n", lower_bound, hard_end),
                policy_text.rfind("\n", lower_bound, hard_end),
                policy_text.rfind(". ", lower_bound, hard_end),
                policy_text.rfind("。", lower_bound, hard_end),
                policy_text.rfind(" ", lower_bound, hard_end),
            ]
            boundary = max(candidates)
            if boundary >= lower_bound:
                end = boundary + (2 if policy_text[boundary:boundary + 2] in {"\n\n", ". "} else 1)

        chunks.append(
            PolicyChunk(index=len(chunks), start=start, end=end, text=policy_text[start:end])
        )
        if end >= text_length:
            break
        # Overlap protects statements that cross a chunk boundary.  Always move
        # forward even if a caller configures an unusually large overlap.
        start = max(start + 1, end - overlap_chars)

    return chunks


def validate_evidence(
    extraction: PolicyChunkExtraction,
    source_text: str,
    *,
    chunk_index: int,
) -> tuple[PolicyChunkExtraction, list[str]]:
    """Remove fabricated/altered quotations and downgrade unsupported claims."""

    cleaned: dict[str, ExtractedField | ExtractedListField] = {}
    errors: list[str] = []
    for field_name in FIELD_NAMES:
        field = getattr(extraction, field_name)
        if field_name in LIST_FIELD_NAMES:
            allowed_values = METADATA_RULES[field_name]
            valid_values: list[str] = []
            valid_evidence_by_value: dict[str, list[str]] = {}
            for value in field.value:
                quotes = field.evidence.get(value, [])
                if value not in allowed_values:
                    errors.append(f"chunk {chunk_index} {field_name}: unsupported value: {value!r}")
                    continue
                valid_quotes = []
                for quote in quotes:
                    if not quote or quote not in source_text:
                        errors.append(f"chunk {chunk_index} {field_name}.{value}: evidence not found verbatim: {quote!r}")
                    else:
                        valid_quotes.append(quote)
                if valid_quotes:
                    valid_values.append(value)
                    valid_evidence_by_value[value] = list(dict.fromkeys(valid_quotes))
                else:
                    errors.append(f"chunk {chunk_index} {field_name}.{value}: no valid evidence")
            cleaned[field_name] = field.model_copy(
                update={
                    "value": valid_values,
                    "evidence": valid_evidence_by_value,
                    "needs_review": field.needs_review or len(valid_values) != len(field.value),
                }
            )
            continue
        valid_evidence: list[str] = []
        for quote in field.evidence:
            if not quote or quote not in source_text:
                errors.append(f"chunk {chunk_index} {field_name}: evidence not found verbatim: {quote!r}")
            elif not _evidence_supports_field(field_name, field.value, quote):
                errors.append(f"chunk {chunk_index} {field_name}: evidence is not relevant to the claimed value: {quote!r}")
            else:
                if quote not in valid_evidence:
                    valid_evidence.append(quote)

        unsupported = field.value != "unclear" and not valid_evidence
        cleaned[field_name] = field.model_copy(
            update={
                "value": "unclear" if unsupported else field.value,
                "evidence": valid_evidence,
                "needs_review": field.needs_review or unsupported or field.value == "unclear",
            }
        )
    return PolicyChunkExtraction(**cleaned), errors


def _evidence_supports_field(field_name: str, value: str, quote: str) -> bool:
    """Apply a small, auditable relevance check after exact-quote validation.

    A negative answer has a higher burden of proof: absence of a statement is
    ``unclear``, not ``no``, so the quote must contain an explicit denial.
    """

    lower_quote = quote.casefold()
    if not any(term in lower_quote for term in EVIDENCE_TERMS[field_name]):
        return False
    if value == "no":
        return any(pattern in lower_quote for pattern in EXPLICIT_NO_PATTERNS[field_name])
    return True


class PolicyLLMProcessor:
    """Coordinate chunking, retrying, validation, and result aggregation."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        client: ChatClient | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        retries: int = DEFAULT_RETRIES,
        retry_delay_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if retries < 0:
            raise ValueError("retries cannot be negative")
        self.model = model
        self.client = client or OllamaChatClient()
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.retry_delay_seconds = retry_delay_seconds
        self.sleep = sleep

    def analyze(
        self,
        policy_text: str,
        *,
        max_chunk_chars: int = DEFAULT_CHUNK_CHARS,
        overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    ) -> PolicyAnalysis:
        chunks = chunk_policy(
            policy_text,
            max_chars=max_chunk_chars,
            overlap_chars=overlap_chars,
        )
        extractions: list[PolicyChunkExtraction] = []
        evidence_errors: list[str] = []
        processing_errors: list[str] = []

        for chunk in chunks:
            try:
                extraction = self._analyze_chunk(chunk)
            except LLMProcessorError as exc:
                # A long policy remains partly useful when one chunk fails.  The
                # final fields are marked for review if any chunk was skipped.
                processing_errors.append(f"chunk {chunk.index}: {exc}")
                continue
            validated, chunk_errors = validate_evidence(
                extraction,
                # The quote must occur in the exact chunk the model saw, which
                # is itself an unchanged slice of the original policy.
                chunk.text,
                chunk_index=chunk.index,
            )
            extractions.append(validated)
            evidence_errors.extend(chunk_errors)

        if not extractions:
            detail = processing_errors[-1] if processing_errors else "unknown model error"
            raise LLMProcessorError(f"No policy chunks could be analyzed: {detail}")

        merged = _merge_extractions(extractions, incomplete=bool(processing_errors))
        return PolicyAnalysis(
            model=self.model,
            chunk_count=len(chunks),
            successful_chunk_count=len(extractions),
            fields=merged,
            evidence_errors=evidence_errors,
            processing_errors=processing_errors,
        )

    def _analyze_chunk(self, chunk: PolicyChunk) -> PolicyChunkExtraction:
        allowed = "\n".join(
            f"- {name}: {', '.join(values)}"
            for name, values in METADATA_RULES.items()
        )
        prompt = (
            f"Analyze policy chunk {chunk.index + 1}. Return the required JSON only.\n"
            f"Allowed values for list fields:\n{allowed}\n\n"
            "Populate details with concrete policy facts such as retention periods, request or contact "
            "channels, encryption standards, sharing conditions, transfer safeguards, and child age "
            "thresholds. Do not use details merely to repeat yes, no, or unclear.\n\n"
            f"<policy_chunk>\n{chunk.text}\n</policy_chunk>"
        )
        last_error: LLMProcessorError | None = None
        for attempt in range(self.retries + 1):
            try:
                content = self.client.chat(
                    model=self.model,
                    prompt=prompt,
                    schema=PolicyChunkExtraction.model_json_schema(),
                    timeout=self.timeout_seconds,
                )
                return PolicyChunkExtraction.model_validate_json(content)
            except ValidationError as exc:
                last_error = LLMResponseError(f"model output failed schema validation: {exc}")
            except (LLMTimeoutError, LLMConnectionError, LLMResponseError) as exc:
                last_error = exc

            if attempt < self.retries:
                # Linear backoff keeps local transient failures from causing an
                # immediate second request while avoiding long API stalls.
                self.sleep(self.retry_delay_seconds * (attempt + 1))

        assert last_error is not None
        raise last_error


def _merge_extractions(
    extractions: list[PolicyChunkExtraction],
    *,
    incomplete: bool,
) -> PolicyChunkExtraction:
    """Merge overlapping chunk results and expose cross-chunk contradictions."""

    merged: dict[str, ExtractedField | ExtractedListField] = {}
    for field_name in FIELD_NAMES:
        fields = [getattr(item, field_name) for item in extractions]
        if field_name in LIST_FIELD_NAMES:
            values: list[str] = []
            evidence: dict[str, list[str]] = {}
            details: list[str] = []
            for field in fields:
                for value in field.value:
                    if value not in values:
                        values.append(value)
                    evidence.setdefault(value, [])
                    evidence[value].extend(
                        quote for quote in field.evidence.get(value, [])
                        if quote not in evidence[value]
                    )
                if field.details and field.details not in details:
                    details.append(field.details)
            merged[field_name] = ExtractedListField(
                value=values,
                evidence=evidence,
                details=" ".join(details),
                needs_review=incomplete or any(field.needs_review for field in fields),
            )
            continue
        supported_values = {field.value for field in fields if field.value != "unclear"}
        conflict = len(supported_values) > 1
        value = "unclear" if conflict or not supported_values else next(iter(supported_values))

        evidence: list[str] = []
        details: list[str] = []
        for field in fields:
            if field.value == value and not conflict:
                evidence.extend(quote for quote in field.evidence if quote not in evidence)
                if field.details and field.details not in details:
                    details.append(field.details)

        merged[field_name] = ExtractedField(
            value=value,
            evidence=evidence,
            details=" ".join(details),
            needs_review=(
                incomplete
                or conflict
                or value == "unclear"
                or any(field.needs_review for field in fields if field.value == value)
            ),
        )
    return PolicyChunkExtraction(**merged)


def analyze_policy(policy_text: str, **processor_options: Any) -> dict[str, Any]:
    """Convenience function for the HTTP layer and small scripts."""

    return PolicyLLMProcessor(**processor_options).analyze(policy_text).model_dump()
