"""Logging (structlog), Sentry and OpenTelemetry setup.

Called at the end of the dev/prod settings modules. Every integration is optional and
driven by environment variables, so local development needs none of them.
"""

from __future__ import annotations

import logging
import logging.config
import re
from collections.abc import MutableMapping
from typing import Any

import structlog

_SENSITIVE_KEY = re.compile(
    r"pass(word)?|token|secret|authori[sz]ation|api[_-]?key|cookie|session|"
    r"card|iban|account_number|sort_code|routing|ssn|tax_id|dob|date_of_birth",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_REDACTED = "[REDACTED]"


def scrub_pii(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """structlog processor: redact sensitive keys and email addresses from log events."""
    for key in list(event_dict):
        value = event_dict[key]
        if _SENSITIVE_KEY.search(key):
            event_dict[key] = _REDACTED
        elif isinstance(value, str):
            event_dict[key] = _EMAIL.sub("[EMAIL]", value)
    return event_dict


def configure_logging(*, level: str, json: bool) -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        scrub_pii,
    ]
    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "structlog": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processors": [
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        structlog.processors.format_exc_info,
                        renderer,
                    ],
                    "foreign_pre_chain": shared,
                }
            },
            "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "structlog"}},
            "root": {"handlers": ["console"], "level": level},
            "loggers": {
                "django.db.backends": {"level": "WARNING"},
                "botocore": {"level": "WARNING"},
                "urllib3": {"level": "WARNING"},
            },
        }
    )


def configure_sentry(dsn: str, environment: str) -> None:
    if not dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        send_default_pii=False,
        traces_sample_rate=0.1,
    )


def configure_tracing(endpoint: str) -> None:
    if not endpoint:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.celery import CeleryInstrumentor
    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "tutortrack-backend"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    DjangoInstrumentor().instrument()
    CeleryInstrumentor().instrument()
    PsycopgInstrumentor().instrument()
    RedisInstrumentor().instrument()


def configure_observability(
    *, log_level: str, log_json: bool, sentry_dsn: str, sentry_env: str, otlp_endpoint: str
) -> None:
    """Called from settings modules with plain values (django.conf.settings isn't ready yet)."""
    configure_logging(level=log_level, json=log_json)
    configure_sentry(sentry_dsn, sentry_env)
    configure_tracing(otlp_endpoint)
