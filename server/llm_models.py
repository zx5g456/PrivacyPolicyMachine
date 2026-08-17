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
        description="A short explanation based only on the supplied policy text.",
    )
    needs_review: bool = False


class ExtractedListField(BaseModel):
    """One multi-value policy finding produced by the model."""

    model_config = ConfigDict(extra="forbid")

    value: list[str] = Field(default_factory=list)
    evidence: dict[str, list[str]] = Field(default_factory=dict)
    details: str = Field(default="")
    needs_review: bool = False


class PolicyChunkExtraction(BaseModel):
    """All reviewable metadata requested from every policy chunk."""

    model_config = ConfigDict(extra="forbid")

    data_type_tags: ExtractedListField
    data_source_types: ExtractedListField
    collection_context: ExtractedListField
    processing_purpose: ExtractedListField
    third_party_sources: ExtractedListField
    downstream_stakeholders: ExtractedListField
    third_party_purpose: ExtractedListField
    regulatory_framework: ExtractedListField
    sharing_condition: ExtractedField
    consent_required: ExtractedField
    opt_out_available: ExtractedField
    deletion_available: ExtractedField
    request_channel: ExtractedField
    retention_policy: ExtractedField
    encryption_applied: ExtractedField
    anonymisation: ExtractedField
    cross_border_transfer: ExtractedField
    child_data_involved: ExtractedField
    contact_channel: ExtractedField


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
