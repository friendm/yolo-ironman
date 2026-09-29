"""Django settings for the Vendor COI Network.

Every secret comes from the environment; see .env.example for the full list.
"""

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_dotenv(path):
    """Minimal .env loader so local development needs no extra dependency."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv(BASE_DIR / ".env")


def parse_database_url(url):
    parsed = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
        "CONN_MAX_AGE": 60,
    }


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY") or ("dev-insecure-key" if DEBUG else None)
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

# Railway: trust the generated public domain, and accept Railway's healthcheck requests.
RAILWAY_PUBLIC_DOMAIN = env("RAILWAY_PUBLIC_DOMAIN")
if RAILWAY_PUBLIC_DOMAIN:
    ALLOWED_HOSTS.append(RAILWAY_PUBLIC_DOMAIN)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RAILWAY_PUBLIC_DOMAIN}")
if env("RAILWAY_ENVIRONMENT_NAME") or env("RAILWAY_ENVIRONMENT"):
    ALLOWED_HOSTS.append("healthcheck.railway.app")

# Absolute base URL used in SMS and email links (no trailing slash).
SITE_URL = (
    env("SITE_URL") or (f"https://{RAILWAY_PUBLIC_DOMAIN}" if RAILWAY_PUBLIC_DOMAIN else "http://localhost:8000")
).rstrip("/")
SITE_NAME = env("SITE_NAME", "COI Network")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.postgres",
    "django.forms",
    "django_q",
    "common",
    "accounts",
    "vendors",
    "events",
    "documents",
    "ops",
    "notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "common.middleware.ContentSecurityPolicyMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "common.context_processors.site",
            ],
        },
    },
]

FORM_RENDERER = "common.forms.Renderer"

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": parse_database_url(env("DATABASE_URL", "postgresql://coi:coi@localhost:5432/coi"))}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Uploaded documents are private. With S3 configured they live in a private
# bucket and are served through presigned URLs; otherwise they are written to
# PRIVATE_MEDIA_ROOT, which is never exposed as a static path.
PRIVATE_MEDIA_ROOT = Path(env("PRIVATE_MEDIA_ROOT", BASE_DIR / "private_media"))
SIGNED_URL_SECONDS = 600
AWS_STORAGE_BUCKET_NAME = env("S3_BUCKET")
USE_S3 = bool(AWS_STORAGE_BUCKET_NAME)
if USE_S3:
    default_storage = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": AWS_STORAGE_BUCKET_NAME,
            "access_key": env("S3_ACCESS_KEY_ID"),
            "secret_key": env("S3_SECRET_ACCESS_KEY"),
            "endpoint_url": env("S3_ENDPOINT_URL") or None,
            "region_name": env("S3_REGION") or None,
            "default_acl": "private",
            "querystring_auth": True,
            "querystring_expire": SIGNED_URL_SECONDS,
            "file_overwrite": False,
            # Railway buckets use virtual-hosted style URLs; leave unset elsewhere to let boto decide.
            "addressing_style": env("S3_ADDRESSING_STYLE") or None,
        },
    }
else:
    default_storage = {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": PRIVATE_MEDIA_ROOT},
    }
STORAGES = {
    "default": default_storage,
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 16 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# Database cache so rate limits hold across web processes.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "cache_table",
    }
}

# Twilio (SMS). Without credentials, messages are logged instead of sent.
TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = env("TWILIO_FROM_NUMBER")

# Email via Postmark or Resend SMTP. Console backend when no host is set.
EMAIL_HOST = env("EMAIL_HOST")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = int(env("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", f"{SITE_NAME} <hello@localhost>")
ADMIN_DIGEST_EMAILS = [e.strip() for e in env("ADMIN_DIGEST_EMAILS", "").split(",") if e.strip()]

# Document extraction with Claude.
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
EXTRACTION_MODEL = env("EXTRACTION_MODEL", "claude-opus-5-5")

# Django-Q2 with Postgres as broker. Q_SYNC runs tasks inline (tests, simple dev).
Q_CLUSTER = {
    "name": "coi",
    "orm": "default",
    "workers": int(env("Q_WORKERS", "2")),
    "timeout": 120,
    "retry": 180,
    "max_attempts": 2,
    "catch_up": False,
    "sync": env_bool("Q_SYNC", DEBUG),
}

SESSION_COOKIE_AGE = 60 * 60 * 24 * 30
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_REDIRECT_EXEMPT = [r"^healthz$"]  # platform healthchecks call over plain HTTP
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
