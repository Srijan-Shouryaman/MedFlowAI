"""Step 2 — Person A / Person B boundary contract.

The shape of data that flows out of Person A's stages
(preprocess -> abbreviations -> terminology) and into Person B's stages
(NER -> contextualization -> event_builder -> validation).

Person A owns the implementation; Person B owns the *type* that her output
has to satisfy. Anything Person B code reads from a PreprocessedField goes
through this model so we have one place to evolve the contract.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SourceMetadata(BaseModel):
    """Provenance metadata for a single preprocessed field."""

    model_config = ConfigDict(extra="allow")

    input_modality: str
    source_language: str = "en"
    translation_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    field_type: str = "clinical_text"
    source_document_id: UUID | None = None


class AbbreviationSpan(BaseModel):
    """One abbreviation occurrence detected by Person A."""

    model_config = ConfigDict(extra="ignore")

    span: dict[str, int] = Field(default_factory=dict)
    surface_text: str
    status: str = "unknown"  # resolved | ambiguous | unknown
    expansion: str | None = None
    candidates: list[str] = Field(default_factory=list)
    resolution_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class NormalizedConcept(BaseModel):
    """One SNOMED-grounded concept Person A's terminology stage attached."""

    model_config = ConfigDict(extra="ignore")

    span: dict[str, int] = Field(default_factory=dict)
    surface_text: str
    normalized_concept: str
    snomed_ct_id: str | None = None
    clinical_domain: str | None = None


class Step2PreprocessedField(BaseModel):
    """Boundary contract between Person A and Person B.

    Person B's NER, contextualization, event_builder, and validation all
    receive this shape. Person A's pipeline (preprocess -> abbreviations ->
    terminology) produces it. When Person A's code is not yet wired in, an
    explicit shim (see app/pipeline.py -> _passthrough_preprocess) builds
    a minimal one with empty abbreviations/normalized_concepts.
    """

    model_config = ConfigDict(extra="forbid")

    field_id: str
    original_text: str = Field(min_length=1)
    processed_text: str = Field(min_length=1)
    source_metadata: SourceMetadata
    abbreviations: list[AbbreviationSpan] = Field(default_factory=list)
    normalized_concepts: list[NormalizedConcept] = Field(default_factory=list)
    # Person A may attach arbitrary flags (e.g. preprocessing_flags); we keep
    # an open dict so her future stages can pass-through debug info without
    # breaking Person B.
    preprocessing_flags: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AbbreviationSpan",
    "NormalizedConcept",
    "SourceMetadata",
    "Step2PreprocessedField",
]
