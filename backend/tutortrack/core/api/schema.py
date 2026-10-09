from __future__ import annotations

from typing import Any

from drf_spectacular.extensions import OpenApiSerializerFieldExtension
from drf_spectacular.openapi import AutoSchema as SpectacularAutoSchema
from drf_spectacular.utils import OpenApiParameter

from .serializers import BaseModelSerializer


class AutoSchema(SpectacularAutoSchema):
    """Documents ``?fields`` / ``?expand`` on GET endpoints using BaseModelSerializer, and
    ``Idempotency-Key`` / ``If-Match`` headers where they apply."""

    def get_override_parameters(self) -> list[Any]:
        params = list(super().get_override_parameters())
        serializer = self.get_response_serializers()
        method = self.method.upper()
        if method == "GET" and isinstance(serializer, BaseModelSerializer):
            params.append(
                OpenApiParameter(
                    "fields", str, description="Comma-separated fields to return (sparse)."
                )
            )
            expandable = getattr(getattr(serializer, "Meta", None), "expandable_fields", {})
            if expandable:
                params.append(
                    OpenApiParameter(
                        "expand",
                        str,
                        description="Comma-separated relations to expand: "
                        + ", ".join(sorted(expandable)),
                    )
                )
        if method == "POST":
            params.append(
                OpenApiParameter(
                    "Idempotency-Key",
                    str,
                    location=OpenApiParameter.HEADER,
                    description="Makes the request safe to retry for 24 hours.",
                )
            )
        if method in {"PUT", "PATCH"} and getattr(self.view, "supports_if_match", False):
            params.append(
                OpenApiParameter(
                    "If-Match",
                    str,
                    location=OpenApiParameter.HEADER,
                    description="ETag from a previous GET; 412 if the resource changed.",
                )
            )
        return params


class MoneyFieldExtension(OpenApiSerializerFieldExtension):
    target_class = "tutortrack.core.api.serializers.MoneySerializerField"

    def map_serializer_field(self, auto_schema: Any, direction: Any) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                # Decimal strings: floats are rejected because they lose precision.
                "amount": {
                    "type": "string",
                    "format": "decimal",
                    "pattern": r"^-?\d+(\.\d+)?$",
                    "example": "40.00",
                },
                "currency": {"type": "string", "example": "GBP", "minLength": 3, "maxLength": 3},
            },
            "required": ["amount", "currency"],
        }


def lib_doc_excludes() -> list[type]:
    """Base classes whose docstrings must not become component descriptions."""
    from drf_spectacular.plumbing import get_lib_doc_excludes

    from .serializers import (
        BaseModelSerializer,
        DynamicFieldsMixin,
        ExpandableFieldsMixin,
        FieldPermissionMixin,
    )

    return [
        BaseModelSerializer,
        FieldPermissionMixin,
        DynamicFieldsMixin,
        ExpandableFieldsMixin,
        *get_lib_doc_excludes(),
    ]
