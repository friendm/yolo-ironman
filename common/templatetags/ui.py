from django import template
from django.urls import reverse
from django.utils.safestring import mark_safe

register = template.Library()

DISCLAIMER = (
    "Verified means our team confirmed this document with the issuer or agent on the date shown. "
    "It is not insurance advice and does not guarantee coverage. Confirm coverage terms with the insurer."
)

LABELS = {
    "verified": "Verified",
    "pending": "Pending",
    "missing": "Missing",
    "expiring": "Expiring",
    "expired": "Expired",
    "rejected": "Rejected",
    "draft": "Not submitted",
    "green": "Ready",
    "yellow": "Pending",
    "red": "Action needed",
    "invited": "Invited",
}


@register.filter
def pill_label(state):
    return LABELS.get(state, str(state).title())


@register.inclusion_tag("includes/pill.html")
def pill(state):
    return {"state": state, "disclaimer": DISCLAIMER}


@register.simple_tag
def disclaimer():
    return DISCLAIMER


@register.filter
def dollars(value):
    if value in (None, ""):
        return "—"
    try:
        return f"${int(value):,}"
    except (TypeError, ValueError):
        return value


@register.simple_tag(takes_context=True)
def nav_current(context, name, *args):
    """aria-current for sidebar links: exact match on the resolved URL prefix."""
    request = context.get("request")
    if request is None:
        return ""
    url = reverse(name, args=args)
    path = request.path
    if url == path or (url not in ("/vendor/", "/org", "/ops/") and path.startswith(url)):
        return mark_safe('aria-current="page"')
    return ""


@register.filter
def get(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None
