"""Step 2 Clinical NLP configuration via Pydantic BaseSettings."""

from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


CLINICAL_NLP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Step2Settings(BaseSettings):
    """Configuration for Step 2 Clinical NLP service."""

    model_config = SettingsConfigDict(
        env_file=(
            PROJECT_ROOT / ".env",
            CLINICAL_NLP_ROOT / ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Mock mode keeps local development and CI independent of external AI
    # providers. Production mode is explicit and validates its credentials.
    step2_nlp_mode: str = Field(
        default="mock",
        description="Step 2 NLP mode: 'mock' or 'production'.",
    )

    # Gemini API configuration
    gemini_api_key: str = Field(
        default="",
        description="Gemini API key for clinical contextualization. Required for production mode.",
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        description="Gemini model name for contextualization.",
    )
    # Shared AI transport settings
    ai_timeout_seconds: float = Field(
        default=15.0,
        description="HTTP timeout for AI provider calls.",
    )
    ai_max_retries: int = Field(
        default=2,
        description="Maximum retries for AI provider calls.",
    )

    @field_validator("step2_nlp_mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        if value.lower() not in {"mock", "production"}:
            raise ValueError("STEP2_NLP_MODE must be 'mock' or 'production'.")
        return value.lower()

    @model_validator(mode="after")
    def validate_production_credentials(self) -> "Step2Settings":
        self.gemini_api_key = self.gemini_api_key.strip()
        if self.step2_nlp_mode == "production" and not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when STEP2_NLP_MODE=production.")
        return self


# Global settings instance
settings = Step2Settings()
