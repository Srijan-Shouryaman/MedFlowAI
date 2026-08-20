from contracts.schemas import ClinicalEvent, Step1Output
from uuid import uuid4

from .abbreviations import expand_field
from .adapters import NLPAdapterBundle, build_adapter_bundle
from .event_builder import build_clinical_event
from .preprocess import preprocess_step1_output
from .pipeline_types import (
    AbbreviationSpan,
    NormalizedConcept,
    SourceMetadata,
    Step2PreprocessedField,
)
from .terminology import normalize_all_concepts, normalize_terminology
from .validation import validate_events


class ClinicalNLPPipeline:
    def __init__(self, adapters: NLPAdapterBundle | None = None) -> None:
        self.adapters = adapters or build_adapter_bundle()

    def process(self, step1_output: Step1Output) -> list[ClinicalEvent]:
        events: list[ClinicalEvent] = []
        for idx, preprocessed in enumerate(preprocess_step1_output(step1_output)):
            expanded = expand_field(preprocessed)
            field_terminology = normalize_terminology(expanded.processed_text)

            # Build the contract object for Person B's stages
            normalized_concepts = normalize_all_concepts(expanded.processed_text)

            # Convert abbreviation spans to contract format
            abbreviation_spans = list(expanded.abbreviation_spans)

            step2_field = Step2PreprocessedField(
                field_id=f"{step1_output.document_id}-{idx}",
                original_text=preprocessed.original_text,
                processed_text=expanded.processed_text,
                source_metadata=SourceMetadata(
                    input_modality=str(step1_output.input_modality),
                    source_language=step1_output.source_language,
                    translation_confidence=step1_output.translation_confidence,
                    extraction_confidence=preprocessed.source_field.extraction_confidence,
                    field_type="clinical_text",
                    source_document_id=step1_output.document_id,
                ),
                abbreviations=abbreviation_spans,
                normalized_concepts=normalized_concepts,
                preprocessing_flags={},
            )

            if hasattr(self.adapters.ner, "extract_with_enrichment"):
                entities = self.adapters.ner.extract_with_enrichment(step2_field)
            else:
                entities = self.adapters.ner.extract(expanded.processed_text)

            for entity in entities:
                terminology = normalize_terminology(entity.text)
                if entity.entity_type == "clinical_statement":
                    terminology = field_terminology
                context = self.adapters.contextualization.contextualize(
                    expanded.processed_text,
                    entity.text,
                )
                events.append(
                    build_clinical_event(
                        field=expanded,
                        terminology=terminology,
                        entity=entity,
                        context=context,
                        source_document_id=step1_output.document_id,
                        input_modality=step1_output.input_modality,
                        source_language=step1_output.source_language,
                        translation_confidence=step1_output.translation_confidence,
                    )
                )

        return validate_events(
            events,
            expected_source_document_id=step1_output.document_id,
        )
