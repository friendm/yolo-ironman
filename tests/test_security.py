import importlib

import pytest
from django.test import override_settings
from django.urls import clear_url_caches, reverse

from accounts.models import User
from common.checks import admin_url_check
from notifications.models import Notification
from ops.models import AuditLog
from tests.test_deploy import load_settings

pytestmark = pytest.mark.django_db
ADMIN = "/test-secret-admin/"


@pytest.fixture
def staff_admin(db):
    return User.objects.create_user(
        phone="+14045550900", password="a-long-admin-password", role=User.Role.ADMIN, is_staff=True
    )


def test_data_admin_only_at_secret_path(client):
    assert client.get("/django-admin/").status_code == 404
    assert client.get("/admin/").status_code == 404
    response = client.get(ADMIN)
    assert response.status_code == 302 and "/test-secret-admin/login/" in response.url


def test_data_admin_switched_off_without_a_path(client, settings):
    import config.urls

    settings.DJANGO_ADMIN_URL = ""
    clear_url_caches()
    importlib.reload(config.urls)
    try:
        assert client.get(ADMIN).status_code == 404
    finally:
        settings.DJANGO_ADMIN_URL = "test-secret-admin/"
        clear_url_caches()
        importlib.reload(config.urls)


def test_only_admin_role_staff_can_use_data_admin(client, staff_admin):
    organizer_staff = User.objects.create_user(phone="+14045550901", role=User.Role.ORGANIZER, is_staff=True)
    client.force_login(organizer_staff)
    assert client.get(ADMIN).status_code == 302
    client.force_login(staff_admin)
    assert client.get(ADMIN).status_code == 200


def test_data_admin_login_is_rate_limited_and_failures_audited(client, staff_admin):
    for _ in range(5):
        response = client.post(ADMIN + "login/", {"username": "+14045550900", "password": "wrong-password"})
        assert response.status_code == 200
    response = client.post(ADMIN + "login/", {"username": "+14045550900", "password": "a-long-admin-password"})
    assert response.status_code == 429
    failures = AuditLog.objects.filter(action="login_failed")
    assert failures.count() == 5 and failures.first().details["tried"] == "+14045550900"
    assert "wrong-password" not in str(list(failures.values_list("details", flat=True)))


def test_successful_admin_login_is_audited_with_short_session(client, staff_admin):
    response = client.post(ADMIN + "login/", {"username": "+14045550900", "password": "a-long-admin-password"})
    assert response.status_code == 302
    assert AuditLog.objects.filter(action="login", actor_user=staff_admin).exists()
    assert client.session.get_expiry_age() == 8 * 60 * 60


def test_sms_login_audits_failures_and_success(client, vendor):
    client.post(reverse("accounts:login"), {"phone": vendor.owner_user.phone})
    code = Notification.objects.get(template="otp").payload["code"]
    wrong = f"{(int(code) + 1) % 1_000_000:06d}"
    client.post(reverse("accounts:code"), {"code": wrong})
    failed = AuditLog.objects.get(action="login_failed")
    assert failed.details["method"] == "sms_code" and failed.details["tried"] == vendor.owner_user.phone
    client.post(reverse("accounts:code"), {"code": code})
    assert AuditLog.objects.filter(action="login", actor_user=vendor.owner_user).exists()
    assert client.session.get_expiry_age() == 30 * 24 * 60 * 60


def test_logout_is_audited(client, vendor):
    client.force_login(vendor.owner_user)
    client.post(reverse("accounts:logout"))
    assert AuditLog.objects.filter(action="logout", actor_user=vendor.owner_user).exists()


def test_email_password_failure_is_audited(client):
    client.post(reverse("accounts:email_login"), {"email": "nobody@example.com", "password": "nope-nope-nope"})
    assert AuditLog.objects.get(action="login_failed").details["method"] == "email_password"


def test_security_headers(client):
    response = client.get("/")
    assert "camera=()" in response["Permissions-Policy"]
    assert "script-src 'self'" in response["Content-Security-Policy"]
    assert response["X-Frame-Options"] == "DENY"


@pytest.mark.parametrize(
    "path,warns",
    [("admin/", True), ("django-admin/", True), ("short/", True), ("k3v9-Qz_x8PmL2wA/", False), ("", False)],
)
def test_deploy_check_flags_guessable_admin_path(path, warns):
    with override_settings(DJANGO_ADMIN_URL=path):
        assert bool(admin_url_check(None)) is warns


def test_production_admin_is_off_unless_configured():
    assert load_settings(SITE_URL="")["admin"] == ""
    assert load_settings(DJANGO_ADMIN_URL="/ops-data-7f3k2/")["admin"] == "ops-data-7f3k2/"
    with pytest.raises(RuntimeError, match="DJANGO_ADMIN_URL"):
        load_settings(DJANGO_ADMIN_URL="bad path?")
