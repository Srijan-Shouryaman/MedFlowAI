"""Test fixtures for Step 2 Clinical NLP.

Provides mock implementations for testing without external API dependencies.
These fixtures are ONLY for tests — never imported in production code.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from services.clinical_nlp.app.contextualization import (
    ContextualizationAdapter,
    ContextualizationResult,
)
from services.clinical_nlp.app.contextualization.assertion import detect_assertion
from services.clinical_nlp.app.contextualization.temporal import extract_temporal_context


@dataclass(frozen=True)
class MockGeminiContextualizationAdapter:
    """Deterministic contextualizer for unit tests.

    Uses local assertion/temporal logic instead of calling Gemini API.
    """

    model_name = "mock-gemini-contextualizer"

    def contextualize(self, text: str, entity_text: str) -> ContextualizationResult:
        assertion = detect_assertion(text, entity_text)
        temporal = extract_temporal_context(text)
        return ContextualizationResult(
            assertion=assertion.assertion,
            clinical_status=(
                "inactive"
                if temporal.temporal_context == "past" and assertion.assertion == "affirmed"
                else assertion.clinical_status
            ),
            temporal_context=temporal.temporal_context,
            temporal_date=temporal.temporal_date,
            confidence=min(assertion.confidence, temporal.confidence, 0.84),
        )


def make_mock_adapter_bundle():
    """Create an NLPAdapterBundle with mock contextualizer for testing.

    Returns:
        NLPAdapterBundle with HybridNERAdapter and MockGeminiContextualizationAdapter
    """
    from services.clinical_nlp.app.adapters import NLPAdapterBundle
    from services.clinical_nlp.app.ner import HybridNERAdapter

    return NLPAdapterBundle(
        ner=HybridNERAdapter(load_models=False),
        contextualization=MockGeminiContextualizationAdapter(),
    )