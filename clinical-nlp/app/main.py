from fastapi import FastAPI

from .adapters import build_adapter_bundle
from .config import settings
from .router import router
from .service import ClinicalNLPService


def create_app(service: ClinicalNLPService | None = None) -> FastAPI:
    # Validate configuration on startup - fail fast if GEMINI_API_KEY is missing
    _ = settings.gemini_api_key  # Triggers validation

    if service is None:
        adapters = build_adapter_bundle()
        service = ClinicalNLPService(adapters=adapters)

    app = FastAPI(
        title="Clinical Memory System - Step 2 Clinical NLP",
        version="1.0.0",
    )
    app.state.clinical_nlp_service = service
    app.include_router(router, prefix="/api/v1")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy", "service": "clinical-nlp"}

    return app


app = create_app()
