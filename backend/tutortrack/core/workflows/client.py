"""Temporal client factory (E32 FR-32-2): encrypted payloads, tracing and Sentry."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import temporalio.converter
from django.conf import settings
from temporalio.client import Client, TLSConfig

from . import runtime
from .codec import EncryptionCodec

_client: Client | None = None
_override: Client | None = None


def data_converter() -> temporalio.converter.DataConverter:
    return dataclasses.replace(temporalio.converter.default(), payload_codec=EncryptionCodec())


def interceptors() -> list[Any]:
    from .interceptors import SentryInterceptor

    found: list[Any] = [SentryInterceptor()]
    if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        from temporalio.contrib.opentelemetry import TracingInterceptor

        found.append(TracingInterceptor())
    return found


async def connect() -> Client:
    config = settings.TEMPORAL
    tls: TLSConfig | bool = False
    if config["TLS_CERT"] and config["TLS_KEY"]:
        tls = TLSConfig(
            client_cert=Path(config["TLS_CERT"]).read_bytes(),
            client_private_key=Path(config["TLS_KEY"]).read_bytes(),
        )
    elif config["API_KEY"]:
        tls = True
    return await Client.connect(
        config["ADDRESS"],
        namespace=config["NAMESPACE"],
        data_converter=data_converter(),
        interceptors=interceptors(),
        tls=tls,
        api_key=config["API_KEY"] or None,
    )


async def get_client() -> Client:
    """The shared client (on the runtime loop). Tests install their own with ``use_client``."""
    global _client
    if _override is not None:
        return _override
    if _client is None:
        _client = await connect()
    return _client


def use_client(client: Client | None) -> None:
    """Point every caller at ``client`` (test environments); ``None`` restores the default."""
    global _override
    _override = client


def client_for_environment(env_client: Client) -> Client:
    """A client on an existing connection (e.g. a test environment) with our converter.
    The environment's own interceptors are kept (time skipping relies on one)."""
    config = env_client.config()
    config["data_converter"] = data_converter()
    config["interceptors"] = [*config.get("interceptors", []), *interceptors()]
    return Client(**config)


def get_client_sync() -> Client:
    return runtime.run(get_client())
