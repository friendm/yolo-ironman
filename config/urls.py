from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from common.views import healthz

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("", include("accounts.urls")),
    path("vendor/", include("vendors.urls")),
    path("", include("events.urls")),
    path("", include("documents.urls")),
    path("ops/", include("ops.urls")),
    path("", include("notifications.urls")),
]

# Django's data admin only exists at the secret DJANGO_ADMIN_URL path (see settings).
if settings.DJANGO_ADMIN_URL:
    urlpatterns.insert(1, path(settings.DJANGO_ADMIN_URL, admin.site.urls))

handler404 = "common.errors.not_found"
handler403 = "common.errors.forbidden"
