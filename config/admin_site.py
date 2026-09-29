from django.contrib import admin
from django.http import HttpResponse

from common.ratelimit import client_ip, hit

LOGIN_LIMIT = 5
LOGIN_WINDOW_SECONDS = 15 * 60


class SecureAdminSite(admin.AdminSite):
    """Django's data admin, limited to active admin-role staff, with rate-limited sign-in."""

    site_header = "COI Network data admin"
    site_title = "COI Network data admin"

    def has_permission(self, request):
        user = request.user
        return user.is_active and user.is_staff and getattr(user, "role", "") == "admin"

    def login(self, request, extra_context=None):
        if request.method == "POST" and not hit("admin-login", client_ip(request), LOGIN_LIMIT, LOGIN_WINDOW_SECONDS):
            return HttpResponse("Too many sign-in attempts. Try again in 15 minutes.", status=429)
        return super().login(request, extra_context)
