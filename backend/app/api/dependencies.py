"""Shared FastAPI dependencies.

Both the storage client and the registry are built once during startup and
held on ``app.state``.  Resolving them through dependencies rather than module
globals is what lets the tests override them with a mock.
"""

from __future__ import annotations

from fastapi import Request

from ..registry import InMemoryDocumentRegistry
from ..storage.base import ObjectStorage


def get_object_storage(request: Request) -> ObjectStorage:
    return request.app.state.object_storage


def get_document_registry(request: Request) -> InMemoryDocumentRegistry:
    return request.app.state.document_registry


__all__ = ["get_document_registry", "get_object_storage"]
