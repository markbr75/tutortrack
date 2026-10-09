"""Base settings shared by every environment. Values come from the environment (12-factor)."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BASE_DIR.parent

env = environ.Env()
environ.Env.read_env(REPO_ROOT / ".env", overwrite=False)

# --- Core -------------------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
TENANT_BASE_DOMAIN = env("TENANT_BASE_DOMAIN", default="localhost")
# The root app (signup, email verification, org picker), e.g. https://app.tutortrack.app.
APP_URL = env("APP_URL", default="https://app.tutortrack.app")
# Public URL of an organisation's app (emails, redirects, the org switcher).
TENANT_URL_TEMPLATE = env("TENANT_URL_TEMPLATE", default="https://{slug}.{domain}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    # third party
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
    # TutorTrack
    "tutortrack.core",
    "tutortrack.tenancy",
    "tutortrack.identity",
    "tutortrack.workflows",
    "tutortrack.privacy",
    "tutortrack.people",
    "tutortrack.crm",
    "tutortrack.catalogue",
    "tutortrack.jobs",
]

MIDDLEWARE = [
    "tutortrack.core.middleware.RequestContextMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "tutortrack.core.security.SecurityHeadersMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "tutortrack.identity.middleware.SessionSecurityMiddleware",
    "tutortrack.identity.impersonation.ImpersonationMiddleware",
    "tutortrack.core.middleware.UserContextMiddleware",
    "tutortrack.tenancy.middleware.TenantMiddleware",
    "tutortrack.tenancy.middleware.OrganisationStatusMiddleware",
    "tutortrack.identity.middleware.MFAEnforcementMiddleware",
    "tutortrack.core.idempotency.IdempotencyMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database ---------------------------------------------------------------------------------
# Three roles (docs/02-architecture.md §3, FR-02-4; created by `manage.py ensure_db_roles`):
#   default  - the application role. Not the table owner and NOBYPASSRLS, so RLS applies.
#   owner    - owns the tables; `manage.py migrate` runs as this role automatically.
#   platform - BYPASSRLS, for platform-admin code only (E30).
DATABASES = {
    "default": env.db(
        "DATABASE_URL", default="postgres://tutortrack_app:tutortrack_app@localhost:5442/tutortrack"
    ),
    "owner": env.db(
        "DATABASE_OWNER_URL", default="postgres://tutortrack:tutortrack@localhost:5442/tutortrack"
    ),
    "platform": env.db(
        "DATABASE_PLATFORM_URL",
        default="postgres://tutortrack_platform:tutortrack_platform@localhost:5442/tutortrack",
    ),
}
for _db in DATABASES.values():
    _db["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
    _db["CONN_HEALTH_CHECKS"] = True
DATABASE_ROUTERS = ["tutortrack.core.db.DatabaseRouter"]
# Connections that carry the app.current_org / app.current_user session variables.
RLS_DB_ALIASES = ["default"]
# What to do if the default role bypasses RLS (superuser/BYPASSRLS): "error" | "warn" | "off".
DB_RLS_ROLE_CHECK = env("DB_RLS_ROLE_CHECK", default="error")
# Primary keys are UUIDv7 via core.models.UUIDModel; this only applies to third-party models.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth -------------------------------------------------------------------------------------
AUTH_USER_MODEL = "identity.User"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    # Roles, data scopes and tutor access toggles (E03, identity.rbac).
    "tutortrack.identity.backends.RBACBackend",
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "tutortrack.identity.password_validation.ZxcvbnValidator"},
    {"NAME": "tutortrack.identity.password_validation.PwnedPasswordValidator"},
]
PWNED_PASSWORDS_CHECK = env.bool("PWNED_PASSWORDS_CHECK", default=True)
PASSWORD_RESET_TIMEOUT = 60 * 60  # 1 hour (E03 §6)
# Sessions (FR-03-3): staff sign out after idle hours (orgs may shorten via
# security.staff_idle_timeout_hours); "remember me" lasts PORTAL_REMEMBER_DAYS.
SESSION_IDLE_TIMEOUT_HOURS = 8
PORTAL_REMEMBER_DAYS = 30
SESSION_COOKIE_AGE = PORTAL_REMEMBER_DAYS * 24 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
MFA_ENROLMENT_EXEMPT_PATHS = ["/api/v1/me", "/api/v1/auth/"]

# --- i18n / time ------------------------------------------------------------------------------
LANGUAGE_CODE = "en-gb"
LANGUAGES = [("en-gb", "English (UK)"), ("en-us", "English (US)")]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
LOCALE_PATHS = [BASE_DIR / "locale"]

# --- Static / media ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="tutortrack-local")
AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default=None)
AWS_S3_PUBLIC_ENDPOINT_URL = env("AWS_S3_PUBLIC_ENDPOINT_URL", default=None)
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default=None)
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default=None)
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="eu-west-2")
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = True

STORAGES = {
    "default": {"BACKEND": "storages.backends.s3.S3Storage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

FILE_UPLOADS = {
    "MAX_SIZE_BYTES": env.int("FILE_UPLOAD_MAX_BYTES", default=25 * 1024 * 1024),
    "ALLOWED_CONTENT_TYPES": [
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/heic",
        "text/csv",
        "text/plain",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "audio/mpeg",
        "video/mp4",
    ],
    "PRESIGN_EXPIRY_SECONDS": 900,
}
CLAMAV = {
    "ENABLED": env.bool("CLAMAV_ENABLED", default=False),
    "HOST": env("CLAMAV_HOST", default="localhost"),
    "PORT": env.int("CLAMAV_PORT", default=3310),
}

# --- Cache / Redis ----------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://localhost:6389/0")
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        "KEY_PREFIX": "tt",
    }
}
SESSION_ENGINE = "django.contrib.sessions.backends.cache"

# --- Email ------------------------------------------------------------------------------------
EMAIL_CONFIG = env.email_url("EMAIL_URL", default="smtp://localhost:1025")
vars().update(EMAIL_CONFIG)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="TutorTrack <noreply@tutortrack.app>")

# --- Celery -----------------------------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6389/1")
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TIMEZONE = "UTC"

# --- CORS / CSRF ------------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "x-csrftoken",
    "x-request-id",
    "x-organisation",
    "idempotency-key",
    "if-match",
]
CORS_EXPOSE_HEADERS = ["etag", "x-request-id"]
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# --- DRF / OpenAPI ----------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "tutortrack.core.api.pagination.CursorPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "tutortrack.core.api.schema.AutoSchema",
    "EXCEPTION_HANDLER": "tutortrack.core.api.exceptions.problem_exception_handler",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
    "DATETIME_FORMAT": "iso-8601",
    "DEFAULT_THROTTLE_RATES": {
        "signup": env("THROTTLE_SIGNUP", default="10/hour"),
        "verify_email": "30/hour",
        "handoff": "60/hour",
        "login": env("THROTTLE_LOGIN", default="30/minute"),
        "magic_link": "10/hour",
        "password_reset": "10/hour",
        "mfa": "20/minute",
    },
    "COERCE_DECIMAL_TO_STRING": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "TutorTrack API",
    "DESCRIPTION": "Run a tutoring business end to end. All first-party apps use this API.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "ProcessStatusEnum": "tutortrack.core.models.workflows.WorkflowLink.Status",
        "ClientStatusEnum": "tutortrack.people.models.Client.Status",
        "ClientTypeEnum": "tutortrack.people.models.Client.Type",
        "StudentStatusEnum": "tutortrack.people.models.Student.Status",
        "TutorStatusEnum": "tutortrack.people.models.TutorProfile.Status",
        "FileVisibilityEnum": "tutortrack.core.models.files.StoredFile.Visibility",
        "CustomFieldVisibilityEnum": "tutortrack.crm.models.CustomFieldDefinition.Visibility",
        "NoteVisibilityEnum": "tutortrack.crm.models.Note.Visibility",
        "JobStatusEnum": "tutortrack.jobs.models.Job.Status",
        "JobTutorStatusEnum": "tutortrack.jobs.models.JobTutor.Status",
        "JobTutorRoleEnum": "tutortrack.jobs.models.JobTutor.Role",
        "RoleEnum": "tutortrack.identity.models.Membership.Role",
    },
    "POSTPROCESSING_HOOKS": ["drf_spectacular.hooks.postprocess_schema_enums"],
}

# --- Temporal (E32) ---------------------------------------------------------------------------
TEMPORAL = {
    "ADDRESS": env("TEMPORAL_ADDRESS", default="localhost:7233"),
    "NAMESPACE": env("TEMPORAL_NAMESPACE", default="tutortrack-local"),
    "TLS_CERT": env("TEMPORAL_TLS_CERT", default=""),  # file path (mTLS, Temporal Cloud)
    "TLS_KEY": env("TEMPORAL_TLS_KEY", default=""),
    "API_KEY": env("TEMPORAL_API_KEY", default=""),  # alternative to mTLS on Temporal Cloud
    # Task queues mirror the Celery queues (E32 FR-32-2).
    "TASK_QUEUES": ["default", "billing", "payroll", "comms", "integrations", "imports", "privacy"],
    # Search attributes must be registered on the namespace (docker-compose does it locally).
    "SEARCH_ATTRIBUTES": env.bool("TEMPORAL_SEARCH_ATTRIBUTES", default=True),
}
# Origins allowed to call /temporal-codec (the Temporal Web UI), e.g. https://cloud.temporal.io
TEMPORAL_CODEC_CORS_ORIGINS = env.list(
    "TEMPORAL_CODEC_CORS_ORIGINS", default=["http://localhost:8233"]
)
# AES-256-GCM keys for workflow payloads, newest first: "<key id>:<base64 32 bytes>".
TEMPORAL_PAYLOAD_KEYS = env.list(
    "TEMPORAL_PAYLOAD_KEYS",
    default=["dev1:3q2+7wABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhs="],
)

# --- Outbox -----------------------------------------------------------------------------------
OUTBOX = {
    "BATCH_SIZE": 100,
    "MAX_ATTEMPTS": env.int("OUTBOX_MAX_ATTEMPTS", default=8),
    "BACKOFF_BASE_SECONDS": 5,
}

IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60

# --- Security headers and outbound requests (E29-T01) ---------------------------------------
FRAMEABLE_PATH_PREFIXES = ["/widgets/"]  # E24 embeddable endpoints may be framed
CSP_EXTRA_SCRIPT_SRC: list[str] = []
CSP_EXTRA_CONNECT_SRC: list[str] = []
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
ALLOW_HTTP_OUTBOUND = False  # SSRF guard (core.net): https only
# Alert the owners when one person runs this many exports within the window (FR-29-2).
MASS_EXPORT_ALERT_THRESHOLD = 5
MASS_EXPORT_WINDOW_MINUTES = 60

# --- Geocoding (E05 FR-05-15) ------------------------------------------------------------------
GEOCODER = env("GEOCODER", default="tutortrack.core.geo.NullGeocoder")
GOOGLE_MAPS_API_KEY = env("GOOGLE_MAPS_API_KEY", default="")

# --- Organisation lifecycle (E02-T09) ---------------------------------------------------------
# Writes still allowed while suspended (billing, so the owner can pay; E04 adds its paths).
SUSPENDED_ORG_WRITE_ALLOWLIST = ["/api/v1/subscription", "/api/v1/auth/"]
# Reachable whatever the organisation's status (sign-in, health).
ORG_STATUS_EXEMPT_PATHS = ["/api/v1/auth/", "/api/v1/me/organisations", "/healthz", "/readyz"]

# --- Field encryption (core.crypto; KMS-managed in E29) ---------------------------------------
# Comma-separated Fernet keys, newest first. Generate: python -c "from cryptography.fernet import
# Fernet; print(Fernet.generate_key().decode())"
FIELD_ENCRYPTION_KEYS = env.list(
    "FIELD_ENCRYPTION_KEYS", default=["DbyhxHUuYW0d6P-VFWYHcV9sWb7MmEwUC9RsDpmJpS8="]
)
# When set, FIELD_ENCRYPTION_KEYS hold KMS-wrapped data keys (envelope encryption, E29-T02).
FIELD_ENCRYPTION_KMS_KEY_ID = env("FIELD_ENCRYPTION_KMS_KEY_ID", default="")
AWS_KMS_REGION = env("AWS_KMS_REGION", default="")

# --- Signup (E02-T06) -------------------------------------------------------------------------
TURNSTILE_SITE_KEY = env("TURNSTILE_SITE_KEY", default="")
TURNSTILE_SECRET_KEY = env("TURNSTILE_SECRET_KEY", default="")
EMAIL_VERIFICATION_MAX_AGE_SECONDS = 3 * 24 * 60 * 60

# --- SSO (E03-T07): a provider is enabled when both values are set ----------------------------
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", default="")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET", default="")
MICROSOFT_CLIENT_ID = env("MICROSOFT_CLIENT_ID", default="")
MICROSOFT_CLIENT_SECRET = env("MICROSOFT_CLIENT_SECRET", default="")

# --- Observability ----------------------------------------------------------------------------
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOG_JSON = env.bool("LOG_JSON", default=True)
SENTRY_DSN = env("SENTRY_DSN", default="")
SENTRY_ENVIRONMENT = env("SENTRY_ENVIRONMENT", default="local")
OTEL_EXPORTER_OTLP_ENDPOINT = env("OTEL_EXPORTER_OTLP_ENDPOINT", default="")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "botocore": {"level": "WARNING"},
    },
}
