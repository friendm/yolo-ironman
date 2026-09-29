from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import PhoneCode, User
from notifications.models import Notification

pytestmark = pytest.mark.django_db


def last_code():
    note = Notification.objects.filter(template="otp").order_by("-created_at").first()
    return note.payload["code"]


def test_new_vendor_logs_in_by_sms_and_lands_on_business_basics(client):
    response = client.post(reverse("accounts:vendor_start"), {"phone": "(404) 555-0199"})
    assert response.status_code == 302 and response.url == reverse("accounts:code")
    response = client.post(reverse("accounts:code"), {"code": last_code()})
    assert response.url == reverse("vendors:basics")
    user = User.objects.get(phone="+14045550199")
    assert user.role == "vendor"


def test_organizer_phone_login_lands_on_org_setup(client):
    client.get(reverse("accounts:org_start"))
    client.post(reverse("accounts:login"), {"phone": "4045550198"})
    response = client.post(reverse("accounts:code"), {"code": last_code()})
    assert response.url == reverse("events:org_setup")


def test_existing_roles_land_on_their_home(client, vendor, admin_user):
    from tests.conftest import make_organizer

    org = make_organizer()
    for user, target in [
        (vendor.owner_user, "vendors:home"),
        (admin_user, "ops:queue"),
        (org.owner_user, "events:org_home"),
    ]:
        client.logout()
        client.post(reverse("accounts:login"), {"phone": user.phone})
        response = client.post(reverse("accounts:code"), {"code": last_code()})
        assert response.url == reverse(target)


def test_codes_are_hashed_and_expire_after_ten_minutes():
    record, code = PhoneCode.issue("+14045550197")
    assert code not in record.code_hash
    record.expires_at = timezone.now() - timedelta(seconds=1)
    record.save()
    assert PhoneCode.verify("+14045550197", code) is False


def test_five_wrong_attempts_lock_the_code():
    _, code = PhoneCode.issue("+14045550196")
    for _ in range(5):
        assert PhoneCode.verify("+14045550196", "000000" if code != "000000" else "111111") is False
    assert PhoneCode.verify("+14045550196", code) is False


def test_code_works_once():
    _, code = PhoneCode.issue("+14045550195")
    assert PhoneCode.verify("+14045550195", code) is True
    assert PhoneCode.verify("+14045550195", code) is False


def test_otp_requests_are_rate_limited(client):
    for _ in range(3):
        client.post(reverse("accounts:vendor_start"), {"phone": "4045550194"})
    response = client.post(reverse("accounts:vendor_start"), {"phone": "4045550194"})
    assert response.status_code == 200
    assert b"Too many codes" in response.content
    assert Notification.objects.filter(template="otp").count() == 3


def test_magic_link_creates_organizer_and_works_once(client, mailoutbox):
    client.post(reverse("accounts:email_link"), {"email": "New@Example.com"})
    assert len(mailoutbox) == 1
    link = [line for line in mailoutbox[0].body.splitlines() if "/login/magic/" in line][0].strip()
    path = link.split("localhost:8000")[-1]
    response = client.get(path)
    assert response.url == reverse("events:org_setup")
    assert User.objects.get(email="new@example.com").role == "organizer"
    client.logout()
    response = client.get(path, follow=True)
    assert b"already used" in response.content


def test_email_password_login(client, org):
    org.owner_user.set_password("a-long-password-1")
    org.owner_user.save()
    response = client.post(
        reverse("accounts:email_login"), {"email": "org@example.com", "password": "a-long-password-1"}
    )
    assert response.url == reverse("events:org_home")


def test_logout_requires_post(client, vendor):
    client.force_login(vendor.owner_user)
    assert client.get(reverse("accounts:logout")).status_code == 405
    assert client.post(reverse("accounts:logout")).status_code == 302
