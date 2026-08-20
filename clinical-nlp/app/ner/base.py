"""NER adapter base interface for Step 2.

Person B's NER stage. The base interface defines the shape of an entity span
and the NERAdapter Protocol that every implementation must satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


# Extraction-source tag — useful for debugging which method surfaced an entity.
# Keep this open as a plain str so future methods (e.g. another transformer) can
# be added without enum churn. The expected values used in this stage are:
#   - "scispacy"     : en_core_sci_md generic biomedical spans
#   - "bc5cdr"       : en_ner_bc5cdr_md Disease / Chemical (->Medication)
#   - "regex"        : dosage/route numeric patterns
#   - "dictionary"   : symptom/allergy/procedure/lab curated lists
EXTRACTION_SOURCE_SCI = "scispacy"
EXTRACTION_SOURCE_BC5CDR = "bc5cdr"
EXTRACTION_SOURCE_REGEX = "regex"
EXTRACTION_SOURCE_DICTIONARY = "dictionary"


@dataclass(frozen=True)
class EntitySpan:
    """A single named-entity mention in a field's processed text."""

    text: str
    start: int
    end: int
    entity_type: str
    confidence: float
    extraction_source: str = EXTRACTION_SOURCE_SCI
    # Optional SNOMED / domain enrichment attached during cross-referencing
    # against PreprocessedField.normalized_concepts.
    snomed_ct_id: str | None = None
    clinical_domain: str | None = None


class NERAdapter(Protocol):
    """Protocol every Person B NER implementation must satisfy."""

    model_name: str

    def extract(self, text: str) -> list[EntitySpan]:
        ...
