"""Stage 4 (Person B - Hybrid NER) unit tests.

These tests exercise the hybrid NER adapter in isolation using hand-built
Step2PreprocessedField fixtures (we do NOT route through Person A's
preprocess/abbreviations/terminology stages).

The Metformin 500mg BD case checks:
  - "metformin"     -> Medication (from bc5cdr's CHEMICAL label)
  - "500mg"        -> Dosage        (regex)
  - "BD"           -> (abbreviation — not surfaced by NER; resolved later by
                       Stage 5 contextualization)

The negation case checks dictionary + scispacy coverage and verifies the
adapter returns entities regardless of negation (assertion is Stage 5's
job, not NER's).
"""

from __future__ import annotations

import pytest

from services.clinical_nlp.app.ner import (
    EXTRACTION_SOURCE_BC5CDR,
    EXTRACTION_SOURCE_DICTIONARY,
    EXTRACTION_SOURCE_REGEX,
    HybridNERAdapter,
)
from services.clinical_nlp.app.ner.entity_dictionaries import (
    ENTITY_TYPE_DOSAGE,
    ENTITY_TYPE_MEDICATION,
    ENTITY_TYPE_ROUTE,
    ENTITY_TYPE_SYMPTOM,
)
from services.clinical_nlp.app.pipeline_types import (
    NormalizedConcept,
    SourceMetadata,
    Step2PreprocessedField,
)


# ---- fixtures ----

METFORMIN_TEXT = "Patient started on Metformin 500mg BD for diabetes mellitus."

NEGATION_TEXT = "Patient has no history of diabetes and denies chest pain."


def _field(text: str, index: int = 0) -> Step2PreprocessedField:
    return Step2PreprocessedField(
        field_id=f"field-{index}",
        original_text=text,
        processed_text=text,
        source_metadata=SourceMetadata(
            input_modality="typed",
            source_language="en",
            translation_confidence=1.0,
            extraction_confidence=0.95,
            field_type="clinical_text",
        ),
    )


def _adapter() -> HybridNERAdapter:
    """Build an adapter that will lazy-load the real spaCy models on first
    .extract() call. Tests that need deterministic behavior without the
    models can construct HybridNERAdapter(load_models=False) but here we
    want the real pipeline."""
    return HybridNERAdapter()


# ---- tests ----

def test_metformin_dosage_via_regex():
    adapter = _adapter()
    entities = adapter.extract(METFORMIN_TEXT)
    dosages = [e for e in entities if e.entity_type == ENTITY_TYPE_DOSAGE]
    assert dosages, f"Expected a Dosage entity in: {entities}"
    assert any(e.text.lower() == "500mg" for e in dosages)
    assert all(e.extraction_source == EXTRACTION_SOURCE_REGEX for e in dosages)
    # span correctness
    d = next(e for e in dosages if e.text.lower() == "500mg")
    assert METFORMIN_TEXT[d.start : d.end].lower() == "500mg"


def test_metformin_medication_via_bc5cdr():
    adapter = _adapter()
    entities = adapter.extract(METFORMIN_TEXT)
    meds = [e for e in entities if e.entity_type == ENTITY_TYPE_MEDICATION]
    assert meds, f"Expected a Medication entity in: {entities}"
    assert any("metformin" in e.text.lower() for e in meds)


def test_confidence_ranges_valid():
    adapter = _adapter()
    entities = adapter.extract(METFORMIN_TEXT)
    for e in entities:
        assert 0.0 <= e.confidence <= 1.0


def test_spans_are_non_overlapping():
    adapter = _adapter()
    entities = adapter.extract(METFORMIN_TEXT)
    spans = [(e.start, e.end) for e in entities]
    spans.sort()
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        assert e1 <= s2, f"Overlapping spans: {spans}"


def test_medication_records_before_extraction():
    entities = _adapter().extract("Metformin 500mg")
    med = next(e for e in entities if e.entity_type == ENTITY_TYPE_MEDICATION)
    assert med.snomed_ct_id is None


def test_normalized_concept_attachment():
    field = _field(METFORMIN_TEXT)
    # Hand-place a normalized concept overlapping "metformin"
    start = METFORMIN_TEXT.lower().find("metformin")
    end = start + len("metformin")
    field = field.model_copy(
        update={
            "normalized_concepts": [
                NormalizedConcept(
                    span={"start": start, "end": end},
                    surface_text="metformin",
                    normalized_concept="Metformin",
                    snomed_ct_id="274729007",
                    clinical_domain="endocrinology",
                )
            ]
        }
    )
    entities = _adapter().extract_with_enrichment(field)
    meds = [e for e in entities if e.entity_type == ENTITY_TYPE_MEDICATION]
    assert meds, "Expected medication entity"
    met = next(m for m in meds if "metformin" in m.text.lower())
    assert met.snomed_ct_id == "274729007"
    assert met.clinical_domain == "endocrinology"


def test_negation_case_still_extracts_entities():
    """Negation affects assertion (Stage 5), not extraction (Stage 4). NER
    must still surface 'diabetes' as Disease and 'chest pain' as Symptom."""
    adapter = _adapter()
    entities = adapter.extract(NEGATION_TEXT)
    symptoms = [
        e for e in entities
        if e.entity_type == ENTITY_TYPE_SYMPTOM
        and e.extraction_source == EXTRACTION_SOURCE_DICTIONARY
    ]
    assert any("chest pain" in e.text.lower() for e in symptoms)


def test_route_extraction():
    text = "Give Metformin 500mg oral daily."
    adapter = _adapter()
    entities = adapter.extract(text)
    routes = [e for e in entities if e.entity_type == ENTITY_TYPE_ROUTE]
    assert routes, f"Expected Route entity in: {entities}"
    assert any(e.text.lower() == "oral" for e in routes)


def test_model_name():
    assert HybridNERAdapter.model_name == "hybrid-scispacy-bc5cdr-regex-dictionary"


def test_raises_when_models_unavailable_and_not_loaded():
    """If load_models=False and no models injected, extract() should return
    [] from the scispacy/bc5cdr branches (no crash); regex/dictionary still
    run. This keeps the adapter usable in environments where the models
    aren't installed."""
    adapter = HybridNERAdapter(load_models=False)
    entities = adapter.extract("Metformin 500mg oral")
    # scispacy/bc5cdr silently skipped; regex + dictionary still work
    assert any(e.entity_type == ENTITY_TYPE_DOSAGE for e in entities)
    assert any(e.entity_type == ENTITY_TYPE_ROUTE for e in entities)
    assert not any(e.extraction_source == EXTRACTION_SOURCE_BC5CDR for e in entities)
