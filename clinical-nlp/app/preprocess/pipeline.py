from dataclasses import dataclass
import re
import unicodedata

from contracts.schemas import ExtractedField, SourceTextSpan, Step1Output


@dataclass(frozen=True)
class PreprocessedField:
    source_field: ExtractedField
    original_text: str
    processed_text: str
    source_text_span: SourceTextSpan


def normalize_text(text: str) -> str:
    """Clinically safe text normalization.

    Performs:
    - Unicode NFC normalization
    - Stripping of zero-width and non-printable OCR artifacts
    - Standardization of typographical quotes and hyphens
    - Multi-whitespace and linebreak collapse
    - Preservation of medical abbreviations, units, decimals, and clinical punctuation
    """
    if not text:
        return ""

    # 1. Unicode NFC normalization
    normalized = unicodedata.normalize("NFC", text)

    # 2. Remove zero-width spaces, soft hyphens, BOMs, form feeds, and control chars
    normalized = re.sub(r"[\u200b\u200c\u200d\u00ad\ufeff\f\r]", "", normalized)

    # 3. Standardize unicode typographic quotes and dashes to standard ASCII
    normalized = re.sub(r"[\u2018\u2019\u201a\u201b]", "'", normalized)
    normalized = re.sub(r"[\u201c\u201d\u201e\u201f]", '"', normalized)
    normalized = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]", "-", normalized)

    # 4. Standardize unicode spaces (e.g. non-breaking space \u00a0, em space, en space, thin space)
    normalized = re.sub(r"[\u00a0\u2000-\u200a\u202f\u205f\u3000]", " ", normalized)

    # 5. Clean OCR bullet noise and scan edge lines if dangling at line/token boundaries
    normalized = re.sub(r"(?:^|\s)[|~•·*](?=\s|$)", " ", normalized)

    # 6. Normalize multiple whitespaces and newlines into a single clean space
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized


def preprocess_field(field: ExtractedField) -> PreprocessedField:
    original_text = field.raw_text.strip()
    return PreprocessedField(
        source_field=field,
        original_text=original_text,
        processed_text=normalize_text(field.standardized_text),
        source_text_span=SourceTextSpan(start=0, end=len(original_text)),
    )


def preprocess_step1_output(step1_output: Step1Output) -> list[PreprocessedField]:
    return [preprocess_field(field) for field in step1_output.extracted_fields]
