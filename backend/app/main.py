"""MedFlow AI backend.

Current scope is document storage only.  The frontend remains mock-backed for
everything else; this service exists so that an uploaded file is durably
persisted to an S3-compatible bucket instead of being discarded.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.documents import router as documents_router
from .api.schemas import StorageHealthResponse
from .registry import InMemoryDocumentRegistry
from .storage.config import env_value
from .storage.factory import build_object_storage


# Load the repo-root .env before anything reads os.environ.  Without it the
# storage factory would fall back to its AWS defaults and fail confusingly
# instead of talking to the local MinIO container.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("medflow")

DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


def configured_cors_origins() -> list[str]:
    raw = env_value("BACKEND_CORS_ORIGINS", DEFAULT_CORS_ORIGINS) or ""
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Built once at startup rather than per request: the boto3 client keeps a
    # connection pool, and rebuilding it per upload would discard it.
    app.state.object_storage = build_object_storage()
    app.state.document_registry = InMemoryDocumentRegistry()
    logger.info(
        "Backend ready",
        extra={"storage_backend": app.state.object_storage.backend_name},
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="MedFlow AI Backend",
        version="0.1.0",
        description="Document storage for the MedFlow AI clinical workflow.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=configured_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(documents_router)

    @app.get("/health", response_model=StorageHealthResponse, tags=["health"])
    def health() -> StorageHealthResponse:
        """Reports which storage backend is live.

        ``persistent`` is the field worth reading: it is false whenever the
        service is running on in-memory storage, which looks identical to a
        working system from the frontend's point of view.
        """

        storage = app.state.object_storage
        return StorageHealthResponse(
            status="ok",
            storage_backend=storage.backend_name,
            bucket=getattr(storage, "bucket", ""),
            persistent=storage.backend_name == "s3",
        )

    return app


app = create_app()


__all__ = ["app", "create_app"]
