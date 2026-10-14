from .base import *

DEBUG = False
SECRET_KEY = "test-secret-key-not-for-production"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # speed only
LOG_JSON = False
LOG_LEVEL = "WARNING"
ALLOWED_HOSTS = ["*"]
TENANT_BASE_DOMAIN = "tutortrack.test"

# The test database is created and migrated as the owner role; backend/conftest.py then
# switches the default connection to the application role so the whole suite runs under
# row-level security, exactly like production.
DB_APP_ROLE = (DATABASES["default"]["USER"], DATABASES["default"]["PASSWORD"])
DATABASES["default"] = {**DATABASES["owner"]}
del DATABASES["owner"]  # migrate must target the test database via "default"
# Concurrent suites (e.g. several git worktrees) need their own test database.
if env("TEST_DB_NAME", default=""):
    DATABASES["default"]["TEST"] = {"NAME": env("TEST_DB_NAME")}
    DATABASES["platform"]["TEST"] = {"NAME": env("TEST_DB_NAME")}
DB_RLS_ROLE_CHECK = "off"
DB_GRANT_TRUNCATE = True  # Django flushes transactional tests with TRUNCATE

# Tests run without Redis for cache/sessions so the suite works anywhere; tests that need
# Redis (locks) use REDIS_URL directly and are marked `redis`.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
SESSION_ENGINE = "django.contrib.sessions.backends.db"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

AWS_STORAGE_BUCKET_NAME = "tutortrack-test"
AWS_S3_ENDPOINT_URL = None
AWS_S3_PUBLIC_ENDPOINT_URL = None
AWS_ACCESS_KEY_ID = "testing"
AWS_SECRET_ACCESS_KEY = "testing"
CLAMAV = {"ENABLED": False, "HOST": "localhost", "PORT": 3310}

OUTBOX = {**OUTBOX, "MAX_ATTEMPTS": 3, "BACKOFF_BASE_SECONDS": 0}

# Concrete models and routes that exercise the abstract core primitives.
INSTALLED_APPS = [*INSTALLED_APPS, "tutortrack.core.tests.testapp"]
ROOT_URLCONF = "tutortrack.core.tests.testapp.api"

PWNED_PASSWORDS_CHECK = False  # no network in tests
# The time-skipping test server has no search attributes; tests that need Temporal use the
# temporal_env fixture, anything else fails fast instead of reaching a local dev server.
# Each test starts a fresh activity thread pool, so activities close their connections
# rather than keeping them for CONN_MAX_AGE (which exhausted Postgres under xdist).
TEMPORAL = {
    **TEMPORAL,
    "SEARCH_ATTRIBUTES": False,
    "ADDRESS": "127.0.0.1:1",
    "CLOSE_CONNECTIONS_AFTER_ACTIVITY": True,
}

# E22: CalDAV/Lessonspace use their fakes in tests (no network).
INTEGRATIONS = {**INTEGRATIONS, "CREDENTIAL_PROVIDERS_LIVE": False}
# E11 Phase 2: GoCardless and PayPal always use their fakes in tests.
GOCARDLESS = {**GOCARDLESS, "CLIENT_ID": "", "WEBHOOK_SECRET": ""}
PAYPAL = {**PAYPAL, "CLIENT_ID": "", "WEBHOOK_ID": ""}

# E24: hosted websites resolve at <slug>.tutortrack-site.test.
CUSTOM_DOMAINS = {**CUSTOM_DOMAINS, "SITE_BASE_DOMAIN": "tutortrack-site.test"}

# E31: always the deterministic fake LLM (the suite never calls the real API).
AI = {**AI, "PROVIDER": "fake", "API_KEY": ""}

# Phase 3 (ADR 0032): warehouse destinations use their fake in tests.
WAREHOUSE_EXPORT = {**WAREHOUSE_EXPORT, "LIVE": False}
