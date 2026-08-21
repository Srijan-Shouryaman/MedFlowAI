"""Safe, bounded upload handling.

Two independent checks run on every upload:

1.  Metadata -- the filename must be safe to log and echo back, the declared
    MIME type must be on the allowlist, and any extension must agree with it.
2.  Content -- the leading bytes must actually look like the declared type.

The declared MIME type is caller-supplied and therefore untrusted.  Check 2 is
what stops a renamed executable from being stored and later served back.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import UploadFile


DEFAULT_MAX_UPLOAD_SIZE_BYTES = 25 * 1024 * 1024
DEFAULT_ALLOWED_MIME_TYPES = frozenset(
    {
        "text/plain",
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/tiff",
    }
)
MIME_EXTENSIONS = {
    "text/plain": {".txt", ".text"},
    "application/pdf": {".pdf"},
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/webp": {".webp"},
    "image/tiff": {".tif", ".tiff"},
}

# Leading-byte signatures per binary type, as (offset, expected bytes).  A type
# passes when any of its signature groups matches in full.
SIGNATURE_SAMPLE_BYTES = 8192
PDF_SIGNATURE_WINDOW = 1024
CONTENT_SIGNATURES: dict[str, tuple[tuple[tuple[int, bytes], ...], ...]] = {
    "image/png": (((0, b"\x89PNG\r\n\x1a\n"),),),
    "image/jpeg": (((0, b"\xff\xd8\xff"),),),
    "image/webp": (((0, b"RIFF"), (8, b"WEBP")),),
    "image/tiff": (
        ((0, b"II*\x00"),),
        ((0, b"MM\x00*"),),
        ((0, b"II+\x00"),),  # BigTIFF
        ((0, b"MM\x00+"),),
    ),
}
# Control characters that legitimately appear in plain text.
_ALLOWED_TEXT_CONTROLS = frozenset({0x09, 0x0A, 0x0D, 0x0C})
_UTF8_BOM = b"\xef\xbb\xbf"


class UploadSecurityError(ValueError):
    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ValidatedUpload:
    content: bytes
    filename: str
    content_type: str


def configured_max_upload_size() -> int:
    raw = os.getenv("MAX_UPLOAD_SIZE_BYTES")
    try:
        value = int(raw) if raw else DEFAULT_MAX_UPLOAD_SIZE_BYTES
    except ValueError:
        value = DEFAULT_MAX_UPLOAD_SIZE_BYTES
    return max(value, 1)


def configured_mime_types() -> frozenset[str]:
    raw = os.getenv("ALLOWED_UPLOAD_MIME_TYPES")
    if not raw:
        return DEFAULT_ALLOWED_MIME_TYPES
    values = frozenset(
        value.strip().casefold().split(";", 1)[0]
        for value in raw.split(",")
        if value.strip()
    )
    return values or DEFAULT_ALLOWED_MIME_TYPES


def validate_upload_metadata(
    *,
    filename: str | None,
    content_type: str | None,
    allowed_mime_types: frozenset[str] | None = None,
) -> tuple[str, str]:
    if not filename or not filename.strip():
        raise UploadSecurityError("A safe filename is required.", status_code=400)
    clean_filename = filename.strip()
    if (
        len(clean_filename) > 255
        or "\x00" in clean_filename
        or "/" in clean_filename
        or "\\" in clean_filename
        or clean_filename in {".", ".."}
        or clean_filename.startswith("..")
    ):
        raise UploadSecurityError("Unsafe filename.", status_code=400)

    normalized_type = (content_type or "").split(";", 1)[0].strip().casefold()
    allowed = allowed_mime_types or configured_mime_types()
    if normalized_type not in allowed:
        raise UploadSecurityError("Unsupported upload type.", status_code=415)

    extension = os.path.splitext(clean_filename)[1].casefold()
    expected_extensions = MIME_EXTENSIONS.get(normalized_type)
    if extension and expected_extensions and extension not in expected_extensions:
        raise UploadSecurityError(
            "Filename extension does not match the upload type.",
            status_code=415,
        )
    return clean_filename, normalized_type


def magic_byte_check_enabled() -> bool:
    raw = os.getenv("UPLOAD_MAGIC_BYTE_CHECK")
    if raw is None:
        return True
    return raw.strip().casefold() not in {"0", "false", "no", "off"}


def _matches_signature(head: bytes, groups) -> bool:
    return any(
        all(
            head[offset : offset + len(expected)] == expected
            for offset, expected in group
        )
        for group in groups
    )


def sniff_matches(head: bytes, declared_type: str) -> bool:
    """Whether the leading bytes are consistent with the declared type."""

    if declared_type == "application/pdf":
        # The PDF spec tolerates leading bytes before the header, and real
        # scanner output sometimes has them, so search a short window rather
        # than requiring offset 0.  This is a deliberate, documented relaxation.
        return b"%PDF-" in head[:PDF_SIGNATURE_WINDOW]

    groups = CONTENT_SIGNATURES.get(declared_type)
    if groups is None:
        return True
    return _matches_signature(head, groups)


def looks_like_text(head: bytes) -> bool:
    """Negative validation for text/plain, which has no magic bytes."""

    if b"\x00" in head:
        return False

    # A binary format smuggled in as text.
    if any(sniff_matches(head, mime) for mime in CONTENT_SIGNATURES):
        return False
    if b"%PDF-" in head[:PDF_SIGNATURE_WINDOW]:
        return False

    sample = head[len(_UTF8_BOM) :] if head.startswith(_UTF8_BOM) else head
    if any(byte < 0x20 and byte not in _ALLOWED_TEXT_CONTROLS for byte in sample):
        return False

    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as exc:
        # Tolerate a multi-byte sequence clipped by the sample boundary.
        if len(sample) < SIGNATURE_SAMPLE_BYTES or exc.start < len(sample) - 3:
            return False
    return True


def validate_content_signature(content: bytes, declared_type: str) -> None:
    if not content:
        return

    head = content[:SIGNATURE_SAMPLE_BYTES]
    if declared_type == "text/plain":
        matched = looks_like_text(head)
    else:
        matched = sniff_matches(head, declared_type)

    if not matched:
        # Deliberately the same message the MIME allowlist uses, so a probing
        # caller cannot learn which check rejected the upload.
        raise UploadSecurityError("Unsupported upload type.", status_code=415)


async def read_validated_upload(upload: UploadFile) -> ValidatedUpload:
    filename, content_type = validate_upload_metadata(
        filename=upload.filename,
        content_type=upload.content_type,
    )
    max_bytes = configured_max_upload_size()
    declared_size = getattr(upload, "size", None)
    if declared_size is not None and declared_size > max_bytes:
        raise UploadSecurityError("Uploaded file is too large.", status_code=413)

    # Read in chunks and stop at the limit rather than buffering an arbitrarily
    # large body first and checking afterwards.
    chunks: list[bytes] = []
    total = 0
    chunk_size = 64 * 1024
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UploadSecurityError("Uploaded file is too large.", status_code=413)
        chunks.append(chunk)

    content = b"".join(chunks)
    if not content:
        raise UploadSecurityError("Uploaded file is empty.", status_code=400)
    if magic_byte_check_enabled():
        validate_content_signature(content, content_type)

    return ValidatedUpload(
        content=content,
        filename=filename,
        content_type=content_type,
    )


__all__ = [
    "CONTENT_SIGNATURES",
    "DEFAULT_ALLOWED_MIME_TYPES",
    "DEFAULT_MAX_UPLOAD_SIZE_BYTES",
    "UploadSecurityError",
    "ValidatedUpload",
    "configured_max_upload_size",
    "configured_mime_types",
    "looks_like_text",
    "magic_byte_check_enabled",
    "read_validated_upload",
    "sniff_matches",
    "validate_content_signature",
    "validate_upload_metadata",
]
