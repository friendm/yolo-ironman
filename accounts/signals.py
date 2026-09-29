"""Audit every sign-in, sign-out, and failed sign-in; keep admin sessions short."""

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from common.ratelimit import client_ip
from ops import audit

ADMIN_SESSION_SECONDS = 8 * 60 * 60


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    if getattr(user, "role", "") == "admin" and request is not None:
        request.session.set_expiry(ADMIN_SESSION_SECONDS)
    audit.record(user, "login", user, entity="user", ip=client_ip(request) if request else None, path=_path(request))


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        audit.record(user, "logout", user, entity="user", ip=client_ip(request) if request else None)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    # Django masks password-like keys; keep only the identifier that was tried.
    tried = credentials.get("username") or credentials.get("phone") or credentials.get("email")
    audit.record(
        None,
        "login_failed",
        entity="user",
        tried=tried,
        method="password",
        ip=client_ip(request) if request else None,
        path=_path(request),
    )


def _path(request):
    return getattr(request, "path", None)
