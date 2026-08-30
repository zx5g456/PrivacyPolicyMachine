"""Data models and domain errors for local-LLM policy analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LLMProcessorError(RuntimeError):
    """Base class for errors that can safely be reported by the API layer."""


class LLMTimeoutError(LLMProcessorError):
    """The local model did not answer before the configured timeout."""


class LLMConnectionError(LLMProcessorError):
    """Ollama is unavailable or returned a retryable server error."""


class LLMResponseError(LLMProcessorError):
    """Ollama or the model returned an invalid response."""


class ExtractedField(BaseModel):
    """One policy finding produced by the model."""

    model_config = ConfigDict(extra="forbid")

    value: Literal["yes", "no", "unclear"]
    evidence: list[str] = Field(default_factory=list)
    details: str = Field(
        default="",
        description=(
            "A concise explanation based only on the supplied policy text. Include concrete "
            "conditions, periods, channels, safeguards, transfer mechanisms, locations, or age "
            "thresholds when the field supports them; do not merely restate yes, no, or unclear."
        ),
    )
    needs_review: bool = False


class ExtractedListField(BaseModel):
    """One multi-value policy finding produced by the model."""

    model_config = ConfigDict(extra="forbid")

    value: list[str] = Field(default_factory=list)
    evidence: dict[str, list[str]] = Field(default_factory=dict)
    details: str = Field(
        default="",
        description=(
            "A concise explanation based only on the supplied policy text, including named "
            "providers, contexts, purposes, or usage limitations when available."
        ),
    )
    needs_review: bool = False


class PolicyChunkExtraction(BaseModel):
    """All reviewable metadata requested from every policy chunk."""

    model_config = ConfigDict(extra="forbid")

    dataTypeTags: ExtractedListField
    dataSourceTypes: ExtractedListField
    collectionContext: ExtractedListField
    processingPurpose: ExtractedListField
    permittedUsage: ExtractedListField
    thirdPartySources: ExtractedListField
    downstreamStakeholders: ExtractedListField
    thirdPartyPurpose: ExtractedListField
    regulatoryFramework: ExtractedListField
    sharingCondition: ExtractedField
    consentRequired: ExtractedField
    optOutAvailable: ExtractedField
    deletionAvailable: ExtractedField
    requestChannel: ExtractedField
    retentionPolicy: ExtractedField
    encryptionApplied: ExtractedField
    anonymisation: ExtractedField
    crossBorderTransfer: ExtractedField
    childDataInvolved: ExtractedField
    contactChannel: ExtractedField


class PolicyAnalysis(BaseModel):
    """Merged result returned to the API consumer."""

    model_config = ConfigDict(extra="forbid")

    model: str
    chunk_count: int
    successful_chunk_count: int
    fields: PolicyChunkExtraction
    evidence_errors: list[str] = Field(default_factory=list)
    processing_errors: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class PolicyChunk:
    """An exact slice of the original policy, including its character offsets."""

    index: int
    start: int
    end: int
    text: str
