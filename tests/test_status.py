"""The red / yellow / green rule, exactly as specified."""

from datetime import timedelta

import pytest

from documents.models import Document
from events.services import join_event
from events.status import evaluate
from tests.conftest import complete_vendor, make_doc, make_event

pytestmark = pytest.mark.django_db


@pytest.fixture
def event(org, today):
    return make_event(org, today + timedelta(days=10), today + timedelta(days=11))


def test_green_when_everything_verified_and_meets_minimums(vendor, types, event):
    complete_vendor(vendor, types)
    result = evaluate(event, vendor)
    assert result.color == "green" and result.reasons == []


def test_red_when_required_document_missing(vendor, types, event):
    make_doc(vendor, types["coi"])
    result = evaluate(event, vendor)
    assert result.color == "red"
    assert "Health permit is missing" in result.reasons
    assert "Fire inspection is missing" in result.reasons


def test_business_license_is_optional_by_default(vendor, types, event):
    for key in ("coi", "health_permit", "fire_inspection"):
        make_doc(vendor, types[key])
    assert evaluate(event, vendor).color == "green"


def test_red_when_rejected(vendor, types, event):
    docs = complete_vendor(vendor, types)
    docs["health_permit"].status = Document.Status.REJECTED
    docs["health_permit"].rejection_reason = "Photo is blurry"
    docs["health_permit"].save()
    result = evaluate(event, vendor)
    assert result.color == "red"
    assert "Health permit was rejected: Photo is blurry" in result.reasons


def test_red_when_expiring_before_event_ends(vendor, types, event):
    complete_vendor(vendor, types)
    make_doc(vendor, types["fire_inspection"], expires=event.end_date - timedelta(days=1))
    result = evaluate(event, vendor)
    assert result.color == "red"
    assert any("Fire inspection expires" in r and "before the event ends" in r for r in result.reasons)


def test_red_when_marked_expired(vendor, types, event):
    complete_vendor(vendor, types)
    make_doc(vendor, types["coi"], status=Document.Status.EXPIRED)
    assert evaluate(event, vendor).color == "red"


def test_red_when_below_gl_minimums(vendor, types, event):
    complete_vendor(vendor, types, gl=(500_000, 1_000_000))
    result = evaluate(event, vendor)
    assert result.color == "red"
    assert "General liability per occurrence is $500,000, below the $1,000,000 minimum" in result.reasons
    assert "General liability aggregate is $1,000,000, below the $2,000,000 minimum" in result.reasons


def test_red_when_food_truck_has_no_auto_liability(vendor, types, event):
    complete_vendor(vendor, types, auto=None)
    assert evaluate(event, vendor).color == "red"


def test_auto_liability_only_required_for_food_trucks(types, event):
    from tests.conftest import make_vendor

    rentals = make_vendor("+14045550141", "Tents Inc", vendor_type="rentals")
    complete_vendor(rentals, types, auto=None)
    assert evaluate(event, rentals).color == "green"


def test_red_when_liquor_required_and_missing(vendor, types, event):
    event.requirement.require_liquor = True
    event.requirement.save()
    complete_vendor(vendor, types)
    assert "Liquor liability is required and is not on the COI" in evaluate(event, vendor).reasons


def test_yellow_when_pending_verification(vendor, types, event):
    complete_vendor(vendor, types)
    make_doc(vendor, types["health_permit"], status=Document.Status.PENDING)
    result = evaluate(event, vendor)
    assert result.color == "yellow"
    assert result.reasons == ["Health permit is pending verification"]


def test_yellow_when_expiring_within_14_days_after_event(vendor, types, event):
    complete_vendor(vendor, types)
    make_doc(vendor, types["coi"], expires=event.end_date + timedelta(days=14))
    result = evaluate(event, vendor)
    assert result.color == "yellow"
    assert "within 14 days after the event" in result.reasons[0]


def test_green_when_expiring_15_days_after_event(vendor, types, event):
    complete_vendor(vendor, types)
    make_doc(vendor, types["coi"], expires=event.end_date + timedelta(days=15))
    assert evaluate(event, vendor).color == "green"


def test_draft_uploads_count_as_missing(vendor, types, event):
    complete_vendor(vendor, types)
    make_doc(vendor, types["coi"], status=Document.Status.DRAFT)
    # The draft is newer but not submitted, so the verified COI still counts.
    assert evaluate(event, vendor).color == "green"


def test_red_beats_yellow(vendor, types, event):
    docs = complete_vendor(vendor, types)
    docs["coi"].status = Document.Status.PENDING
    docs["coi"].save()
    docs["health_permit"].delete()
    assert evaluate(event, vendor).color == "red"


def test_standing_list_evaluates_against_today(vendor, types, org, today):
    from events.models import Event
    from events.services import ensure_requirement

    standing = Event.objects.create(organization=org, name="Taproom", is_standing=True)
    ensure_requirement(standing)
    complete_vendor(vendor, types)
    make_doc(vendor, types["coi"], expires=today + timedelta(days=20))
    assert evaluate(standing, vendor).color == "green"
    make_doc(vendor, types["coi"], expires=today + timedelta(days=10))
    assert evaluate(standing, vendor).color == "yellow"


def test_computed_status_recalculated_when_requirements_change(client, vendor, types, event):
    from tests.conftest import login

    complete_vendor(vendor, types, gl=(1_000_000, 2_000_000))
    link = join_event(vendor, event)
    assert link.computed_status == "green"
    login(client, event.organization.owner_user)
    data = {
        "event-name": event.name,
        "event-start_date": event.start_date,
        "event-end_date": event.end_date,
        "event-location_name": "",
        "event-address": "",
        "event-status": "open",
        "req-required_document_types": [types["coi"].id],
        "req-min_gl_per_occurrence": "2,000,000",
        "req-min_gl_aggregate": "2000000",
        "req-require_auto": "on",
        "req-additional_insured_text": "",
    }
    response = client.post(f"/org/events/{event.id}/edit", data)
    assert response.status_code == 302, response.content
    link.refresh_from_db()
    assert link.computed_status == "red"
