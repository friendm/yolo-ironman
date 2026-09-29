from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from documents.models import Document, ShareLink
from events.models import AICertificateRequest
from ops.models import AuditLog
from tests.conftest import complete_vendor, login, make_doc, make_event, png_upload

pytestmark = pytest.mark.django_db


def test_share_packet_link_is_read_only_audited_and_expires(client, vendor, types):
    docs = complete_vendor(vendor, types)
    make_doc(vendor, types["business_license"], status="pending")  # replaces the verified license
    login(client, vendor.owner_user)
    client.post(reverse("vendors:share"))
    link = ShareLink.objects.get()
    assert (link.expires_at - timezone.now()).days == 13
    client.logout()
    page = client.get(reverse("documents:share", args=[link.token]))
    assert page.status_code == 200
    shown = {d.document_type.key for d in page.context["documents"]}
    assert shown == {"coi", "health_permit", "fire_inspection"}
    response = client.get(reverse("documents:share_document", args=[link.token, docs["coi"].id]))
    assert response.status_code == 302
    assert AuditLog.objects.filter(action="share_view").count() == 1
    assert AuditLog.objects.filter(action="document_view", entity_id=docs["coi"].id, details__via="share_link").exists()
    signed = client.get(response.url)
    assert signed.status_code == 200 and signed["Content-Type"] == "image/png"
    link.expires_at = timezone.now() - timedelta(minutes=1)
    link.save()
    assert client.get(reverse("documents:share", args=[link.token])).status_code == 410


def test_share_links_are_rate_limited(client, vendor):
    link = ShareLink.objects.create(vendor=vendor, expires_at=timezone.now() + timedelta(days=1))
    for _ in range(60):
        client.get(reverse("documents:share", args=[link.token]))
    assert client.get(reverse("documents:share", args=[link.token])).status_code == 429


def test_signed_file_links_expire(client, vendor, types, settings):
    from django.core import signing

    doc = make_doc(vendor, types["coi"])
    login(client, vendor.owner_user)
    url = client.get(reverse("documents:view", args=[doc.id])).url
    assert client.get(url).status_code == 200
    token = url.rsplit("/", 1)[-1]
    with pytest.raises(signing.SignatureExpired):
        signing.loads(token, salt="private-file", max_age=-1)
    assert client.get("/files/not-a-real-token").status_code == 410


def test_agent_uploads_certificate_without_account_into_admin_queue(
    client, vendor, org, types, today, admin_user, mailoutbox
):
    from events.services import join_event

    complete_vendor(vendor, types)
    event = make_event(org, today + timedelta(days=10), name="AI Fest")
    event.requirement.additional_insured_text = "AI Fest LLC and its officers"
    event.requirement.save()
    join_event(vendor, event)
    login(client, vendor.owner_user)
    client.post(reverse("events:ai_request", args=[event.id]))
    req = AICertificateRequest.objects.get()
    assert mailoutbox[0].to == ["agent@example.com"]
    assert "AI Fest LLC and its officers" in mailoutbox[0].body and req.upload_token in mailoutbox[0].body
    client.logout()

    url = reverse("events:agent_upload", args=[req.upload_token])
    assert client.get(url).status_code == 200
    response = client.post(url, {"file": png_upload("certificate.png")})
    assert response.status_code == 200 and b"Thank you" in response.content
    agent_doc = Document.objects.get(source="agent")
    assert agent_doc.status == "pending" and agent_doc.event == event
    req.refresh_from_db()
    assert req.status == "received"

    # The vendor's verified COI still counts until the agent's certificate is verified.
    from events.models import EventVendor

    assert EventVendor.objects.get(event=event, vendor=vendor).computed_status == "green"
    login(client, admin_user)
    queue = client.get(reverse("ops:queue"))
    queued = list(queue.context["documents"])
    assert agent_doc in queued and b"for AI Fest" in queue.content


def test_expired_agent_link(client, vendor, org, today):
    event = make_event(org, today)
    req = AICertificateRequest.objects.create(
        event=event,
        vendor=vendor,
        sent_to_email="a@example.com",
        wording="x",
        token_expires_at=timezone.now() - timedelta(days=1),
    )
    assert client.get(reverse("events:agent_upload", args=[req.upload_token])).status_code == 410


def test_vendor_account_deletion_keeps_past_event_documents(client, vendor, org, types, today):
    from events.models import EventVendor
    from events.services import join_event

    docs = complete_vendor(vendor, types)
    past = make_event(org, today - timedelta(days=30), name="Past Fest")
    future = make_event(org, today + timedelta(days=30), name="Future Fest")
    join_event(vendor, past)
    join_event(vendor, future)
    login(client, vendor.owner_user)
    response = client.post(reverse("vendors:delete_account"), {"confirm": "DELETE"})
    assert response.status_code == 302
    vendor.refresh_from_db()
    assert vendor.deleted_at and not vendor.owner_user.is_active and vendor.owner_user.phone is None
    assert EventVendor.objects.filter(vendor=vendor, event=past).exists()
    assert not EventVendor.objects.filter(vendor=vendor, event=future).exists()
    assert Document.objects.filter(pk=docs["coi"].pk).exists()
