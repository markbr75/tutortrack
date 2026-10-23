"""Images inlined as data URIs for WeasyPrint, which must not fetch anything while it
renders a PDF (logos on invoices, statements and brand documents)."""

from __future__ import annotations

import base64
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

IMAGE_INLINE_LIMIT = 300 * 1024


def image_data_uri(file_id: Any, *, limit: int = IMAGE_INLINE_LIMIT) -> str:
    """The stored image as a ``data:`` URI, or "" when it is missing, not an image, too big
    or storage is unavailable. Runs in the caller's tenant context."""
    if not file_id:
        return ""
    from tutortrack.core.models import StoredFile

    from .client import bucket, s3_client

    try:
        stored = StoredFile.objects.filter(pk=file_id).first()
        if stored is None or not stored.is_downloadable or stored.size_bytes > limit:
            return ""
        if not stored.content_type.startswith("image/"):
            return ""
        body = s3_client().get_object(Bucket=bucket(), Key=stored.storage_key)["Body"].read()
    except Exception:  # storage unavailable: render without the image
        logger.warning("storage.inline_image_unavailable", file_id=str(file_id))
        return ""
    return f"data:{stored.content_type};base64,{base64.b64encode(body).decode()}"
