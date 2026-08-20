from uuid import uuid4

from fastapi.testclient import TestClient

from contracts.schemas import (
    ConfidenceTier,
    ExtractedField,
    InputModality,
    ProcessingStatus,
    Step1Output,
    VerificationState,
)
from services.clinical_nlp.app.main import create_app
from services.clinical_nlp.app.service import ClinicalNLPService


def make_payload():
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
                raw_text="Patient has cough",
                standardized_text="Patient has cough",
                extraction_confidence=0.97,
                confidence_tier=ConfidenceTier.AUTO_PASS,
            )
        ],
        translation_confidence=1.0,
        processing_status=ProcessingStatus.COMPLETE,
        audit_log_id=uuid4(),
        verification_state=VerificationState.NOT_REQUIRED,
    )
    return patient_id, encounter_id, document_id, step1


def make_test_service(mock_adapter_bundle):
    """Create a ClinicalNLPService with mock adapter bundle for testing."""
    return ClinicalNLPService(adapters=mock_adapter_bundle)


def test_process_and_get_api(mock_adapter_bundle):
    client = TestClient(create_app(make_test_service(mock_adapter_bundle)))
    patient_id, encounter_id, document_id, step1 = make_payload()

    response = client.post(
        "/api/v1/step2/process",
        json={
            "document_id": str(document_id),
            "patient_id": str(patient_id),
            "encounter_id": str(encounter_id),
            "step1_output": step1.model_dump(mode="json"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_document_id"] == str(document_id)
    # With load_models=False, only dictionary extraction works: "cough" -> Symptom
    cough_events = [e for e in body["clinical_events"] if e["normalized_concept"] == "Cough"]
    assert len(cough_events) >= 1

    fetched = client.get(f"/api/v1/step2/process/{document_id}")
    assert fetched.status_code == 200
    assert fetched.json() == body


def test_mismatched_step1_ids_are_rejected(mock_adapter_bundle):
    client = TestClient(create_app(make_test_service(mock_adapter_bundle)))
    patient_id, encounter_id, document_id, step1 = make_payload()

    response = client.post(
        "/api/v1/step2/process",
        json={
            "document_id": str(uuid4()),
            "patient_id": str(patient_id),
            "encounter_id": str(encounter_id),
            "step1_output": step1.model_dump(mode="json"),
        },
    )

    assert response.status_code == 422


def test_get_missing_document_returns_404(mock_adapter_bundle):
    client = TestClient(create_app(make_test_service(mock_adapter_bundle)))

    response = client.get(f"/api/v1/step2/process/{uuid4()}")

    assert response.status_code == 404
