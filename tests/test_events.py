import csv
import io
import zipfile
from datetime import timedelta

import pytest
from django.urls import reverse

from events.models import Event, EventVendor
from notifications.models import Notification
from tests.conftest import complete_vendor, login, make_doc, make_event, make_vendor

pytestmark = pytest.mark.django_db


def test_create_event_uses_default_requirements(client, org, types, today):
    login(client, org.owner_user)
    page = client.get(reverse("events:event_new"))
    initial = page.context["req_form"].initial
    assert initial["min_gl_per_occurrence"] == 1_000_000 and initial["min_gl_aggregate"] == 2_000_000
    assert initial["require_auto"] is True
    assert {t.key for t in initial["required_document_types"]} == {"coi", "health_permit", "fire_inspection"}
    data = {
        "event-name": "Summer Fest",
        "event-start_date": today + timedelta(days=30),
        "event-end_date": today + timedelta(days=31),
        "event-location_name": "Park",
        "event-address": "",
        "event-status": "open",
        "req-required_document_types": [types[k].id for k in ("coi", "health_permit", "fire_inspection")],
        "req-min_gl_per_occurrence": "1,000,000",
        "req-min_gl_aggregate": "2,000,000",
        "req-require_auto": "on",
        "req-additional_insured_text": "Summer Fest LLC",
    }
    response = client.post(reverse("events:event_new"), data)
    event = Event.objects.get(name="Summer Fest")
    assert response.url == reverse("events:org_invite", args=[event.id])
    assert event.requirement.additional_insured_text == "Summer Fest LLC"
    assert len(event.invite_code) == 6
    invite_page = client.get(response.url).content.decode()
    assert event.invite_code in invite_page and f"/i/{event.invite_code}" in invite_page


def test_brand_new_vendor_joins_from_invite_link_in_one_flow(client, org, types, today):
    event = make_event(org, today + timedelta(days=5), invite_code="JOINME")
    response = client.get(reverse("events:invite", args=["joinme"]))
    assert response.status_code == 200 and b"invited you to" in response.content
    response = client.get(reverse("accounts:vendor_start") + "?invite=JOINME")
    assert b"JOINME" in response.content
    client.post(reverse("accounts:vendor_start") + "?invite=JOINME", {"phone": "4045550177"})
    code = Notification.objects.get(template="otp").payload["code"]
    response = client.post(reverse("accounts:code"), {"code": code})
    assert response.url == reverse("vendors:basics")
    response = client.post(
        reverse("vendors:basics"),
        {
            "business_name": "Brand New Tacos",
            "vendor_type": "food_truck",
            "service_area": "ATL",
            "description": "",
            "agent_name": "",
            "agent_email": "",
            "agent_phone": "",
            "insurer_name": "",
        },
    )
    assert response.url == reverse("events:join_code", args=["JOINME"])
    page = client.get(response.url)
    assert b"Certificate of insurance is missing" in page.content
    response = client.post(response.url)
    assert response.url == reverse("events:vendor_event", args=[event.id])
    link = EventVendor.objects.get(event=event)
    assert link.status == "joined" and link.vendor.business_name == "Brand New Tacos"
    assert link.computed_status == "red"


def test_join_by_code(client, vendor, org, types, today):
    event = make_event(org, today + timedelta(days=5), invite_code="CODE42")
    complete_vendor(vendor, types)
    login(client, vendor.owner_user)
    response = client.post(reverse("events:join"), {"code": " code42 "})
    assert response.url == reverse("events:join_code", args=["CODE42"])
    client.post(response.url)
    assert EventVendor.objects.get(event=event, vendor=vendor).computed_status == "green"


def test_dashboard_counts_filters_and_detail(client, org, types, today):
    from events.services import invite_vendor, join_event

    event = make_event(org, today + timedelta(days=3))
    green, yellow, red, invited = (make_vendor(f"+1404555016{i}", n) for i, n in enumerate(["G", "Y", "R", "I"]))
    complete_vendor(green, types)
    complete_vendor(yellow, types)
    make_doc(yellow, types["health_permit"], status="pending")
    for v in (green, yellow, red):
        join_event(v, event)
    invite_vendor(event, invited)
    login(client, org.owner_user)
    page = client.get(reverse("events:org_event", args=[event.id]))
    assert page.context["counts"] == {"green": 1, "yellow": 1, "red": 1, "invited": 1}
    filtered = client.get(reverse("events:org_event", args=[event.id]) + "?status=red")
    assert [link.vendor.business_name for link in filtered.context["links"]] == ["R"]
    assert client.get(reverse("events:org_home")).status_code == 200


def test_bulk_reminder_once_per_24_hours(client, org, types, today):
    from events.services import join_event

    event = make_event(org, today + timedelta(days=3))
    red = make_vendor("+14045550171", "Red Truck")
    green = make_vendor("+14045550172", "Green Truck")
    complete_vendor(green, types)
    join_event(red, event)
    join_event(green, event)
    login(client, org.owner_user)
    client.post(reverse("events:org_remind", args=[event.id]))
    sms = Notification.objects.filter(template="bulk_reminder")
    assert sms.count() == 1 and sms.get().user == red.owner_user
    assert "Certificate of insurance is missing" in sms.get().body
    client.post(reverse("events:org_remind", args=[event.id]))
    assert Notification.objects.filter(template="bulk_reminder").count() == 1


def test_direct_invite_texts_vendor(client, org, vendor, today):
    event = make_event(org, today + timedelta(days=3))
    login(client, org.owner_user)
    results = client.get(reverse("events:org_invite", args=[event.id]) + "?q=test").context["results"]
    assert list(results) == [vendor]
    client.post(reverse("events:org_invite_vendor", args=[event.id]), {"vendor_id": vendor.id})
    assert EventVendor.objects.get(event=event, vendor=vendor).status == "invited"
    assert f"/i/{event.invite_code}" in Notification.objects.get(template="event_invite").body


def test_exports(client, org, vendor, types, today):
    from events.services import join_event
    from ops.models import AuditLog

    event = make_event(org, today + timedelta(days=3), name="Export Fest")
    complete_vendor(vendor, types)
    join_event(vendor, event)
    login(client, org.owner_user)
    response = client.get(reverse("events:export_csv", args=[event.id]))
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0][0] == "Vendor" and rows[1][0] == "Test Truck" and rows[1][3] == "Green"
    response = client.get(reverse("events:export_zip", args=[event.id]))
    names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    assert sorted(names) == ["test-truck/coi.png", "test-truck/fire_inspection.png", "test-truck/health_permit.png"]
    assert AuditLog.objects.filter(action="document_download", details__via="event_zip").count() == 3


def test_organizer_is_emailed_when_vendor_turns_red_within_7_days(org, vendor, types, today, mailoutbox):
    from events.services import join_event, recompute_for_vendor

    event = make_event(org, today + timedelta(days=5))
    docs = complete_vendor(vendor, types)
    join_event(vendor, event)
    docs["coi"].status = "rejected"
    docs["coi"].save()
    recompute_for_vendor(vendor)
    assert len(mailoutbox) == 1 and "Test Truck is not ready" in mailoutbox[0].subject


def test_vendor_event_page_and_home_list(client, vendor, org, types, today):
    from events.services import join_event

    event = make_event(org, today + timedelta(days=3), name="Visible Fest")
    join_event(vendor, event)
    login(client, vendor.owner_user)
    assert b"Visible Fest" in client.get(reverse("vendors:home")).content
    assert client.get(reverse("events:vendor_event", args=[event.id])).status_code == 200
