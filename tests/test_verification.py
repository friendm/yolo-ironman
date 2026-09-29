import pytest
from django.urls import reverse

from documents.models import Document
from notifications.models import Notification
from ops.models import AuditLog
from tests.conftest import complete_vendor, login, make_doc

pytestmark = pytest.mark.django_db


@pytest.fixture
def review_post(client, django_capture_on_commit_callbacks):
    """Post a review decision. SMS go out after commit, so those callbacks run too."""

    def post(doc, **extra):
        data = {"f-expiration_date": "2027-06-30", "decision": "verify", "method": "agent_email", "notes": ""}
        if doc.document_type.key == "coi":
            data.update({"f-gl_per_occurrence": "1000000", "f-gl_aggregate": "2000000", "f-auto_liability": "1000000"})
        data.update(extra)
        with django_capture_on_commit_callbacks(execute=True):
            return client.post(reverse("ops:review", args=[doc.id]), data)

    return post


def test_verifying_updates_vendor_home_within_one_refresh(client, vendor, types, admin_user, review_post):
    docs = complete_vendor(vendor, types)
    pending = make_doc(vendor, types["health_permit"], status=Document.Status.PENDING)
    login(client, vendor.owner_user)
    assert b"1 document pending" in client.get(reverse("vendors:home")).content
    client.logout()
    login(client, admin_user)
    response = review_post(pending)
    assert response.status_code == 302
    pending.refresh_from_db()
    assert pending.status == "verified" and pending.verification_method == "agent_email"
    assert pending.verified_by == admin_user
    docs["health_permit"].refresh_from_db()
    assert docs["health_permit"].superseded_by == pending
    client.logout()
    login(client, vendor.owner_user)
    assert b"Verified" in client.get(reverse("vendors:home")).content
    assert Notification.objects.filter(template="document_verified", user=vendor.owner_user).count() == 1
    assert AuditLog.objects.filter(action="document_verify", entity_id=pending.id).exists()


def test_verify_requires_method(client, vendor, types, admin_user, review_post):
    doc = make_doc(vendor, types["coi"], status=Document.Status.PENDING)
    login(client, admin_user)
    response = review_post(doc, method="")
    assert response.status_code == 200 and b"Pick how you verified" in response.content


def test_reject_texts_vendor_with_reason_and_reupload_link(client, vendor, types, admin_user, review_post):
    doc = make_doc(vendor, types["fire_inspection"], status=Document.Status.PENDING)
    login(client, admin_user)
    response = review_post(doc, decision="reject", reason="The inspection date is cut off")
    assert response.status_code == 302
    doc.refresh_from_db()
    assert doc.status == "rejected"
    sms = Notification.objects.get(template="document_rejected")
    assert "The inspection date is cut off." in sms.body
    assert "/vendor/documents/fire_inspection/upload" in sms.body


def test_queue_orders_by_soonest_event_then_oldest(client, types, admin_user, org, today):
    from datetime import timedelta

    from django.utils import timezone

    from events.services import join_event
    from tests.conftest import make_event, make_vendor

    a = make_vendor("+14045550151", "A")
    b = make_vendor("+14045550152", "B")
    c = make_vendor("+14045550153", "C")
    old = make_doc(a, types["coi"], status="pending")
    Document.objects.filter(pk=old.pk).update(submitted_at=timezone.now() - timedelta(days=3))
    make_doc(b, types["coi"], status="pending")
    soon = make_doc(c, types["coi"], status="pending")
    join_event(c, make_event(org, today + timedelta(days=2)))
    login(client, admin_user)
    names = [d.vendor.business_name for d in client.get(reverse("ops:queue")).context["documents"]]
    assert names == ["C", "A", "B"]
    assert soon.vendor.business_name == "C"


def test_review_page_is_audited_and_flags_mismatches(client, vendor, types, admin_user):
    doc = make_doc(vendor, types["coi"], status=Document.Status.PENDING)
    doc.confirmed = {
        "insured_name": "Someone Else LLC",
        "effective_date": "2027-01-01",
        "expiration_date": "2026-01-01",
    }
    doc.save()
    login(client, admin_user)
    page = client.get(reverse("ops:review", args=[doc.id]))
    assert page.status_code == 200
    flags = page.context["flags"]
    assert any("differs from business name" in f for f in flags)
    assert any("before the effective date" in f for f in flags)
    assert AuditLog.objects.filter(action="document_view", entity_id=doc.id).exists()


def test_agent_verification_email(client, vendor, types, admin_user, mailoutbox):
    doc = make_doc(vendor, types["coi"], status=Document.Status.PENDING)
    login(client, admin_user)
    client.post(reverse("ops:agent_verify", args=[doc.id]))
    assert mailoutbox[0].to == ["agent@example.com"]
    assert "confirm" in mailoutbox[0].body


def test_ops_pages_render(client, admin_user, vendor, types):
    complete_vendor(vendor, types)
    login(client, admin_user)
    for name in (
        "ops:queue",
        "ops:expirations",
        "ops:directory",
        "ops:document_types",
        "ops:templates",
        "ops:audit",
        "ops:metrics",
    ):
        assert client.get(reverse(name)).status_code == 200, name
    assert client.get(reverse("ops:vendor_detail", args=[vendor.id])).status_code == 200
    assert client.get(reverse("ops:directory") + "?q=Test").status_code == 200
