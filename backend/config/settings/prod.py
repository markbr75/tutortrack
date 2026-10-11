from .base import *

DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY")  # required in production
TURNSTILE_SECRET_KEY = env("TURNSTILE_SECRET_KEY")  # signup captcha is mandatory
if not TURNSTILE_SECRET_KEY:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("TURNSTILE_SECRET_KEY must be set in production")
FIELD_ENCRYPTION_KEYS = env.list("FIELD_ENCRYPTION_KEYS")  # no development default in prod
TEMPORAL_PAYLOAD_KEYS = env.list("TEMPORAL_PAYLOAD_KEYS")  # no development default in prod
# Share the session across tenant subdomains so the org switcher needs no re-login.
SESSION_COOKIE_DOMAIN = env("SESSION_COOKIE_DOMAIN", default=None)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 63072000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
# Tenant custom domains (E24): requests are same-origin on the custom host, so CSRF needs no
# trusted origins. Set DJANGO_ALLOWED_HOSTS=* with CUSTOM_DOMAINS_STRICT_HOSTS=true so
# sites.middleware refuses hosts that are neither platform hosts nor connected domains.
CUSTOM_DOMAINS = {
    **CUSTOM_DOMAINS,
    "DNS_RESOLVER": env("CUSTOM_DOMAINS_DNS_RESOLVER", default="doh"),
    "STRICT_HOSTS": env.bool("CUSTOM_DOMAINS_STRICT_HOSTS", default=False),
}


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
