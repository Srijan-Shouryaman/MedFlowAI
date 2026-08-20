from uuid import uuid4

import pytest

from contracts.schemas import (
    ClinicalEvent,
    ClinicalEventValidationStatus,
    ConfidenceTier,
    ExtractedField,
    InputModality,
    ProcessingStatus,
    SourceTextSpan,
    Step1Output,
    VerificationState,
)
from services.clinical_nlp.app.abbreviations import (
    DetectedAbbreviation,
    ExpandedField,
    detect_abbreviations,
    expand_abbreviations,
    expand_field,
)
from services.clinical_nlp.app.contextualization import (
    detect_assertion,
    extract_temporal_context,
)
from services.clinical_nlp.app.ner import (
    HybridNERAdapter,
    NLPModelUnavailableError,
)
from services.clinical_nlp.app.pipeline import ClinicalNLPPipeline
from services.clinical_nlp.app.preprocess import (
    PreprocessedField,
    normalize_text,
    preprocess_field,
    preprocess_step1_output,
)
from services.clinical_nlp.app.service import (
    ClinicalNLPService,
    Step1InputError,
)
from services.clinical_nlp.app.terminology import (
    TerminologyMatch,
    normalize_field,
    normalize_terminology,
)
from services.clinical_nlp.app.validation import (
    ClinicalEventValidationError,
    validate_event,
    validate_events,
)
# Use pytest fixture: mock_adapter_bundle


def make_step1_output(
    *,
    text: str = "Patient has HTN and cough",
    status: ProcessingStatus = ProcessingStatus.COMPLETE,
    requires_review: bool = False,
) -> Step1Output:
    patient_id = uuid4()
    encounter_id = uuid4()
    return Step1Output(
        document_id=uuid4(),
        patient_id=patient_id,
        encounter_id=encounter_id,
        input_modality=InputModality.TYPED,
        source_language="en",
        extracted_fields=[
            ExtractedField(
                raw_text=text,
                standardized_text=text,
                extraction_confidence=0.96,
                is_high_risk_field=False,
                confidence_tier=(
                    ConfidenceTier.HUMAN_VERIFICATION_REQUIRED
                    if requires_review
                    else ConfidenceTier.AUTO_PASS
                ),
                requires_doctor_review_before_memory_write=requires_review,
            )
        ],
        translation_confidence=1.0,
        original_language_text=None,
        ocr_engine_used=None,
        vlm_model_used=None,
        processing_status=status,
        audit_log_id=uuid4(),
        verification_state=(
            VerificationState.PENDING
            if requires_review
            else VerificationState.NOT_REQUIRED
        ),
    )


# ==========================================
# 2.1 Preprocessing Tests
# ==========================================

def test_preprocessing_normalizes_unicode_and_whitespace():
    assert normalize_text("  Patient\n\thas  HTN  ") == "Patient has HTN"


def test_preprocessing_unicode_nfc_and_smart_quotes():
    # Smart quotes and dashes normalized
    input_text = "‘Patient’ has “high-risk” HTN—severe"
    assert normalize_text(input_text) == "'Patient' has \"high-risk\" HTN-severe"


def test_preprocessing_cleans_zero_width_and_ocr_artifacts():
    # Zero-width spaces, soft hyphens, BOMs, trailing OCR scan lines
    input_text = "Patient\u200b has \u00adHTN \ufeffand | fever •"
    assert normalize_text(input_text) == "Patient has HTN and fever"


def test_preprocessing_preserves_medical_abbreviations_and_punctuation():
    # Preserves casing of medical acronyms, decimal numbers, and clinical slashes
    input_text = "Patient takes Metformin 0.5mg BD and c/o SOB."
    assert normalize_text(input_text) == "Patient takes Metformin 0.5mg BD and c/o SOB."


def test_preprocessing_empty_and_multiline_input():
    assert normalize_text("") == ""
    assert normalize_text("   \n\t\r  ") == ""
    multiline = """
    Line 1: Patient has HTN.
    Line 2: Pt has DM.
    """
    assert normalize_text(multiline) == "Line 1: Patient has HTN. Line 2: Pt has DM."


