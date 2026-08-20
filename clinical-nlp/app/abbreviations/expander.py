from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from ..preprocess import PreprocessedField
from ..pipeline_types import AbbreviationSpan


@dataclass(frozen=True)
class DetectedAbbreviation:
    surface_text: str
    start: int
    end: int
    is_known: bool
    is_ambiguous: bool
    expansion: str | None
    candidate_expansions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExpandedField:
    source: PreprocessedField
    processed_text: str
    replacements: tuple[tuple[str, str], ...]
    abbreviation_spans: tuple[AbbreviationSpan, ...]


DEFAULT_ABBREVIATIONS: dict[str, dict[str, Any]] = {
    "htn": {"expansion": "hypertension", "is_ambiguous": False, "category": "condition"},
    "dm": {"expansion": "diabetes mellitus", "is_ambiguous": False, "category": "condition"},
    "sob": {"expansion": "shortness of breath", "is_ambiguous": False, "category": "symptom"},
    "bp": {"expansion": "blood pressure", "is_ambiguous": False, "category": "vital"},
    "hr": {"expansion": "heart rate", "is_ambiguous": False, "category": "vital"},
    "rr": {"expansion": "respiratory rate", "is_ambiguous": False, "category": "vital"},
    "pt": {
        "expansion": "patient",
        "is_ambiguous": True,
        "candidates": ["patient", "physical therapy", "prothrombin time"],
        "category": "general",
    },
    "c/o": {"expansion": "complains of", "is_ambiguous": False, "category": "general"},
    "hx": {"expansion": "history", "is_ambiguous": False, "category": "general"},
    "dx": {"expansion": "diagnosis", "is_ambiguous": False, "category": "general"},
    "tx": {
        "expansion": "treatment",
        "is_ambiguous": True,
        "candidates": ["treatment", "transplant"],
        "category": "general",
    },
    "meds": {"expansion": "medications", "is_ambiguous": False, "category": "general"},
    "bd": {"expansion": "twice daily", "is_ambiguous": False, "category": "dosage"},
    "bid": {"expansion": "twice daily", "is_ambiguous": False, "category": "dosage"},
    "tid": {"expansion": "three times daily", "is_ambiguous": False, "category": "dosage"},
    "qid": {"expansion": "four times daily", "is_ambiguous": False, "category": "dosage"},
    "od": {"expansion": "once daily", "is_ambiguous": False, "category": "dosage"},
    "po": {"expansion": "orally", "is_ambiguous": False, "category": "dosage"},
    "prn": {"expansion": "as needed", "is_ambiguous": False, "category": "dosage"},
}


def _load_abbreviations_registry() -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {k: dict(v) for k, v in DEFAULT_ABBREVIATIONS.items()}
    seed_path = Path(__file__).resolve().parents[4] / "database" / "seeds" / "abbreviations.json"
    if seed_path.is_file():
        try:
            with open(seed_path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    for key, entry in data.items():
                        if isinstance(entry, dict):
                            registry[key.casefold()] = entry
        except Exception:
            pass
    return registry


ABBREVIATIONS_REGISTRY: dict[str, dict[str, Any]] = _load_abbreviations_registry()

# Flat dictionary maintained for backwards compatibility with unambiguous expansions
ABBREVIATIONS: dict[str, str] = {
    key: str(info.get("expansion", ""))
    for key, info in ABBREVIATIONS_REGISTRY.items()
    if info.get("expansion") and not info.get("is_ambiguous", False)
}


def _boundary_pattern(term: str) -> str:
    """Build a regex pattern that safely matches word-based and punctuation/slash-based terms."""
    escaped = re.escape(term)
    return rf"(?<![\w/]){escaped}(?![\w/])"


def detect_abbreviations(text: str) -> list[DetectedAbbreviation]:
    """Identify medical abbreviations, their character spans, and ambiguity status."""
    if not text:
        return []

    detected: list[DetectedAbbreviation] = []
    occupied: list[tuple[int, int]] = []

    # Sort registered abbreviations by length descending to match multi-token/longer abbreviations first
    sorted_terms = sorted(
        ABBREVIATIONS_REGISTRY.keys(),
        key=lambda item: len(item),
        reverse=True,
    )

    for term in sorted_terms:
        info = ABBREVIATIONS_REGISTRY[term]
        pattern = _boundary_pattern(term)
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            span = (match.start(), match.end())
            if any(span[0] < end and span[1] > start for start, end in occupied):
                continue
            occupied.append(span)
            is_ambiguous = bool(info.get("is_ambiguous", False))
            expansion = str(info["expansion"]) if ("expansion" in info and not is_ambiguous) else None
            candidates = tuple(info.get("candidates", ()))
            detected.append(
                DetectedAbbreviation(
                    surface_text=match.group(0),
                    start=match.start(),
                    end=match.end(),
                    is_known=True,
                    is_ambiguous=is_ambiguous,
                    expansion=expansion,
                    candidate_expansions=candidates,
                )
            )

    return sorted(detected, key=lambda item: item.start)


def expand_abbreviations(text: str) -> str:
    """Deterministically expand unambiguous abbreviations while preserving ambiguous ones."""
    if not text:
        return ""

    detections = detect_abbreviations(text)
    if not detections:
        return text

    # Replace from right to left to keep character start indices stable during replacement
    expanded = text
    for item in reversed(detections):
        if item.expansion and not item.is_ambiguous:
            expanded = expanded[: item.start] + item.expansion + expanded[item.end :]

    return expanded


def _to_abbreviation_span(item: DetectedAbbreviation) -> AbbreviationSpan:
    """Convert internal DetectedAbbreviation to contract AbbreviationSpan."""
    status = "resolved"
    if item.is_ambiguous:
        status = "ambiguous"
    elif item.expansion is None:
        status = "unknown"
    return AbbreviationSpan(
        span={"start": item.start, "end": item.end},
        surface_text=item.surface_text,
        status=status,
        expansion=item.expansion,
        candidates=list(item.candidate_expansions),
        resolution_confidence=1.0 if not item.is_ambiguous else 0.5,
    )


def expand_field(field: PreprocessedField) -> ExpandedField:
    """Expand abbreviations in a preprocessed field and track replacement tuples."""
    detections = detect_abbreviations(field.processed_text)
    expanded = expand_abbreviations(field.processed_text)

    replacements: list[tuple[str, str]] = []
    abbreviation_spans: list[AbbreviationSpan] = []
    for item in detections:
        abbreviation_spans.append(_to_abbreviation_span(item))
        if item.expansion and not item.is_ambiguous:
            replacements.append((item.surface_text, item.expansion))

    return ExpandedField(
        source=field,
        processed_text=expanded,
        replacements=tuple(replacements),
        abbreviation_spans=tuple(abbreviation_spans),
    )
