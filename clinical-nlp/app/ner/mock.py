import re

from ..terminology import TERMINOLOGY
from .base import EntitySpan


ENTITY_TYPES = {
    "penicillin allergy": "allergy",
    "hypertension": "condition",
    "high blood pressure": "condition",
    "diabetes mellitus": "condition",
    "shortness of breath": "symptom",
    "fever": "symptom",
    "cough": "symptom",
    "chest pain": "symptom",
    "metformin": "medication",
    "insulin": "medication",
}


class MockClinicalNERAdapter:
    """Deterministic development NER with explicit mock provenance."""

    model_name = "mock-ner"

    def extract(self, text: str) -> list[EntitySpan]:
        entities: list[EntitySpan] = []
        occupied: list[tuple[int, int]] = []
        for phrase, *_ in sorted(TERMINOLOGY, key=lambda item: len(item[0]), reverse=True):
            for match in re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.IGNORECASE):
                span = (match.start(), match.end())
                if any(span[0] < end and span[1] > start for start, end in occupied):
                    continue
                occupied.append(span)
                entities.append(
                    EntitySpan(
                        text=match.group(0),
                        start=match.start(),
                        end=match.end(),
                        entity_type=ENTITY_TYPES.get(phrase, "clinical_entity"),
                        confidence=0.91,
                    )
                )

        if not entities and text.strip():
            entities.append(
                EntitySpan(
                    text=text.strip(),
                    start=0,
                    end=len(text.strip()),
                    entity_type="clinical_statement",
                    confidence=0.75,
                )
            )
        return sorted(entities, key=lambda entity: entity.start)
