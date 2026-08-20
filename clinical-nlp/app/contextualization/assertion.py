from dataclasses import dataclass
import re


@dataclass(frozen=True)
class AssertionResult:
    assertion: str
    clinical_status: str
    confidence: float


def detect_assertion(text: str, entity_text: str) -> AssertionResult:
    lowered = text.casefold()
    entity_position = lowered.find(entity_text.casefold())
    context = lowered[max(0, entity_position - 40) : entity_position] if entity_position >= 0 else lowered

    if re.search(r"\b(?:no|not|denies|denied|without|negative for)\b", context):
        return AssertionResult("negated", "inactive", 0.90)
    if re.search(r"\b(?:possible|possibly|疑似|rule out|suspected|suspect)\b", context):
        return AssertionResult("possible", "unknown", 0.78)
    if re.search(r"\b(?:if|when|should|may develop)\b", context):
        return AssertionResult("conditional", "unknown", 0.76)
    return AssertionResult("affirmed", "active", 0.88)
