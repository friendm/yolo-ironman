"""Pilot metrics computed server-side from database events."""

from statistics import median

from django.db.models import Count, Min

from documents.models import Document, DocumentType
from events.models import Event, EventVendor
from notifications.models import Notification
from vendors.models import Vendor

from .models import AuditLog

CORE_KEYS = ("coi", "health_permit", "fire_inspection", "business_license")


def profile_completion_minutes():
    """Minutes from first login (vendor record creation) to all core documents submitted."""
    wanted = set(DocumentType.objects.filter(key__in=CORE_KEYS).values_list("id", flat=True))
    durations = []
    for vendor in Vendor.objects.filter(deleted_at__isnull=True):
        firsts = (
            Document.objects.filter(vendor=vendor, submitted_at__isnull=False)
            .values("document_type_id")
            .annotate(first=Min("submitted_at"))
        )
        by_type = {row["document_type_id"]: row["first"] for row in firsts}
        if wanted and wanted <= set(by_type):
            start = vendor.owner_user.created_at
            done = max(by_type[t] for t in wanted)
            durations.append((done - start).total_seconds() / 60)
    return (round(median(durations), 1) if durations else None), len(durations)


def invite_conversion():
    invited = EventVendor.objects.count()
    joined = EventVendor.objects.filter(status="joined").count()
    return (round(100 * joined / invited, 1) if invited else None), joined, invited


def verification_turnaround_hours():
    hours = [
        (d.verified_at - d.submitted_at).total_seconds() / 3600
        for d in Document.objects.filter(verified_at__isnull=False, submitted_at__isnull=False)
    ]
    return (round(median(hours), 1) if hours else None), len(hours)


def green_by_event_day():
    """Share of joined vendors green at event start, from the status recorded for past events."""
    rows = []
    for event in Event.objects.filter(is_standing=False, start_date__isnull=False).order_by("-start_date")[:20]:
        joined = event.vendor_links.filter(status="joined")
        total = joined.count()
        green = joined.filter(computed_status="green").count()
        rows.append(
            {"event": event, "green": green, "total": total, "pct": round(100 * green / total, 1) if total else None}
        )
    return rows


def profile_reuse():
    """Vendors who joined a second event without uploading anything new in between."""
    reused = 0
    multi = 0
    for vendor_id, _count in (
        EventVendor.objects.filter(status="joined").values_list("vendor_id").annotate(n=Count("id")).filter(n__gte=2)
    ):
        multi += 1
        joins = list(
            EventVendor.objects.filter(vendor_id=vendor_id, status="joined")
            .order_by("joined_at")
            .values_list("joined_at", flat=True)
        )
        if len(joins) >= 2 and joins[0] and joins[1]:
            uploads = Document.objects.filter(
                vendor_id=vendor_id, created_at__gt=joins[0], created_at__lt=joins[1]
            ).exists()
            if not uploads:
                reused += 1
    return reused, multi


def reminders_per_event():
    rows = (
        AuditLog.objects.filter(action="bulk_reminder", entity="event")
        .values("entity_id")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    names = dict(Event.objects.filter(pk__in=[r["entity_id"] for r in rows]).values_list("id", "name"))
    return [{"event": names.get(r["entity_id"], r["entity_id"]), "count": r["n"]} for r in rows]


def _same(a, b):
    if a in (None, "") and b in (None, ""):
        return True
    return str(a).strip().lower() == str(b).strip().lower()


def extraction_accuracy():
    """Extracted fields left unchanged by the vendor and admin / fields extracted."""
    unchanged = total = 0
    docs = (
        Document.objects.filter(extraction_status="done")
        .exclude(status="draft")
        .only("extracted", "confirmed", "admin_confirmed")
    )
    for doc in docs:
        final = {**(doc.confirmed or {}), **(doc.admin_confirmed or {})}
        for key, value in (doc.extracted or {}).items():
            if key in ("confidence", "policy_types", "certificate_holder") or value in (None, "", []):
                continue
            if key not in final:
                continue
            total += 1
            if _same(value, final.get(key)):
                unchanged += 1
    return (round(100 * unchanged / total, 1) if total else None), unchanged, total


def summary():
    return {
        "completion": profile_completion_minutes(),
        "conversion": invite_conversion(),
        "turnaround": verification_turnaround_hours(),
        "green": green_by_event_day(),
        "reuse": profile_reuse(),
        "reminders": reminders_per_event(),
        "accuracy": extraction_accuracy(),
        "sms_sent": Notification.objects.filter(channel="sms", status="sent").count(),
    }