def test_preprocess_field_structure():
    field = ExtractedField(
        raw_text="  Patient with HTN  ",
        standardized_text="  Patient with HTN  ",
        extraction_confidence=0.95,
        confidence_tier=ConfidenceTier.AUTO_PASS,
    )
    preprocessed = preprocess_field(field)
    assert isinstance(preprocessed, PreprocessedField)
    assert preprocessed.original_text == "Patient with HTN"
    assert preprocessed.processed_text == "Patient with HTN"
    assert preprocessed.source_text_span.start == 0
    assert preprocessed.source_text_span.end == len("Patient with HTN")


# ==========================================
# 2.2 Abbreviation Detection Tests
# ==========================================

def test_abbreviation_detection_known_terms():
    text = "Pt with HTN, DM, SOB, BP 120/80, taking Metformin 500mg BD. Tx planned."
    detections = detect_abbreviations(text)

    surfaces = [d.surface_text for d in detections]
    assert "Pt" in surfaces
    assert "HTN" in surfaces
    assert "DM" in surfaces
    assert "SOB" in surfaces
    assert "BP" in surfaces
    assert "BD" in surfaces
    assert "Tx" in surfaces

    # Check spans and ambiguity
    for d in detections:
        assert text[d.start : d.end] == d.surface_text
        assert d.is_known is True

    pt_det = next(d for d in detections if d.surface_text == "Pt")
    assert pt_det.is_ambiguous is True
    assert pt_det.expansion is None
    assert pt_det.candidate_expansions == ("patient", "physical therapy", "prothrombin time")

    tx_det = next(d for d in detections if d.surface_text == "Tx")
    assert tx_det.is_ambiguous is True
    assert tx_det.expansion is None
    assert tx_det.candidate_expansions == ("treatment", "transplant")

    htn_det = next(d for d in detections if d.surface_text == "HTN")
    assert htn_det.is_ambiguous is False
    assert htn_det.expansion == "hypertension"


def test_abbreviation_detection_punctuation_and_slashes():
    text = "Patient (c/o) chest pain, Hx of HTN, Dx of DM."
    detections = detect_abbreviations(text)

    surfaces = [d.surface_text for d in detections]
    assert "c/o" in surfaces
    assert "Hx" in surfaces
    assert "HTN" in surfaces
    assert "Dx" in surfaces
    assert "DM" in surfaces


def test_abbreviation_detection_case_insensitivity():
    text = "htn HTN Htn Hx hx"
    detections = detect_abbreviations(text)
    assert len(detections) == 5
    assert all(d.is_known for d in detections)


def test_abbreviation_detection_unknown_and_empty():
    assert detect_abbreviations("") == []
    assert detect_abbreviations("No abbreviations here") == []


# ==========================================
# 2.3 Abbreviation Expansion Tests
# ==========================================

def test_abbreviation_expansion():
    # Ambiguous abbreviation "Pt" remains unchanged, while unambiguous "HTN", "DM", "SOB" expand
    assert expand_abbreviations("Pt with HTN, DM and SOB") == (
        "Pt with hypertension, diabetes mellitus and shortness of breath"
    )


def test_abbreviation_expansion_ambiguous_remain_unchanged():
    # Ambiguous abbreviations must not be automatically expanded
    assert expand_abbreviations("Pt with HTN") == "Pt with hypertension"
    assert expand_abbreviations("Tx planned") == "Tx planned"


def test_abbreviation_expansion_metformin_500mg_bd():
    assert expand_abbreviations("Metformin 500mg BD") == "Metformin 500mg twice daily"
    assert expand_abbreviations("Metformin 500mg bid") == "Metformin 500mg twice daily"


def test_abbreviation_expansion_repeated_and_multiple():
    text = "HTN and BP check. History of HTN."
    assert expand_abbreviations(text) == "hypertension and blood pressure check. History of hypertension."


def test_expand_field_records_replacements():
    field = ExtractedField(
        raw_text="Metformin 500mg BD for HTN",
        standardized_text="Metformin 500mg BD for HTN",
        extraction_confidence=0.98,
        confidence_tier=ConfidenceTier.AUTO_PASS,
    )
    preprocessed = preprocess_field(field)
    expanded = expand_field(preprocessed)

    assert isinstance(expanded, ExpandedField)
    assert expanded.processed_text == "Metformin 500mg twice daily for hypertension"
    assert ("BD", "twice daily") in expanded.replacements
    assert ("HTN", "hypertension") in expanded.replacements
    assert expanded.source.original_text == "Metformin 500mg BD for HTN"


