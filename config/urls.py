from django.contrib import admin
from django.urls import include, path

from common.views import healthz

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("django-admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("vendor/", include("vendors.urls")),
    path("", include("events.urls")),
    path("", include("documents.urls")),
    path("ops/", include("ops.urls")),
    path("", include("notifications.urls")),
]

handler404 = "common.errors.not_found"
handler403 = "common.errors.forbidden"
