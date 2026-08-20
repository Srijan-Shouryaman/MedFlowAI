"""Object key construction for stored source documents.

The key layout is a versioned contract.  It is a pure function of
``(patient_id, document_id)``, which is what allows a stored object to be
located again without a database lookup -- useful now, while there is no
database at all.  Changing the layout or the prefix after objects exist
silently orphans every previously stored document.

Keys deliberately contain no protected health information: no original
filename, no patient name, no encounter detail, and no timestamp.  Keys travel
into logs, audit records, and presigned URLs, so only opaque identifiers
belong in them.
"""

from __future__ import annotations

import re
from uuid import UUID

from .config import env_value


DEFAULT_KEY_PREFIX = "step1"

# The frontend issues patient identifiers such as ``pat_00123``.  They are not
# UUIDs, so they are constrained here rather than trusted: anything outside
# this set could otherwise inject path segments into the key.
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# Canonical download extension per validated content type.  Used only to name
# the file the browser saves; never to build a key.
CANONICAL_EXTENSIONS = {
    "text/plain": ".txt",
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/tiff": ".tif",
}


class UnsafeIdentifierError(ValueError):
    """A caller-supplied identifier cannot be placed in an object key."""


def configured_key_prefix() -> str:
    raw = env_value("S3_KEY_PREFIX", DEFAULT_KEY_PREFIX) or DEFAULT_KEY_PREFIX
    return raw.strip("/") or DEFAULT_KEY_PREFIX


def safe_identifier(value: str, *, field: str) -> str:
    candidate = (value or "").strip()
    if not _SAFE_IDENTIFIER.match(candidate):
        raise UnsafeIdentifierError(f"{field} is not a valid identifier.")
    return candidate


def build_source_key(
    *,
    patient_id: str,
    document_id: UUID,
    prefix: str | None = None,
) -> str:
    """Return the key for a document's original uploaded bytes."""

    resolved_prefix = (prefix or configured_key_prefix()).strip("/")
    patient_segment = safe_identifier(patient_id, field="patient_id")
    return (
        f"{resolved_prefix}/patients/{patient_segment}"
        f"/documents/{document_id}/source"
    )


def canonical_extension(content_type: str | None) -> str:
    if not content_type:
        return ""
    normalized = content_type.split(";", 1)[0].strip().casefold()
    return CANONICAL_EXTENSIONS.get(normalized, "")


def download_filename(document_id: UUID, content_type: str | None) -> str:
    """Name the browser should save the file as.

    Derived from the document id rather than the uploaded filename, which may
    itself carry patient identifiers.
    """

    return f"{document_id}{canonical_extension(content_type)}"


__all__ = [
    "CANONICAL_EXTENSIONS",
    "DEFAULT_KEY_PREFIX",
    "UnsafeIdentifierError",
    "build_source_key",
    "canonical_extension",
    "configured_key_prefix",
    "download_filename",
    "safe_identifier",
]
