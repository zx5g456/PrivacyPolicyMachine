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


class PolicyChunkExtraction(BaseModel):
    """The four fields requested from every policy chunk."""

    model_config = ConfigDict(extra="forbid")

    sharing_condition: ExtractedField
    retention_policy: ExtractedField
    cross_border_transfer: ExtractedField
    child_data_involved: ExtractedField


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
