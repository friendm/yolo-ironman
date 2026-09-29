from datetime import timedelta

from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from documents.models import Document, DocumentType
from events.models import EventVendor
from events.status import current_documents
from ops import audit

EXPIRING_WINDOW_DAYS = 30


def document_cards(vendor):
    """One card per document type with the vendor's current document, if any."""
    docs = current_documents(vendor)
    drafts = {
        d.document_type_id: d
        for d in Document.objects.filter(
            vendor=vendor, status=Document.Status.DRAFT, superseded_by__isnull=True
        ).order_by("created_at")
    }
    today = timezone.localdate()
    cards = []
    for dtype in DocumentType.objects.all():
        doc = docs.get(dtype.id)
        pill = "missing"
        days_left = None
        if doc is not None:
            pill = doc.status
            if doc.expiration_date:
                days_left = (doc.expiration_date - today).days
                if doc.status == Document.Status.VERIFIED and 0 <= days_left <= EXPIRING_WINDOW_DAYS:
                    pill = "expiring"
        cards.append({"type": dtype, "doc": doc, "draft": drafts.get(dtype.id), "pill": pill, "days_left": days_left})
    return cards


def status_summary(cards):
    """The one-line headline on the vendor home status card."""
    expiring = sorted(
        (c for c in cards if c["doc"] and c["days_left"] is not None and 0 <= c["days_left"] <= EXPIRING_WINDOW_DAYS),
        key=lambda c: c["days_left"],
    )
    problems = [c for c in cards if c["pill"] in ("rejected", "expired")]
    pending = [c for c in cards if c["pill"] == "pending"]
    missing = [c for c in cards if c["pill"] == "missing"]
    if problems:
        c = problems[0]
        word = "was rejected" if c["pill"] == "rejected" else "has expired"
        return "red", f"{c['type'].label} {word}"
    if expiring:
        c = expiring[0]
        days = c["days_left"]
        when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
        return "yellow", f"{c['type'].label} expires {when}"
    if pending:
        n = len(pending)
        return "yellow", f"{n} document{'s' if n != 1 else ''} pending"
    if missing:
        n = len(missing)
        return "red", f"{n} document{'s' if n != 1 else ''} to add"
    return "green", "Verified"


def upcoming_links(vendor):
    today = timezone.localdate()
    links = (
        EventVendor.objects.filter(vendor=vendor)
        .exclude(status=EventVendor.Status.REMOVED)
        .select_related("event__organization")
        .order_by("event__start_date")
    )
    return [
        link
        for link in links
        if link.event.is_standing or not link.event.end_date or link.event.end_date >= today - timedelta(days=1)
    ]


@transaction.atomic
def delete_account(vendor, actor):
    """Close the account. Documents shared for past events stay in those events' exports."""
    today = timezone.localdate()
    past_links = EventVendor.objects.filter(vendor=vendor, status=EventVendor.Status.JOINED, event__end_date__lt=today)
    keep_ids = set()
    if past_links.exists():
        keep_ids = set(Document.objects.current().filter(vendor=vendor).values_list("id", flat=True))
    EventVendor.objects.filter(vendor=vendor).exclude(pk__in=past_links.values("pk")).delete()
    for doc in Document.objects.filter(vendor=vendor).exclude(pk__in=keep_ids):
        for path in (doc.file_path, doc.thumbnail_path):
            if path:
                default_storage.delete(path)
        doc.delete()
    if vendor.photo_url:
        default_storage.delete(vendor.photo_url)
    vendor.deleted_at = timezone.now()
    vendor.description = ""
    vendor.photo_url = ""
    vendor.agent_name = vendor.agent_email = vendor.agent_phone = ""
    vendor.save()
    user = vendor.owner_user
    audit.record(actor, "account_delete", vendor, kept_documents=len(keep_ids))
    user.is_active = False
    user.phone = None
    user.email = None
    user.full_name = ""
    user.set_unusable_password()
    user.save()