# ==========================================
# 2.4 SNOMED Normalization Tests
# ==========================================

def test_terminology_normalization():
    match = normalize_terminology("hypertension")

    assert match.concept == "Hypertension"
    assert match.snomed_ct_id == "38341003"
    assert match.clinical_domain == "cardiology"


def test_terminology_normalization_synonyms():
    # "high blood pressure" -> "Hypertension"
    match = normalize_terminology("high blood pressure")
    assert match.concept == "Hypertension"
    assert match.snomed_ct_id == "38341003"
    assert match.clinical_domain == "cardiology"

    # "shortness of breath" -> "Dyspnea"
    match_sob = normalize_terminology("shortness of breath")
    assert match_sob.concept == "Dyspnea"
    assert match_sob.snomed_ct_id == "267036007"
    assert match_sob.clinical_domain == "respiratory"

    # "penicillin allergy" -> "Allergy to penicillin"
    match_allergy = normalize_terminology("penicillin allergy")
    assert match_allergy.concept == "Allergy to penicillin"
    assert match_allergy.snomed_ct_id == "91936005"
    assert match_allergy.clinical_domain == "allergy"


def test_terminology_normalization_approved_concepts():
    # Diabetes mellitus
    dm = normalize_terminology("diabetes mellitus")
    assert dm.concept == "Diabetes mellitus"
    assert dm.snomed_ct_id == "73211009"
    assert dm.clinical_domain == "endocrinology"

    # Fever
    fever = normalize_terminology("fever")
    assert fever.concept == "Fever"
    assert fever.snomed_ct_id == "386661006"
    assert fever.clinical_domain == "general medicine"

    # Cough
    cough = normalize_terminology("cough")
    assert cough.concept == "Cough"
    assert cough.snomed_ct_id == "49727002"
    assert cough.clinical_domain == "respiratory"

    # Chest pain
    cp = normalize_terminology("chest pain")
    assert cp.concept == "Chest pain"
    assert cp.snomed_ct_id == "29857009"
    assert cp.clinical_domain == "cardiology"

    # Metformin and Insulin (IDs remain null per specification)
    metformin = normalize_terminology("metformin")
    assert metformin.concept == "Metformin"
    assert metformin.snomed_ct_id is None
    assert metformin.clinical_domain == "medication"

    insulin = normalize_terminology("insulin")
    assert insulin.concept == "Insulin"
    assert insulin.snomed_ct_id is None
    assert insulin.clinical_domain == "medication"


def test_terminology_normalization_unknown_term_fallback():
    unknown = normalize_terminology("atypical fatigue")
    assert unknown.concept == "Atypical fatigue"
    assert unknown.snomed_ct_id is None
    assert unknown.clinical_domain == "general medicine"


def test_normalize_field_integration():
    field = ExtractedField(
        raw_text="Patient with high blood pressure",
        standardized_text="Patient with high blood pressure",
        extraction_confidence=0.95,
        confidence_tier=ConfidenceTier.AUTO_PASS,
    )
    expanded = expand_field(preprocess_field(field))
    match = normalize_field(expanded)
    assert match.concept == "Hypertension"
    assert match.snomed_ct_id == "38341003"


# ==========================================
# NER, Contextualization & Validation Tests (Yatharth's modules integration)
# ==========================================

def test_ner_extracts_multiple_entities():
    # HybridNERAdapter extracts: "Patient" (Disease, scispacy), "hypertension" (Disease, bc5cdr), "cough" (Symptom, dictionary)
    entities = HybridNERAdapter().extract("Patient has hypertension and cough")

    entity_texts = [entity.text.casefold() for entity in entities]
    assert "hypertension" in entity_texts
    assert "cough" in entity_texts
    assert all(entity.confidence > 0 for entity in entities)


def test_assertion_detection():
    assert detect_assertion("Patient denies chest pain", "chest pain").assertion == "negated"
    assert detect_assertion("Patient has chest pain", "chest pain").assertion == "affirmed"


