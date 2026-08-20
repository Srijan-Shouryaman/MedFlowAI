from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from services.ai_adapters import (
    AIProviderError,
    AIProviderResponseError,
)
from typing import Protocol

from .assertion import detect_assertion
from .temporal import extract_temporal_context


@dataclass(frozen=True)
class ContextualizationResult:
    assertion: str
    clinical_status: str
    temporal_context: str
    temporal_date: object | None
    confidence: float


class ContextualizationAdapter(Protocol):
    model_name: str

    def contextualize(self, text: str, entity_text: str) -> ContextualizationResult:
        ...


class DeterministicContextualizationAdapter:
    """Local contextualizer used by mock mode and deterministic tests."""

    model_name = "deterministic-contextualizer"

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


class ProductionGeminiContextualizationAdapter:
    """Gemini contextualization using the official google-genai SDK."""

    model_name = "gemini-contextualizer"

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str | None = None,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        client: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name or self.model_name
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._uses_sdk_client = client is None
        # Initialize the google-genai client
        self._client = client or self._create_client()

    def _create_client(self):
        from google import genai
        from google.genai.types import HttpOptions

        return genai.Client(
            api_key=self.api_key,
            http_options=HttpOptions(
                timeout=self.timeout_seconds * 1000,  # Convert to milliseconds
            ),
        )

    def contextualize(self, text: str, entity_text: str) -> ContextualizationResult:
        prompt = _contextualization_prompt(text, entity_text)
        if self._uses_sdk_client:
            from google.genai.types import GenerateContentConfig

            config: Any = GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0,
            )
        else:
            config = {
                "response_mime_type": "application/json",
                "temperature": 0,
            }

        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.models.generate_content(
                    model=self.model_name,
                    contents=[{"role": "user", "parts": [{"text": prompt}]}],
                config=config,
                )
                break
            except Exception as exc:
                if attempt == self.max_retries:
                    raise AIProviderResponseError(
                        f"Gemini model '{self.model_name}' request failed: {exc}"
                    ) from exc

        content = _extract_text(response)
        try:
            parsed = json.loads(content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise AIProviderResponseError(
                f"Gemini model '{self.model_name}' returned invalid contextualization JSON: {content[:200]}"
            ) from exc

        return _contextualization_result(parsed, self.model_name)


class NLPProviderUnavailableError(AIProviderError):
    """Raised when configured clinical NLP provider execution is unavailable."""


def _contextualization_prompt(text: str, entity_text: str) -> str:
    return (
        "Return only JSON with keys assertion, clinical_status, "
        "temporal_context, temporal_date, confidence. "
        "Use temporal_date as YYYY-MM-DD or null and confidence between 0 and 1. "
        f"Entity: {entity_text}\nClinical text: {text}"
    )


def _extract_text(response: Any) -> str:
    """Extract text content from google-genai response."""
    # Try candidates first
    candidates = getattr(response, "candidates", None)
    if candidates:
        content = getattr(candidates[0], "content", None)
        if content:
            parts = getattr(content, "parts", None)
            if parts:
                part_text = getattr(parts[0], "text", None)
                if part_text:
                    return part_text

    # Fallback to direct text attribute
    direct = getattr(response, "text", None)
    if isinstance(direct, str):
        return direct

    raise AIProviderResponseError(
        "Gemini response did not contain a text candidate."
    )


def _contextualization_result(value: Any, provider: str) -> ContextualizationResult:
    if not isinstance(value, dict):
        raise AIProviderResponseError(
            f"AI provider '{provider}' returned a non-object contextualization."
        )
    required = ("assertion", "clinical_status", "temporal_context", "confidence")
    if any(not isinstance(value.get(key), str) for key in required[:3]):
        raise AIProviderResponseError(
            f"AI provider '{provider}' returned incomplete contextualization."
        )
    try:
        confidence = float(value["confidence"])
    except (TypeError, ValueError) as exc:
        raise AIProviderResponseError(
            f"AI provider '{provider}' returned invalid contextualization confidence."
        ) from exc
    if not 0.0 <= confidence <= 1.0:
        raise AIProviderResponseError(
            f"AI provider '{provider}' returned out-of-range contextualization confidence."
        )
    temporal_date = value.get("temporal_date")
    if temporal_date is not None:
        try:
            temporal_date = date.fromisoformat(str(temporal_date))
        except ValueError as exc:
            raise AIProviderResponseError(
                f"AI provider '{provider}' returned invalid temporal_date."
            ) from exc
    return ContextualizationResult(
        assertion=value["assertion"].strip(),
        clinical_status=value["clinical_status"].strip(),
        temporal_context=value["temporal_context"].strip(),
        temporal_date=temporal_date,
        confidence=confidence,
    )
