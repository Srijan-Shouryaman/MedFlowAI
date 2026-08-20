from dataclasses import dataclass

from .config import settings
from .contextualization import (
    ContextualizationAdapter,
    DeterministicContextualizationAdapter,
    ProductionGeminiContextualizationAdapter,
)
from .ner import (
    HybridNERAdapter,
    MockClinicalNERAdapter,
    NERAdapter,
)


@dataclass(frozen=True)
class NLPAdapterBundle:
    ner: NERAdapter
    contextualization: ContextualizationAdapter


def build_adapter_bundle() -> NLPAdapterBundle:
    """Build the configured Step 2 adapters."""
    if settings.step2_nlp_mode == "mock":
        return NLPAdapterBundle(
            ner=MockClinicalNERAdapter(),
            contextualization=DeterministicContextualizationAdapter(),
        )

    return NLPAdapterBundle(
        ner=HybridNERAdapter(),
        contextualization=ProductionGeminiContextualizationAdapter(
            api_key=settings.gemini_api_key,
            model_name=settings.gemini_model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
        ),
    )
