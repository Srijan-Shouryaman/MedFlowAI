from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from ..abbreviations import ExpandedField
from ..pipeline_types import NormalizedConcept


@dataclass(frozen=True)
class TerminologyMatch:
    concept: str
    snomed_ct_id: str | None
    clinical_domain: str
    matched_text: str


@dataclass(frozen=True)
class NormalizedConceptsResult:
    """Result of normalizing all concepts in a field's text."""
    matches: list[NormalizedConcept]


DEFAULT_TERMINOLOGY_ENTRIES: list[dict[str, Any]] = [
    {
        "concept": "Allergy to penicillin",
        "snomed_ct_id": "91936005",
        "clinical_domain": "allergy",
        "synonyms": ["penicillin allergy", "allergy to penicillin"],
    },
    {
        "concept": "Hypertension",
        "snomed_ct_id": "38341003",
        "clinical_domain": "cardiology",
        "synonyms": ["hypertension", "high blood pressure"],
    },
    {
        "concept": "Diabetes mellitus",
        "snomed_ct_id": "73211009",
        "clinical_domain": "endocrinology",
        "synonyms": ["diabetes mellitus", "diabetes"],
    },
    {
        "concept": "Dyspnea",
        "snomed_ct_id": "267036007",
        "clinical_domain": "respiratory",
        "synonyms": ["shortness of breath", "dyspnea"],
    },
    {
        "concept": "Fever",
        "snomed_ct_id": "386661006",
        "clinical_domain": "general medicine",
        "synonyms": ["fever"],
    },
    {
        "concept": "Cough",
        "snomed_ct_id": "49727002",
        "clinical_domain": "respiratory",
        "synonyms": ["cough"],
    },
    {
        "concept": "Chest pain",
        "snomed_ct_id": "29857009",
        "clinical_domain": "cardiology",
        "synonyms": ["chest pain"],
    },
    {
        "concept": "Metformin",
        "snomed_ct_id": None,
        "clinical_domain": "medication",
        "synonyms": ["metformin"],
    },
    {
        "concept": "Insulin",
        "snomed_ct_id": None,
        "clinical_domain": "medication",
        "synonyms": ["insulin"],
    },
]


def _load_terminology_tuples() -> tuple[tuple[str, str, str | None, str], ...]:
    entries = DEFAULT_TERMINOLOGY_ENTRIES
    seed_path = Path(__file__).resolve().parents[4] / "database" / "seeds" / "snomed_subset.json"
    if seed_path.is_file():
        try:
            with open(seed_path, encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list) and loaded:
                    entries = loaded
        except Exception:
            pass

    tuples: list[tuple[str, str, str | None, str]] = []
    seen: set[str] = set()

    for item in entries:
        concept = str(item.get("concept", "")).strip()
        code = item.get("snomed_ct_id")
        domain = str(item.get("clinical_domain", "general medicine")).strip()
        synonyms = item.get("synonyms", [])
        if not isinstance(synonyms, list) or not synonyms:
            synonyms = [concept.casefold()]

        for syn in synonyms:
            phrase = str(syn).strip().casefold()
            if phrase and phrase not in seen:
                seen.add(phrase)
                tuples.append((phrase, concept, code, domain))

    # Always sort by phrase length descending
    return tuple(sorted(tuples, key=lambda item: len(item[0]), reverse=True))


# Maintained tuple format for full backwards compatibility
TERMINOLOGY: tuple[tuple[str, str, str | None, str], ...] = _load_terminology_tuples()


def normalize_terminology(text: str) -> TerminologyMatch:
    """Normalize clinical text to curated preferred concepts and verified SNOMED CT IDs."""
    if not text:
        return TerminologyMatch(
            concept="",
            snomed_ct_id=None,
            clinical_domain="general medicine",
            matched_text="",
        )

    lowered = text.casefold().strip()

    # 1. Exact match against known synonyms/concepts
    for phrase, concept, code, domain in TERMINOLOGY:
        if lowered == phrase:
            return TerminologyMatch(
                concept=concept,
                snomed_ct_id=code,
                clinical_domain=domain,
                matched_text=phrase,
            )

    # 2. Word boundary substring search
    for phrase, concept, code, domain in TERMINOLOGY:
        if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered):
            return TerminologyMatch(
                concept=concept,
                snomed_ct_id=code,
                clinical_domain=domain,
                matched_text=phrase,
            )

    # 3. Fallback for unmapped terms
    return TerminologyMatch(
        concept=text.strip().capitalize(),
        snomed_ct_id=None,
        clinical_domain="general medicine",
        matched_text=text.strip(),
    )


def normalize_field(field: ExpandedField) -> TerminologyMatch:
    return normalize_terminology(field.processed_text)


def normalize_all_concepts(text: str) -> list[NormalizedConcept]:
    """Find all known concepts in text with their character spans.

    Returns a list of NormalizedConcept objects, each with the span where
    the concept was matched in the input text.
    """
    if not text:
        return []

    lowered = text.casefold()
    matches: list[NormalizedConcept] = []
    seen_spans: set[tuple[int, int]] = set()

    # Sort by phrase length descending to match longer phrases first
    for phrase, concept, code, domain in TERMINOLOGY:
        # Find all non-overlapping occurrences
        for match in re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered, flags=re.IGNORECASE):
            span = (match.start(), match.end())
            # Skip if this span overlaps with an already matched concept
            if any(span[0] < end and span[1] > start for start, end in seen_spans):
                continue
            seen_spans.add(span)
            matches.append(
                NormalizedConcept(
                    span={"start": span[0], "end": span[1]},
                    surface_text=match.group(0),
                    normalized_concept=concept,
                    snomed_ct_id=code,
                    clinical_domain=domain,
                )
            )

    # Sort by start position
    matches.sort(key=lambda m: m.span.get("start", 0) if isinstance(m.span, dict) else 0)
    return matches
