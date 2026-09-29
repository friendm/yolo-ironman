"""Short-lived signed links for private files when S3 is not configured."""

from django.conf import settings
from django.core import signing
from django.urls import reverse

SALT = "private-file"


def local_file_url(path):
    token = signing.dumps(path, salt=SALT)
    return reverse("documents:signed_file", args=[token])


def unsign_local_path(token):
    return signing.loads(token, salt=SALT, max_age=settings.SIGNED_URL_SECONDS)


def storage_url(path):
    """Return a URL for a private file that expires in SIGNED_URL_SECONDS."""
    if settings.USE_S3:
        from django.core.files.storage import default_storage

        return default_storage.url(path)
    return local_file_url(path)
