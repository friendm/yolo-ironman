from django.conf import settings
from django.core.checks import Warning, register

GUESSABLE_ADMIN_PATHS = {"admin/", "django-admin/", "djangoadmin/", "administrator/", "backend/", "ops/"}


@register("security", deploy=True)
def admin_url_check(app_configs, **kwargs):
    """Warn when the data admin is mounted at a path attackers try first."""
    path = (settings.DJANGO_ADMIN_URL or "").lower()
    if path in GUESSABLE_ADMIN_PATHS or (path and len(path.strip("/")) < 12):
        return [
            Warning(
                "DJANGO_ADMIN_URL is easy to guess.",
                hint='Use a long random path, e.g. python -c "import secrets; print(secrets.token_urlsafe(16))".',
                id="common.W001",
            )
        ]
    return []
