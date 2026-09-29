import os
import tempfile

os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key")
os.environ["Q_SYNC"] = "1"
os.environ["DJANGO_ADMIN_URL"] = "test-secret-admin"
for key in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "EMAIL_HOST", "ANTHROPIC_API_KEY", "S3_BUCKET"):
    os.environ[key] = ""

from .settings import *  # noqa: E402,F403

PRIVATE_MEDIA_ROOT = tempfile.mkdtemp(prefix="coi-test-media-")
STORAGES["default"] = {  # noqa: F405
    "BACKEND": "django.core.files.storage.FileSystemStorage",
    "OPTIONS": {"location": PRIVATE_MEDIA_ROOT},
}
USE_S3 = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}  # noqa: F405
SECURE_SSL_REDIRECT = False
ADMIN_DIGEST_EMAILS = ["ops@example.com"]
