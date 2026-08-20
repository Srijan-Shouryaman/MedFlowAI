from dataclasses import dataclass
from datetime import date, datetime
import re


@dataclass(frozen=True)
class TemporalResult:
    temporal_context: str
    temporal_date: date | None
    confidence: float


def extract_temporal_context(text: str) -> TemporalResult:
    lowered = text.casefold()
    date_match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", lowered)
    if date_match:
        try:
            extracted_date = date(
                int(date_match.group(1)),
                int(date_match.group(2)),
                int(date_match.group(3)),
            )
            return TemporalResult("past", extracted_date, 0.92)
        except ValueError:
            pass

    if re.search(r"\b(?:history of|historical|previously|prior|old)\b", lowered):
        return TemporalResult("historical", None, 0.88)
    if re.search(r"\b(?:resolved|no longer|former)\b", lowered):
        return TemporalResult("past", None, 0.88)
    if re.search(r"\b(?:will|planned|scheduled|future)\b", lowered):
        return TemporalResult("future", None, 0.82)
    if re.search(r"\b(?:today|now|currently|current|for \d+ days?)\b", lowered):
        return TemporalResult("current", None, 0.90)
    return TemporalResult("current", None, 0.75)