def test_temporal_extraction():
    current = extract_temporal_context("fever for 3 days")
    historical = extract_temporal_context("history of hypertension")

    assert current.temporal_context == "current"
    assert historical.temporal_context == "historical"


def test_pipeline_builds_provenance_preserving_events(mock_adapter_bundle):
    step1 = make_step1_output()
    events = ClinicalNLPPipeline(adapters=mock_adapter_bundle).process(step1)

    # With load_models=False, only dictionary extraction works: "cough" -> Symptom
    # HTN is expanded to "hypertension" by abbreviation expander but not extracted by NER without models
    assert len(events) == 1
    cough_event = events[0]
    assert cough_event.normalized_concept == "Cough"
    assert cough_event.entity_type == "Symptom"
    assert cough_event.source_document_id == step1.document_id
    assert cough_event.original_text == "Patient has HTN and cough"
    assert cough_event.processed_text == "Patient has hypertension and cough"
    assert cough_event.snomed_ct_id == "49727002"
    assert cough_event.input_modality == InputModality.TYPED
    assert cough_event.source_language == "en"
    assert cough_event.translation_confidence == 1.0
    assert cough_event.validation_status == ClinicalEventValidationStatus.VALID
    assert cough_event.source_text_span.end > cough_event.source_text_span.start

    # Verify all events have valid provenance
    for event in events:
        assert event.validation_status == ClinicalEventValidationStatus.VALID
        assert event.source_document_id == step1.document_id
        assert event.source_text_span.end > event.source_text_span.start


def test_event_contract_round_trip(mock_adapter_bundle):
    step1 = make_step1_output(text="Patient has fever")
    event = ClinicalNLPPipeline(adapters=mock_adapter_bundle).process(step1)[0]

    assert ClinicalEvent.model_validate(event.model_dump()) == event


def test_invalid_event_does_not_validate(mock_adapter_bundle):
    step1 = make_step1_output(text="Patient has fever")
    event = ClinicalNLPPipeline(adapters=mock_adapter_bundle).process(step1)[0].model_copy(
        update={"source_text_span": SourceTextSpan(start=0, end=999)}
    )

    result = validate_event(event, expected_source_document_id=step1.document_id)

    assert result.valid is False
    assert any(issue.field == "source_text_span" for issue in result.issues)
    with pytest.raises(ClinicalEventValidationError):
        validate_events([event], expected_source_document_id=step1.document_id)


def test_service_rejects_unverified_step1_output(mock_adapter_bundle):
    step1 = make_step1_output(
        status=ProcessingStatus.PENDING_HUMAN_VERIFICATION,
        requires_review=True,
    )
    service = ClinicalNLPService(adapters=mock_adapter_bundle)

    with pytest.raises(Step1InputError):
        service.process(
            document_id=step1.document_id,
            patient_id=step1.patient_id,
            encounter_id=step1.encounter_id,
            step1_output=step1,
        )


def test_hybrid_ner_adapter_creation():
    adapter = HybridNERAdapter(load_models=False)
    assert adapter.model_name == "hybrid-scispacy-bc5cdr-regex-dictionary"
    entities = adapter.extract("Patient has 500mg aspirin oral")
    assert len(entities) > 0


def test_metformin_500mg_bd_case(mock_adapter_bundle):
    step1 = make_step1_output(text="Patient started on Metformin 500mg BD oral for diabetes mellitus.")
    pipeline = ClinicalNLPPipeline(adapters=mock_adapter_bundle)
    events = pipeline.process(step1)

    assert len(events) > 0
    for event in events:
        assert isinstance(event, ClinicalEvent)
        assert event.validation_status == ClinicalEventValidationStatus.VALID
        assert event.source_document_id == step1.document_id


def test_negation_case_no_history_of_diabetes(mock_adapter_bundle):
    step1 = make_step1_output(text="Patient has no history of diabetes and denies chest pain.")
    pipeline = ClinicalNLPPipeline(adapters=mock_adapter_bundle)
    events = pipeline.process(step1)

    assert len(events) > 0
    negated_events = [e for e in events if e.assertion == "negated"]
    assert len(negated_events) >= 1
    for event in events:
        assert isinstance(event, ClinicalEvent)
        assert event.validation_status == ClinicalEventValidationStatus.VALID

