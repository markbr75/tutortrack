from .base import *

DEBUG = False
SECRET_KEY = "test-secret-key-not-for-production"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # speed only
LOG_JSON = False
LOG_LEVEL = "WARNING"
ALLOWED_HOSTS = ["*"]
TENANT_BASE_DOMAIN = "tutortrack.test"

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
