from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from .schemas import ClinicalEventBatch, Step2ProcessRequest
from .service import (
    ClinicalEventBatchNotFoundError,
    ClinicalNLPProcessingError,
    ClinicalNLPService,
    Step1InputError,
)


router = APIRouter(
    prefix="/step2",
    tags=["Step 2 - Clinical NLP"],
)


def get_nlp_service(request: Request) -> ClinicalNLPService:
    return request.app.state.clinical_nlp_service


@router.post("/process", response_model=ClinicalEventBatch)
def process_step1_output(
    request: Step2ProcessRequest,
    service: ClinicalNLPService = Depends(get_nlp_service),
) -> ClinicalEventBatch:
    try:
        return service.process(
            document_id=request.document_id,
            patient_id=request.patient_id,
            encounter_id=request.encounter_id,
            step1_output=request.step1_output,
        )
    except Step1InputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ClinicalNLPProcessingError as exc:
        raise HTTPException(
            status_code=503,
            detail="Clinical NLP processing failed.",
        ) from exc


@router.get("/process/{document_id}", response_model=ClinicalEventBatch)
def get_processed_events(
    document_id: UUID,
    service: ClinicalNLPService = Depends(get_nlp_service),
) -> ClinicalEventBatch:
    try:
        return service.get(document_id)
    except ClinicalEventBatchNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Clinical events have not been processed for this document.",
        ) from exc
