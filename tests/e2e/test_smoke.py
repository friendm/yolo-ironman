from datetime import timedelta

import pytest
from django.utils import timezone

from tests.e2e.conftest import assert_fits_phone, last_code

pytestmark = [pytest.mark.e2e]


def sign_in_by_phone(page, base, start_path, phone):
    page.goto(base + start_path)
    page.fill("#id_phone", phone)
    page.click("#main button[type=submit]")
    page.fill("#id_code", last_code(phone))
    page.click("#main button[type=submit]")


def fill_basics(page, name):
    page.fill("#id_business_name", name)
    page.fill("#id_service_area", "Metro Atlanta")
    page.fill("#id_agent_email", "agent@example.com")
    page.click("#main button[type=submit]")


def test_vendor_sign_up_and_first_document(page, live_server, seeded, sample_png):
    sign_in_by_phone(page, live_server.url, "/vendor/start", "+14045550301")
    assert page.url.endswith("/vendor/basics")
    assert_fits_phone(page)
    fill_basics(page, "Smoke Test Tacos")
    assert page.url.endswith("/vendor/documents")
    assert_fits_phone(page)
    page.click("a[href='/vendor/documents/health_permit/upload']")
    page.set_input_files("#id_file", str(sample_png))
    page.click("#main button[type=submit]")
    assert "/confirm" in page.url
    assert page.get_by_text("fill in the details below").is_visible()
    page.fill("#id_expiration_date", "2027-06-30")
    page.click("#main button[type=submit]")
    assert page.url.endswith("/vendor/documents")
    assert page.get_by_text("submitted").first.is_visible()
    page.goto(live_server.url + "/vendor/")
    assert page.get_by_text("1 document pending").is_visible()
    assert_fits_phone(page)


def test_brand_new_vendor_joins_event_from_invite_link(page, live_server, seeded):
    from events.models import Event, EventVendor
    from events.services import ensure_requirement
    from tests.conftest import make_organizer

    org = make_organizer("+14045550311", "smoke-org@example.com", name="Smoke Fest Org")
    start = timezone.localdate() + timedelta(days=9)
    event = Event.objects.create(
        organization=org, name="Smoke Fest", start_date=start, end_date=start, invite_code="SMOKE1"
    )
    ensure_requirement(event)

    page.goto(live_server.url + "/i/SMOKE1")
    assert page.get_by_text("Smoke Fest Org invited you to Smoke Fest").is_visible()
    assert_fits_phone(page)
    page.click("text=Get started")
    page.fill("#id_phone", "+14045550302")
    page.click("#main button[type=submit]")
    page.fill("#id_code", last_code("+14045550302"))
    page.click("#main button[type=submit]")
    fill_basics(page, "Invite Flow BBQ")
    assert "/vendor/join/SMOKE1" in page.url
    assert page.get_by_text("Certificate of insurance is missing").is_visible()
    assert_fits_phone(page)
    page.click("button:has-text('Join Smoke Fest')")
    assert f"/vendor/events/{event.id}" in page.url
    assert EventVendor.objects.get(event=event).status == "joined"
    assert_fits_phone(page)


def test_organizer_dashboard(page, live_server, seeded):
    from events.services import join_event
    from tests.conftest import complete_vendor, make_event, make_organizer, make_vendor

    org = make_organizer("+14045550321", "dash@example.com", name="Dash Org")
    org.owner_user.set_password("a-long-password-1")
    org.owner_user.save()
    event = make_event(org, timezone.localdate() + timedelta(days=4), name="Dashboard Fest")
    from documents.models import DocumentType

    types = {t.key: t for t in DocumentType.objects.all()}
    ready = make_vendor("+14045550331", "Ready Truck")
    complete_vendor(ready, types)
    join_event(ready, event)
    join_event(make_vendor("+14045550332", "Missing Truck"), event)

    page.goto(live_server.url + "/login/email")
    page.fill("#id_email", "dash@example.com")
    page.fill("#id_password", "a-long-password-1")
    page.click("#main button[type=submit]")
    assert page.url.endswith("/org")
    page.click("text=Dashboard Fest")
    assert page.get_by_text("Ready Truck").is_visible()
    assert page.get_by_text("Certificate of insurance is missing").is_visible()
    assert_fits_phone(page)
    page.click("a[href='?status=red']")
    assert page.get_by_text("Missing Truck").is_visible()
    assert page.get_by_text("Ready Truck").count() == 0
    page.goto(live_server.url + f"/org/events/{event.id}")
    page.click("text=Ready Truck")
    assert page.get_by_text("Documents for this event").is_visible()
    assert_fits_phone(page)
