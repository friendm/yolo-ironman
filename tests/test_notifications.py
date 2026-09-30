from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse

from documents.models import Document
from notifications import jobs, services
from notifications.models import Notification
from tests.conftest import complete_vendor, make_doc

pytestmark = pytest.mark.django_db
EASTERN = ZoneInfo("America/New_York")


@pytest.fixture
def daytime():
    noon = datetime(2026, 9, 29, 12, 0, tzinfo=EASTERN)
    with mock.patch("notifications.services.in_quiet_hours", return_value=False):
        yield noon


def test_document_expiring_in_14_days_triggers_exactly_one_sms(vendor, types, today, daytime):
    complete_vendor(vendor, types)
    make_doc(vendor, types["health_permit"], expires=today + timedelta(days=14))
    jobs.daily()
    jobs.daily()
    sms = Notification.objects.filter(template="document_expiring")
    assert sms.count() == 1
    assert sms.get().status == "sent" and "Health permit expires" in sms.get().body


def test_reminders_at_30_14_and_3_days_only(vendor, types, today, daytime):
    for days in (30, 20, 3):
        make_doc(vendor, types["coi"], expires=today + timedelta(days=days))
    # Only the newest COI is current, so exactly one reminder applies (3 days).
    assert jobs.send_expiration_reminders(today) == 1
    make_doc(vendor, types["health_permit"], expires=today + timedelta(days=30))
    make_doc(vendor, types["fire_inspection"], expires=today + timedelta(days=20))
    assert jobs.send_expiration_reminders(today) == 1


def test_daily_job_marks_expired_and_recomputes(vendor, org, types, today, daytime):
    from events.services import join_event
    from tests.conftest import make_event

    docs = complete_vendor(vendor, types)
    event = make_event(org, today + timedelta(days=2))
    link = join_event(vendor, event)
    assert link.computed_status == "green"
    Document.objects.filter(pk=docs["fire_inspection"].pk).update(expiration_date=today - timedelta(days=1))
    result = jobs.daily()
    assert result["expired"] == 1
    link.refresh_from_db()
    assert link.computed_status == "red"


def test_quiet_hours_hold_sms_until_morning(vendor):
    night = datetime(2026, 9, 29, 22, 30, tzinfo=EASTERN)
    assert services.in_quiet_hours(night) and services.in_quiet_hours(night.replace(hour=7, minute=59))
    assert not services.in_quiet_hours(night.replace(hour=8, minute=0))
    with mock.patch("notifications.services.in_quiet_hours", return_value=True):
        note = services.send_sms(vendor.owner_user, "document_verified", {"document": "coi", "link": "x"})
    assert note.status == "queued"
    with mock.patch("notifications.services.in_quiet_hours", return_value=False):
        assert services.flush_queued_sms() == 1
    note.refresh_from_db()
    assert note.status == "sent"


def test_login_codes_ignore_quiet_hours(vendor):
    with mock.patch("notifications.services.in_quiet_hours", return_value=True):
        note = services.send_sms(None, "otp", {"code": "123456"}, phone="+14045550111", transactional=True)
    assert note.status == "sent"


def test_stop_opts_out_and_start_opts_back_in(client, vendor, settings, daytime):
    settings.DEBUG = True
    client.post(reverse("notifications:twilio_inbound"), {"From": "+14045550111", "Body": "STOP"})
    vendor.owner_user.refresh_from_db()
    assert vendor.owner_user.sms_opt_out
    note = services.send_sms(vendor.owner_user, "document_verified", {"document": "coi", "link": "x"})
    assert note.status == "skipped"
    client.post(reverse("notifications:twilio_inbound"), {"From": "+14045550111", "Body": "start"})
    vendor.owner_user.refresh_from_db()
    assert not vendor.owner_user.sms_opt_out


def test_twilio_webhook_rejects_unsigned_requests_in_production(client, settings):
    settings.DEBUG = False
    settings.TWILIO_AUTH_TOKEN = "secret"
    response = client.post(reverse("notifications:twilio_inbound"), {"From": "+14045550111", "Body": "STOP"})
    assert response.status_code == 403


def test_hourly_digest_emails_admin_once_per_hour(vendor, types, mailoutbox, daytime):
    make_doc(vendor, types["coi"], status="pending")
    jobs.hourly()
    jobs.hourly()
    assert len(mailoutbox) == 1 and "1 documents waiting" in mailoutbox[0].subject


def test_every_message_is_logged(vendor, daytime):
    services.send_sms(vendor.owner_user, "document_verified", {"document": "coi", "link": "https://x"})
    services.send_email(None, "admin_digest", {"count": 1, "link": "https://x"}, email="a@example.com")
    assert Notification.objects.count() == 2


def test_setup_schedules_command():
    from django.core.management import call_command
    from django_q.models import Schedule

    call_command("setup_schedules")
    call_command("setup_schedules")
    assert set(Schedule.objects.values_list("name", flat=True)) == {"daily-7am-eastern", "hourly"}
    daily = Schedule.objects.get(name="daily-7am-eastern")
    assert daily.next_run.astimezone(EASTERN).hour == 7


@pytest.mark.parametrize("start", [datetime(2026, 10, 30, 7, 0), datetime(2027, 3, 12, 7, 0)])
def test_daily_job_stays_at_7am_eastern_across_daylight_saving_changes(start):
    from django_q.models import Schedule

    schedule = Schedule(name="t", func="notifications.jobs.daily", schedule_type=Schedule.DAILY)
    run = start.replace(tzinfo=EASTERN)
    for _ in range(5):  # crosses Nov 1, 2026 (clocks back) and Mar 14, 2027 (clocks forward)
        run = schedule.calculate_next_run(run)
        assert run.astimezone(EASTERN).hour == 7
