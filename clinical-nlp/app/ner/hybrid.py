"""Hybrid NER adapter — Person B's Stage 4.

Composes four extractors and merges / dedupes their results:
  1. scispaCy en_core_sci_md     -> general biomedical spans
  2. scispaCy en_ner_bc5cdr_md    -> Disease + Chemical (-> Medication) typing
  3. regex                        -> Dosage patterns, Route vocabulary
  4. dictionary                   -> Symptom / Allergy / Procedure / Lab curated lists

Outputs a list[EntitySpan] sorted by start offset. Each entity carries
`extraction_source` so downstream stages can debug which method found it.

The adapter loads spaCy models lazily on first .extract() call to keep
import-time cheap. If a model is missing the adapter raises
NLPModelUnavailableError with a clear remediation message — we never
silently fall back to a degraded extractor.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..pipeline_types import Step2PreprocessedField
from .base import (
    EXTRACTION_SOURCE_BC5CDR,
    EXTRACTION_SOURCE_DICTIONARY,
    EXTRACTION_SOURCE_REGEX,
    EXTRACTION_SOURCE_SCI,
    EntitySpan,
)
from .entity_dictionaries import (
    ALLERGY_TERMS,
    ENTITY_TYPE_ALLERGY,
    ENTITY_TYPE_DOSAGE,
    ENTITY_TYPE_LAB,
    ENTITY_TYPE_MEDICATION,
    ENTITY_TYPE_PROCEDURE,
    ENTITY_TYPE_ROUTE,
    ENTITY_TYPE_SYMPTOM,
    LAB_TERMS,
    PROCEDURE_TERMS,
    ROUTE_TERMS,
    SYMPTOM_TERMS,
)


# ---- regex patterns ----

# Dosage: a number (int or decimal) followed by a unit. \b boundaries prevent
# matching things like "100ml" inside longer words.
_DOSAGE_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:mg|mcg|µg|ug|ml|mL|cc|g|kg|units|IU)\b",
    flags=re.IGNORECASE,
)

# Sentence splitter for the contextualization stage. We use the same simple
# regex here that spaCy's sentencizer would emit, so the rest of the pipeline
# doesn't need spaCy just to chunk sentences.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


class NLPModelUnavailableError(RuntimeError):
    """Raised when a required NLP model cannot be loaded."""


class HybridNERAdapter:
    """scispaCy + bc5cdr + regex + dictionary NER.

    Lazy-loads spaCy models on first use. If you want to inject pre-loaded
    models (e.g. for tests), pass them via the constructor.
    """

    model_name = "hybrid-scispacy-bc5cdr-regex-dictionary"

    _SCISPACY_MODEL = "en_core_sci_md"
    _BC5CDR_MODEL = "en_ner_bc5cdr_md"

    def __init__(
        self,
        *,
        scispacy_nlp=None,
        bc5cdr_nlp=None,
        load_models: bool = True,
    ) -> None:
        # spaCy Language objects. None until first use (or injected).
        self._scispacy_nlp = scispacy_nlp
        self._bc5cdr_nlp = bc5cdr_nlp
        self._load_models = load_models

    # ----- public API -----

    def extract(self, text: str) -> list[EntitySpan]:
        entities: list[EntitySpan] = []
        entities.extend(self._extract_scispacy(text))
        entities.extend(self._extract_bc5cdr(text))
        entities.extend(self._extract_regex(text))
        entities.extend(self._extract_dictionary(text))
        return _dedupe_overlapping(entities)

    def extract_with_enrichment(
        self,
        field: Step2PreprocessedField,
    ) -> list[EntitySpan]:
        """Extract entities AND cross-reference Person A's normalized_concepts.

        Use this from the pipeline; the plain .extract() is exposed for
        Stage 4 standalone testing.
        """
        entities = self.extract(field.processed_text)
        return _attach_normalized_concepts(entities, field)

    # ----- private extractors -----

    def _extract_scispacy(self, text: str) -> list[EntitySpan]:
        nlp = self._get_scispacy()
        if nlp is None:
            return []
        spans: list[EntitySpan] = []
        doc = nlp(text)
        for ent in doc.ents:
            if not ent.text.strip():
                continue
            spans.append(
                EntitySpan(
                    text=ent.text,
                    start=ent.start_char,
                    end=ent.end_char,
                    # scispaCy does not produce a fine-grained entity_type on
                    # en_core_sci_md; default to "Disease" as the closest
                    # generic biomedical category. bc5cdr/validation will
                    # refine downstream.
                    entity_type="Disease",
                    confidence=0.75,
                    extraction_source=EXTRACTION_SOURCE_SCI,
                )
            )
        return spans

    def _extract_bc5cdr(self, text: str) -> list[EntitySpan]:
        nlp = self._get_bc5cdr()
        if nlp is None:
            return []
        spans: list[EntitySpan] = []
        doc = nlp(text)
        for ent in doc.ents:
            label = ent.label_.upper()
            # BC5CDR has two labels: DISEASE and CHEMICAL. We re-type CHEMICAL
            # to Medication per the brief.
            if label == "DISEASE":
                entity_type = "Disease"
            elif label == "CHEMICAL":
                entity_type = "Medication"
            else:
                continue
            if not ent.text.strip():
                continue
            spans.append(
                EntitySpan(
                    text=ent.text,
                    start=ent.start_char,
                    end=ent.end_char,
                    entity_type=entity_type,
                    confidence=0.85,
                    extraction_source=EXTRACTION_SOURCE_BC5CDR,
                )
            )
        return spans

    def _extract_regex(self, text: str) -> list[EntitySpan]:
        spans: list[EntitySpan] = []
        # Dosage
        for match in _DOSAGE_PATTERN.finditer(text):
            spans.append(
                EntitySpan(
                    text=match.group(0),
                    start=match.start(),
                    end=match.end(),
                    entity_type=ENTITY_TYPE_DOSAGE,
                    confidence=0.95,
                    extraction_source=EXTRACTION_SOURCE_REGEX,
                )
            )
        # Route — vocabulary match
        lowered = text.casefold()
        for route in ROUTE_TERMS:
            pattern = re.compile(rf"(?<!\w){re.escape(route)}(?!\w)", flags=re.IGNORECASE)
            for match in pattern.finditer(text):
                # Sanity-check: word-boundary match in lowered form too, to
                # avoid matching inside other words.
                if lowered[match.start() : match.end()] != route.casefold():
                    continue
                spans.append(
                    EntitySpan(
                        text=match.group(0),
                        start=match.start(),
                        end=match.end(),
                        entity_type=ENTITY_TYPE_ROUTE,
                        confidence=0.92,
                        extraction_source=EXTRACTION_SOURCE_REGEX,
                    )
                )
        return spans

    def _extract_dictionary(self, text: str) -> list[EntitySpan]:
        spans: list[EntitySpan] = []
        for table, entity_type in (
            (SYMPTOM_TERMS, ENTITY_TYPE_SYMPTOM),
            (ALLERGY_TERMS, ENTITY_TYPE_ALLERGY),
            (PROCEDURE_TERMS, ENTITY_TYPE_PROCEDURE),
            (LAB_TERMS, ENTITY_TYPE_LAB),
        ):
            spans.extend(_dictionary_extract(text, table, entity_type))
        return spans

    # ----- model loading -----

    def _get_scispacy(self):
        if self._scispacy_nlp is None and self._load_models:
            self._scispacy_nlp = _load_spacy(self._SCISPACY_MODEL)
        return self._scispacy_nlp

    def _get_bc5cdr(self):
        if self._bc5cdr_nlp is None and self._load_models:
            self._bc5cdr_nlp = _load_spacy(self._BC5CDR_MODEL)
        return self._bc5cdr_nlp


# ----- module-level helpers -----


def _load_spacy(model_name: str):
    try:
        import spacy  # type: ignore
    except ImportError as exc:  # pragma: no cover - install-time
        raise NLPModelUnavailableError(
            f"spaCy is not installed; cannot load model '{model_name}'."
        ) from exc
    try:
        return spacy.load(model_name)
    except OSError as exc:
        raise NLPModelUnavailableError(
            f"spaCy model '{model_name}' is not installed. "
            f"Run: pip install <wheel> && pip install {model_name}"
        ) from exc


def _dictionary_extract(
    text: str,
    table: Iterable[tuple[str, str]],
    entity_type: str,
) -> list[EntitySpan]:
    spans: list[EntitySpan] = []
    for surface, _canonical in table:
        pattern = re.compile(rf"(?<!\w){re.escape(surface)}(?!\w)", flags=re.IGNORECASE)
        for match in pattern.finditer(text):
            spans.append(
                EntitySpan(
                    text=match.group(0),
                    start=match.start(),
                    end=match.end(),
                    entity_type=entity_type,
                    confidence=0.88,
                    extraction_source=EXTRACTION_SOURCE_DICTIONARY,
                )
            )
    return spans


def _dedupe_overlapping(entities: list[EntitySpan]) -> list[EntitySpan]:
    """Drop overlaps and prefer higher-confidence / longer matches.

    Rules:
      1. If two entities overlap, keep the one with higher confidence.
      2. If confidences are equal, keep the longer span.
    """
    if not entities:
        return []

    # Sort: highest confidence first, then longest span.
    sorted_entities = sorted(
        entities,
        key=lambda e: (-e.confidence, -(e.end - e.start)),
    )
    kept: list[EntitySpan] = []
    occupied: list[tuple[int, int]] = []

    for ent in sorted_entities:
        span = (ent.start, ent.end)
        if any(_overlaps(span, occ) for occ in occupied):
            continue
        kept.append(ent)
        occupied.append(span)

    kept.sort(key=lambda e: e.start)
    return kept


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _attach_normalized_concepts(
    entities: list[EntitySpan],
    field: Any,
) -> list[EntitySpan]:
    """Cross-reference NER spans against Person A's normalized_concepts.

    Where a normalized_concept's span overlaps an NER span,
    copy its snomed_ct_id + clinical_domain onto the entity.
    """
    concepts = getattr(field, "normalized_concepts", None)
    if not concepts and isinstance(field, dict):
        concepts = field.get("normalized_concepts")
    if not concepts:
        return entities

    enriched: list[EntitySpan] = []
    for ent in entities:
        snomed, domain = None, None
        for concept in concepts:
            if isinstance(concept, dict):
                span = concept.get("span")
                if isinstance(span, dict):
                    c_start = span.get("start", -1)
                    c_end = span.get("end", -1)
                else:
                    c_start = concept.get("start_char", concept.get("start", -1))
                    c_end = concept.get("end_char", concept.get("end", -1))
                c_snomed = concept.get("snomed_ct_id")
                c_domain = concept.get("clinical_domain")
            else:
                span = getattr(concept, "span", {})
                if isinstance(span, dict):
                    c_start = span.get("start", -1)
                    c_end = span.get("end", -1)
                else:
                    c_start = getattr(concept, "start_char", getattr(concept, "start", -1))
                    c_end = getattr(concept, "end_char", getattr(concept, "end", -1))
                c_snomed = getattr(concept, "snomed_ct_id", None)
                c_domain = getattr(concept, "clinical_domain", None)

            if c_start is not None and c_end is not None and c_start >= 0 and c_end > c_start:
                if _overlaps((ent.start, ent.end), (c_start, c_end)):
                    snomed = snomed or c_snomed
                    domain = domain or c_domain

        if snomed or domain:
            ent = EntitySpan(
                text=ent.text,
                start=ent.start,
                end=ent.end,
                entity_type=ent.entity_type,
                confidence=ent.confidence,
                extraction_source=ent.extraction_source,
                snomed_ct_id=snomed or ent.snomed_ct_id,
                clinical_domain=domain or ent.clinical_domain,
            )
        enriched.append(ent)
    return enriched


def split_sentences(text: str) -> list[str]:
    """Lightweight sentence splitter — exposed for Stage 5's contextualization."""
    if not text:
        return []
    parts = _SENTENCE_SPLIT.split(text.strip())
    return [p for p in parts if p]
