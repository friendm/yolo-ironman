import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db  # the shared cache-clearing fixture uses the database cache

ROOT = Path(__file__).resolve().parent.parent


def test_healthz_needs_no_login_or_database(client, django_assert_num_queries):
    with django_assert_num_queries(0):
        response = client.get(reverse("healthz"))
    assert response.status_code == 200 and response.content == b"ok"


def load_settings(**env):
    """Import production settings in a fresh interpreter with the given environment."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("RAILWAY_", "DJANGO_", "SITE_URL"))}
    clean.update({"DJANGO_SECRET_KEY": "x", "DJANGO_DEBUG": "0", **env})
    code = (
        "import json, config.settings as s; print(json.dumps({'hosts': s.ALLOWED_HOSTS, "
        "'csrf': s.CSRF_TRUSTED_ORIGINS, 'site': s.SITE_URL, 'exempt': s.SECURE_REDIRECT_EXEMPT, "
        "'admin': s.DJANGO_ADMIN_URL}))"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=clean, capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(out.stderr.strip().splitlines()[-1])
    return json.loads(out.stdout)


def test_railway_domain_and_healthcheck_host_are_allowed():
    s = load_settings(
        RAILWAY_PUBLIC_DOMAIN="coi-web.up.railway.app", RAILWAY_ENVIRONMENT_NAME="production", SITE_URL=""
    )
    assert "coi-web.up.railway.app" in s["hosts"] and "healthcheck.railway.app" in s["hosts"]
    assert "https://coi-web.up.railway.app" in s["csrf"]
    assert s["site"] == "https://coi-web.up.railway.app"
    assert s["exempt"] == ["^healthz$"]


def test_explicit_site_url_wins_and_nothing_railway_specific_off_railway():
    s = load_settings(SITE_URL="https://app.example.com/", DJANGO_ALLOWED_HOSTS="app.example.com")
    assert s["site"] == "https://app.example.com"
    assert s["hosts"] == ["app.example.com"]
