"""Pytest configuration and fixtures for Step 2 Clinical NLP tests.

Provides mock implementations for testing without external API dependencies.
These fixtures are ONLY for tests — never imported in production code.
"""

import pytest

from services.clinical_nlp.app.adapters import NLPAdapterBundle
from services.clinical_nlp.app.contextualization import (
    ContextualizationAdapter,
    ContextualizationResult,
)
from services.clinical_nlp.app.contextualization.assertion import detect_assertion
from services.clinical_nlp.app.contextualization.temporal import extract_temporal_context
from services.clinical_nlp.app.ner import HybridNERAdapter


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


@pytest.fixture
def mock_adapter_bundle() -> NLPAdapterBundle:
    """Create an NLPAdapterBundle with mock contextualizer for unit tests.

    Uses load_models=False for fast execution without spaCy models.
    Only dictionary and regex extractions will work.

    Returns:
        NLPAdapterBundle with HybridNERAdapter (load_models=False) and MockGeminiContextualizationAdapter
    """
    return NLPAdapterBundle(
        ner=HybridNERAdapter(load_models=False),
        contextualization=MockGeminiContextualizationAdapter(),
    )


@pytest.fixture
def integration_adapter_bundle() -> NLPAdapterBundle:
    """Create an NLPAdapterBundle with mock contextualizer for integration tests.

    Uses load_models=True to load spaCy models for full NER capability.
    This fixture is slower but provides full HybridNERAdapter functionality.

    Returns:
        NLPAdapterBundle with HybridNERAdapter (load_models=True) and MockGeminiContextualizationAdapter
    """
    return NLPAdapterBundle(
        ner=HybridNERAdapter(load_models=True),
        contextualization=MockGeminiContextualizationAdapter(),
    )