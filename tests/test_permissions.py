import pytest
from django.urls import reverse

from documents.models import Document
from events.services import join_event
from tests.conftest import complete_vendor, login, make_event, make_organizer, make_vendor

pytestmark = pytest.mark.django_db


def test_vendor_cannot_read_another_vendors_documents(client, types):
    alice = make_vendor("+14045550121", "Alice Eats")
    bob = make_vendor("+14045550122", "Bob Bites")
    bob_docs = complete_vendor(bob, types)
    login(client, alice.owner_user)
    assert client.get(reverse("documents:view", args=[bob_docs["coi"].id])).status_code == 404
    assert client.get(reverse("documents:thumbnail", args=[bob_docs["coi"].id])).status_code == 404
    assert not Document.objects.visible_to(alice.owner_user).filter(vendor=bob).exists()


def test_vendor_can_read_own_documents_and_view_is_audited(client, vendor, types):
    docs = complete_vendor(vendor, types)
    login(client, vendor.owner_user)
    response = client.get(reverse("documents:view", args=[docs["coi"].id]))
    assert response.status_code == 302
    from ops.models import AuditLog

    assert AuditLog.objects.filter(action="document_view", entity_id=docs["coi"].id).count() == 1


def test_organizer_sees_documents_only_after_vendor_joins(client, vendor, types, today):
    docs = complete_vendor(vendor, types)
    org = make_organizer()
    event = make_event(org, today)
    login(client, org.owner_user)
    assert client.get(reverse("documents:view", args=[docs["coi"].id])).status_code == 404
    assert client.get(reverse("events:org_vendor", args=[event.id, vendor.id])).status_code == 404
    join_event(vendor, event)
    assert client.get(reverse("documents:view", args=[docs["coi"].id])).status_code == 302
    assert client.get(reverse("events:org_vendor", args=[event.id, vendor.id])).status_code == 200


def test_invited_but_not_joined_vendor_is_hidden_from_organizer(client, vendor, types, today):
    from events.services import invite_vendor

    docs = complete_vendor(vendor, types)
    org = make_organizer()
    event = make_event(org, today)
    invite_vendor(event, vendor)
    assert not Document.objects.visible_to(org.owner_user).filter(pk=docs["coi"].pk).exists()


def test_organizer_cannot_open_another_organizers_event(client, today):
    mine = make_organizer("+14045550231", "a@example.com")
    theirs = make_organizer("+14045550232", "b@example.com", name="Other")
    event = make_event(theirs, today)
    login(client, mine.owner_user)
    for name in (
        "events:org_event",
        "events:event_edit",
        "events:org_invite",
        "events:export_csv",
        "events:export_zip",
    ):
        assert client.get(reverse(name, args=[event.id])).status_code == 404


def test_role_gates(client, vendor, admin_user):
    login(client, vendor.owner_user)
    assert client.get(reverse("ops:queue")).status_code == 403
    assert client.get(reverse("events:org_home")).status_code == 403
    client.logout()
    login(client, admin_user)
    assert client.get(reverse("ops:queue")).status_code == 200
    assert client.get(reverse("vendors:home")).status_code == 403


def test_anonymous_users_are_sent_to_login(client):
    for url in (reverse("vendors:home"), reverse("events:org_home"), reverse("ops:queue")):
        response = client.get(url)
        assert response.status_code == 302 and response.url.startswith(reverse("accounts:login"))
