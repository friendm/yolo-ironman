"""Sentry error reporting, server-side only (no browser script, so the CSP stays strict).

This app holds phone numbers, login codes, and insurance documents, so events carry
no personal data: no request bodies, cookies, IPs, or stack-frame variables.
"""

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

# Log lines that can contain phone numbers or login codes (see notifications.services).
PRIVATE_LOG_PREFIXES = ("SMS to ",)


def before_breadcrumb(crumb, hint):
    message = crumb.get("message") or ""
    if crumb.get("category") != "django.db.backends" and message.startswith(PRIVATE_LOG_PREFIXES):
        return None
    return crumb


def before_send(event, hint):
    request = event.get("request") or {}
    for key in ("data", "cookies", "query_string"):
        request.pop(key, None)
    headers = request.get("headers") or {}
    for key in list(headers):
        if key.lower() in ("cookie", "authorization", "x-twilio-signature", "x-forwarded-for"):
            headers.pop(key)
    return event


def init(dsn, *, environment, release=None, traces_sample_rate=0.0):
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        before_send=before_send,
        before_breadcrumb=before_breadcrumb,
        # Worker task failures are logged by Django-Q at ERROR level; report those as events.
        integrations=[DjangoIntegration(), LoggingIntegration(event_level="ERROR")],
    )
