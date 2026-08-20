from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.registry import InMemoryDocumentRegistry
from app.storage.mock import InMemoryObjectStorage


@pytest.fixture()
def storage() -> InMemoryObjectStorage:
    return InMemoryObjectStorage(bucket="test-documents")


@pytest.fixture()
def client(storage: InMemoryObjectStorage):
    app = create_app()
    with TestClient(app) as test_client:
        # Replace what lifespan built.  Overriding after startup keeps the
        # real wiring under test and swaps only the transport.
        app.state.object_storage = storage
        app.state.document_registry = InMemoryDocumentRegistry()
        yield test_client


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)
