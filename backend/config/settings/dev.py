from .base import *

DEBUG = env.bool("DJANGO_DEBUG", default=True)
APP_URL = env("APP_URL", default="http://localhost:5173")
TENANT_URL_TEMPLATE = env("TENANT_URL_TEMPLATE", default="http://{slug}.{domain}:5173")
LOG_JSON = env.bool("LOG_JSON", default=False)
ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", ".localhost", "backend"]
)
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS", default=["http://localhost:5173", "http://localhost:5174"]
)
# Apps are served on tenant subdomains locally, e.g. http://brightminds.localhost:5173.
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://*.localhost:5173",
        "http://*.localhost:5174",
    ],
)

# Browsable API is handy locally.
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]


# Django must not re-apply LOGGING over the structlog configuration.
LOGGING_CONFIG = None

from config.observability import configure_observability  # noqa: E402

configure_observability(
    log_level=LOG_LEVEL,
    log_json=LOG_JSON,
    sentry_dsn=SENTRY_DSN,
    sentry_env=SENTRY_ENVIRONMENT,
    otlp_endpoint=OTEL_EXPORTER_OTLP_ENDPOINT,
)
