"""Full pipeline integration tests for Step 2 Clinical NLP.

These tests verify that Person A's preprocessing/abbreviations/terminology stages
correctly feed into Person B's NER/contextualization/event_builder/validation stages
as a single end-to-end pipeline.
"""

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
from services.clinical_nlp.app.pipeline import ClinicalNLPPipeline
from services.clinical_nlp.app.service import ClinicalNLPService


def make_step1_output(
    *,
    text: str,
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


class TestMetforminDosageFrequencyRoute:
    """Test Case 1: Metformin 500mg BD (medication + dosage + frequency + route)."""

    def test_pipeline_produces_valid_events(self, mock_adapter_bundle):
        step1 = make_step1_output(text="Patient started on Metformin 500mg BD oral for diabetes mellitus.")
        pipeline = ClinicalNLPPipeline(adapters=mock_adapter_bundle)
        events = pipeline.process(step1)

        assert len(events) > 0, "Pipeline should produce at least one event"
        for event in events:
            assert isinstance(event, ClinicalEvent)
            assert event.validation_status == ClinicalEventValidationStatus.VALID
            assert event.source_document_id == step1.document_id
            assert event.original_text == step1.extracted_fields[0].raw_text
            assert 0.0 <= event.bioclinicalbert_confidence <= 1.0
            assert 0.0 <= event.gemini_contextualization_confidence <= 1.0
            assert event.source_text_span.end > event.source_text_span.start
            assert event.source_text_span.end <= len(event.original_text)

    def test_metformin_entity_type_medication(self, integration_adapter_bundle):
        step1 = make_step1_output(text="Patient started on Metformin 500mg BD oral for diabetes mellitus.")
        pipeline = ClinicalNLPPipeline(adapters=integration_adapter_bundle)
        events = pipeline.process(step1)

        med_events = [e for e in events if "metformin" in e.normalized_concept.lower()]
        assert len(med_events) >= 1, "Should extract Metformin as medication"
        for event in med_events:
            assert event.entity_type in ("Medication", "medication"), f"Expected Medication entity_type, got {event.entity_type}"
            assert event.assertion == "affirmed"
            assert event.clinical_status == "active"

    def test_dosage_entity_extracted(self, integration_adapter_bundle):
        step1 = make_step1_output(text="Patient started on Metformin 500mg BD oral for diabetes mellitus.")
        pipeline = ClinicalNLPPipeline(adapters=integration_adapter_bundle)
        events = pipeline.process(step1)

        dosage_events = [e for e in events if e.entity_type == "Dosage"]
        assert len(dosage_events) >= 1, "Should extract 500mg as Dosage"
        for event in dosage_events:
            assert "500" in event.normalized_concept or "500" in event.processed_text

    def test_route_entity_extracted(self, integration_adapter_bundle):
        step1 = make_step1_output(text="Patient started on Metformin 500mg BD oral for diabetes mellitus.")
        pipeline = ClinicalNLPPipeline(adapters=integration_adapter_bundle)
        events = pipeline.process(step1)

        route_events = [e for e in events if e.entity_type == "Route"]
        assert len(route_events) >= 1, "Should extract 'oral' as Route"
        for event in route_events:
            assert "oral" in event.normalized_concept.lower()

    def test_snomed_ct_id_present_for_known_concepts(self, integration_adapter_bundle):
        step1 = make_step1_output(text="Patient started on Metformin 500mg BD oral for diabetes mellitus.")
        pipeline = ClinicalNLPPipeline(adapters=integration_adapter_bundle)
        events = pipeline.process(step1)

        htn_events = [e for e in events if "diabetes" in e.normalized_concept.lower()]
        for event in htn_events:
            assert event.snomed_ct_id is not None, f"Expected SNOMED CT ID for {event.normalized_concept}"
            assert event.clinical_domain == "endocrinology"


class TestNegationCase:
    """Test Case 2: 'No history of diabetes' (negation case)."""

    def test_pipeline_produces_valid_events(self, integration_adapter_bundle):
        step1 = make_step1_output(text="Patient has no history of diabetes and denies chest pain.")
        pipeline = ClinicalNLPPipeline(adapters=integration_adapter_bundle)
        events = pipeline.process(step1)

        assert len(events) > 0, "Pipeline should produce at least one event"
        for event in events:
            assert isinstance(event, ClinicalEvent)
            assert event.validation_status == ClinicalEventValidationStatus.VALID

    def test_negated_assertion_for_diabetes(self, integration_adapter_bundle):
        step1 = make_step1_output(text="Patient has no history of diabetes and denies chest pain.")
        pipeline = ClinicalNLPPipeline(adapters=integration_adapter_bundle)
        events = pipeline.process(step1)

        diabetes_events = [e for e in events if "diabetes" in e.normalized_concept.lower()]
        assert len(diabetes_events) >= 1, "Should extract diabetes entity"
        for event in diabetes_events:
            assert event.assertion == "negated", f"Expected negated assertion, got {event.assertion}"
            assert event.clinical_status == "inactive"

    def test_negated_assertion_for_chest_pain(self, integration_adapter_bundle):
        step1 = make_step1_output(text="Patient has no history of diabetes and denies chest pain.")
        pipeline = ClinicalNLPPipeline(adapters=integration_adapter_bundle)
        events = pipeline.process(step1)

        chest_pain_events = [e for e in events if "chest pain" in e.normalized_concept.lower()]
        assert len(chest_pain_events) >= 1, "Should extract chest pain entity"
        for event in chest_pain_events:
            assert event.assertion == "negated", f"Expected negated assertion, got {event.assertion}"
            assert event.clinical_status == "inactive"

    def test_temporal_context_historical(self, integration_adapter_bundle):
        step1 = make_step1_output(text="Patient has no history of diabetes and denies chest pain.")
        pipeline = ClinicalNLPPipeline(adapters=integration_adapter_bundle)
        events = pipeline.process(step1)

        diabetes_events = [e for e in events if "diabetes" in e.normalized_concept.lower()]
        for event in diabetes_events:
            assert event.temporal_context == "historical", f"Expected historical temporal_context, got {event.temporal_context}"


class TestEdgeCases:
    """Edge cases to verify graceful degradation."""

    def test_empty_text_field(self):
        """Empty text should fail at schema validation (min_length=1 on ExtractedField.raw_text)."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            make_step1_output(text="")

    def test_unknown_entity_type_fallback(self, integration_adapter_bundle):
        """Text that produces 'clinical_statement' entity type used to trigger NameError bug.
        Now fixed - should process without error and use field-level terminology."""
        step1 = make_step1_output(text="Some completely unknown medical text xyzabc")
        pipeline = ClinicalNLPPipeline(adapters=integration_adapter_bundle)

        # Should not raise NameError; should process and produce valid events
        events = pipeline.process(step1)
        assert len(events) > 0
        for event in events:
            assert event.validation_status == ClinicalEventValidationStatus.VALID

    def test_low_confidence_field_flagged(self, integration_adapter_bundle):
        """Fields with low extraction confidence should still process but may have lower confidence."""
        step1 = make_step1_output(
            text="Patient has hypertension",
        )
        # Modify confidence to be low
        step1.extracted_fields[0].extraction_confidence = 0.3
        step1.extracted_fields[0].confidence_tier = ConfidenceTier.AUTO_PASS

        pipeline = ClinicalNLPPipeline(adapters=integration_adapter_bundle)
        events = pipeline.process(step1)

        assert len(events) > 0
        for event in events:
            assert event.validation_status == ClinicalEventValidationStatus.VALID

    def test_entity_type_outside_expected_categories(self, integration_adapter_bundle):
        """Entity types not in the 7 expected categories should still produce valid events."""
        step1 = make_step1_output(text="Patient has hypertension and cough")
        pipeline = ClinicalNLPPipeline(adapters=integration_adapter_bundle)
        events = pipeline.process(step1)

        # Should produce events for hypertension (condition/Disease) and cough (Symptom)
        assert len(events) >= 2
        entity_types = {e.entity_type for e in events}
        # Check that we get at least some known types
        assert any(t in entity_types for t in ["Disease", "condition", "Symptom", "Medication", "Dosage", "Route", "Allergy", "Procedure", "LaboratoryFinding"])

def test_multiple_fields_in_step1_output(integration_adapter_bundle):
        """Step1Output with multiple extracted fields should process all."""
        patient_id = uuid4()
        encounter_id = uuid4()
        document_id = uuid4()
        step1 = Step1Output(
            document_id=document_id,
            patient_id=patient_id,
            encounter_id=encounter_id,
            input_modality=InputModality.TYPED,
            source_language="en",
            extracted_fields=[
                ExtractedField(
                    raw_text="Patient has hypertension",
                    standardized_text="Patient has hypertension",
                    extraction_confidence=0.95,
                    confidence_tier=ConfidenceTier.AUTO_PASS,
                ),
                ExtractedField(
                    raw_text="Patient takes Metformin 500mg BD",
                    standardized_text="Patient takes Metformin 500mg BD",
                    extraction_confidence=0.95,
                    confidence_tier=ConfidenceTier.AUTO_PASS,
                ),
            ],
            translation_confidence=1.0,
            processing_status=ProcessingStatus.COMPLETE,
            audit_log_id=uuid4(),
            verification_state=VerificationState.NOT_REQUIRED,
        )

        pipeline = ClinicalNLPPipeline(adapters=integration_adapter_bundle)
        events = pipeline.process(step1)

        assert len(events) >= 2
        for event in events:
            assert event.validation_status == ClinicalEventValidationStatus.VALID
            assert event.source_document_id == document_id


class TestAPILayerIntegration:
    """Test the FastAPI endpoints end-to-end."""

    def test_post_and_get_process_endpoint(self, integration_adapter_bundle):
        step1 = make_step1_output(text="Patient started on Metformin 500mg BD oral for diabetes mellitus.")
        service = ClinicalNLPService(adapters=integration_adapter_bundle)

        from fastapi.testclient import TestClient
        from services.clinical_nlp.app.main import create_app

        client = TestClient(create_app(service))

        response = client.post(
            "/api/v1/step2/process",
            json={
                "document_id": str(step1.document_id),
                "patient_id": str(step1.patient_id),
                "encounter_id": str(step1.encounter_id),
                "step1_output": step1.model_dump(mode="json"),
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["source_document_id"] == str(step1.document_id)
        assert len(body["clinical_events"]) > 0

        event = body["clinical_events"][0]
        assert event["validation_status"] == "valid"
        assert "normalized_concept" in event
        assert "entity_type" in event
        assert "assertion" in event
        assert "clinical_status" in event
        assert "snomed_ct_id" in event
        assert "clinical_domain" in event

        # GET the same document
        get_response = client.get(f"/api/v1/step2/process/{step1.document_id}")
        assert get_response.status_code == 200
        assert get_response.json() == body

    def test_mismatched_ids_rejected(self, integration_adapter_bundle):
        step1 = make_step1_output(text="Patient has hypertension")
        service = ClinicalNLPService(adapters=integration_adapter_bundle)

        from fastapi.testclient import TestClient
        from services.clinical_nlp.app.main import create_app

        client = TestClient(create_app(service))

        response = client.post(
            "/api/v1/step2/process",
            json={
                "document_id": str(uuid4()),
                "patient_id": str(step1.patient_id),
                "encounter_id": str(step1.encounter_id),
                "step1_output": step1.model_dump(mode="json"),
            },
        )

        assert response.status_code == 422

    def test_get_missing_document_returns_404(self, integration_adapter_bundle):
        service = ClinicalNLPService(adapters=integration_adapter_bundle)

        from fastapi.testclient import TestClient
        from services.clinical_nlp.app.main import create_app

        client = TestClient(create_app(service))

        response = client.get(f"/api/v1/step2/process/{uuid4()}")
        assert response.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])