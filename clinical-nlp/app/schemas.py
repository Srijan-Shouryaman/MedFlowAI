from uuid import UUID

from pydantic import BaseModel, ConfigDict

from contracts.schemas import ClinicalEventBatch, Step1Output


class Step2ProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    patient_id: UUID
    encounter_id: UUID
    step1_output: Step1Output


__all__ = ["ClinicalEventBatch", "Step1Output", "Step2ProcessRequest"]
