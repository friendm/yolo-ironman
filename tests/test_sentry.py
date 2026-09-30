import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest
import sentry_sdk
from django.urls import reverse
from sentry_sdk.transport import Transport

from config import sentry

pytestmark = pytest.mark.django_db  # the shared cache-clearing fixture uses the database cache
ROOT = Path(__file__).resolve().parent.parent


class CaptureTransport(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type == "event":
                self.events.append(item.payload.json)


@pytest.fixture
def captured():
    transport = CaptureTransport()
    with mock.patch("sentry_sdk.init", wraps=sentry_sdk.init) as init:
        sentry.init("https://public@example.invalid/1", environment="test")
        # Re-run with the capturing transport but the same privacy options.
        options = init.call_args.kwargs
    sentry_sdk.init(**{**options, "transport": transport})
    yield transport.events
    sentry_sdk.init()  # no DSN: turn reporting back off for the other tests


def test_errors_are_reported_without_personal_data(client, vendor, captured):
    client.raise_request_exception = False
    client.post(reverse("accounts:login"), {"phone": vendor.owner_user.phone})
    client.cookies["tracker"] = "secret-cookie-value"
    with mock.patch("accounts.models.PhoneCode.verify", side_effect=RuntimeError("boom")):
        response = client.post(reverse("accounts:code"), {"code": "123456"})
    assert response.status_code == 500
    sentry_sdk.flush()
    assert len(captured) == 1
    event = captured[0]
    request = event.get("request", {})
    assert "data" not in request and "cookies" not in request
    assert not {k.lower() for k in request.get("headers", {})} & {"cookie", "x-forwarded-for"}
    frames = event["exception"]["values"][-1]["stacktrace"]["frames"]
    assert all("vars" not in frame for frame in frames)
    serialized = json.dumps(event)
    assert "123456" not in serialized and vendor.owner_user.phone not in serialized
    assert "secret-cookie-value" not in serialized and client.cookies["sessionid"].value not in serialized


def test_failed_background_tasks_are_reported(captured):
    import logging

    logging.getLogger("django-q").error("Failed 'documents.tasks.extract_document' (abc) - boom : Traceback ...")
    sentry_sdk.flush()
    assert any("extract_document" in json.dumps(e) for e in captured)


def test_sms_log_lines_never_become_breadcrumbs():
    assert sentry.before_breadcrumb({"message": "SMS to +14045550111: 123456 is your code"}, {}) is None
    crumb = {"message": "Processed task", "category": "django-q"}
    assert sentry.before_breadcrumb(crumb, {}) is crumb


def test_before_send_strips_request_details():
    event = {
        "request": {
            "url": "https://x/login/code",
            "data": {"code": "123456"},
            "cookies": {"sessionid": "s"},
            "query_string": "phone=4045550111",
            "headers": {"Cookie": "s", "User-Agent": "ua", "X-Twilio-Signature": "sig"},
        }
    }
    request = sentry.before_send(event, {})["request"]
    assert request == {"url": "https://x/login/code", "headers": {"User-Agent": "ua"}}


def run_settings(**env):
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("RAILWAY_", "DJANGO_", "SENTRY_"))}
    clean.update({"DJANGO_SECRET_KEY": "x", "DJANGO_DEBUG": "0", **env})
    code = (
        "import json, sentry_sdk, config.settings; o = sentry_sdk.get_client().options; "
        "print(json.dumps({'active': sentry_sdk.get_client().is_active(), 'env': o.get('environment'), "
        "'release': o.get('release'), 'pii': o.get('send_default_pii'), 'locals': o.get('include_local_variables'), "
        "'body': o.get('max_request_body_size')}))"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=clean, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_sentry_is_off_without_a_dsn():
    assert run_settings()["active"] is False


def test_sentry_uses_railway_environment_and_commit():
    s = run_settings(
        SENTRY_DSN="https://public@example.invalid/1",
        RAILWAY_ENVIRONMENT_NAME="production",
        RAILWAY_GIT_COMMIT_SHA="abc123",
    )
    assert s == {
        "active": True,
        "env": "production",
        "release": "abc123",
        "pii": False,
        "locals": False,
        "body": "never",
    }
