from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse


def role_required(*roles):
    """Require login plus one of the given roles (vendor, organizer, admin)."""

    def decorator(view):
        @login_required
        def wrapped(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        wrapped.__name__ = view.__name__
        wrapped.__doc__ = view.__doc__
        return wrapped

    return decorator


def healthz(request):
    """Liveness check for the hosting platform. No database access, no redirects."""
    return HttpResponse("ok", content_type="text/plain")
