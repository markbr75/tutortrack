"""OpenAPI: public/internal tagging and the bearer-token security scheme (E27-T01).

Every operation gets ``x-visibility: public|internal`` (from ``scopes.PUBLIC_VIEWS``). Public
operations also list ``x-scopes`` (the scope a token needs) and the ``apiToken`` bearer
security requirement; internal ones only advertise the session cookie. The developer portal
serves the public subset (``docs.public_schema``).
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension

from tutortrack.core.api.schema import AutoSchema as CoreAutoSchema

from . import scopes

SAFE = {"GET", "HEAD", "OPTIONS"}


class AutoSchema(CoreAutoSchema):
    def get_operation(self, *args: Any, **kwargs: Any) -> Any:
        operation = super().get_operation(*args, **kwargs)
        if operation is None:
            return operation
        resource = scopes.resource_for(type(self.view))
        operation["x-visibility"] = "public" if resource else "internal"
        if resource:
            level = "read" if self.method.upper() in SAFE else "write"
            operation["x-scopes"] = [f"{resource}:{level}"]
        return operation


class ApiTokenScheme(OpenApiAuthenticationExtension):
    target_class = "tutortrack.developer.auth.ApiTokenAuthentication"
    name = "apiToken"

    def get_security_requirement(self, auto_schema: Any) -> Any:
        resource = scopes.resource_for(type(auto_schema.view))
        if resource is None:
            return None  # internal endpoints don't accept tokens
        level = "read" if auto_schema.method.upper() in SAFE else "write"
        return {self.name: [f"{resource}:{level}"]}

    def get_security_definition(self, auto_schema: Any) -> dict[str, Any]:
        return {
            "type": "http",
            "scheme": "bearer",
            "description": "An API key (`ttk_…`) or OAuth2 access token (`tta_…`).",
        }
