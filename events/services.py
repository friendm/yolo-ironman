from datetime import timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from documents.models import DocumentType
from notifications import services as notify
from ops import audit

from .models import Event, EventRequirement, EventVendor, RequirementTemplate
from .status import current_documents, evaluate

DEFAULT_REQUIRED = ("coi", "health_permit", "fire_inspection")


def default_requirement_values():
    """Values for a new event's requirements form: the admin's default template, else the spec defaults."""
    template = RequirementTemplate.objects.filter(is_default=True).first()
    if template:
        return {
            "required_document_types": list(template.required_document_types.all()),
            "min_gl_per_occurrence": template.min_gl_per_occurrence,
            "min_gl_aggregate": template.min_gl_aggregate,
            "require_auto": template.require_auto,
            "require_liquor": template.require_liquor,
        }
    return {
        "required_document_types": list(DocumentType.objects.filter(key__in=DEFAULT_REQUIRED)),
        "min_gl_per_occurrence": 1_000_000,
        "min_gl_aggregate": 2_000_000,
        "require_auto": True,
        "require_liquor": False,
    }


def ensure_requirement(event):
    try:
        return event.requirement
    except EventRequirement.DoesNotExist:
        values = default_requirement_values()
        types = values.pop("required_document_types")
        requirement = EventRequirement.objects.create(event=event, **values)
        requirement.required_document_types.set(types)
        return requirement


def recompute(link, docs=None, notify_organizer=True):
    """Recalculate one vendor's status at one event and alert the organizer if it just turned red."""
    result = evaluate(link.event, link.vendor, docs)
    previous = link.computed_status
    changed = previous != result.color or link.status_reasons != result.reasons
    if changed:
        link.computed_status = result.color
        link.status_reasons = result.reasons
        link.save(update_fields=["computed_status", "status_reasons", "updated_at"])
    event = link.event
    if (
        notify_organizer
        and changed
        and result.color == "red"
        and previous != "red"
        and link.status == EventVendor.Status.JOINED
        and event.start_date
        and 0 <= (event.start_date - timezone.localdate()).days <= 7
    ):
        owner = event.organization.owner_user
        notify.notify_organizer(
            owner,
            "bulk_reminder",
            "vendor_red",
            {
                "vendor": link.vendor.business_name,
                "event": event.name,
                "date": f"{event.start_date:%b %-d}",
                "reasons": "\n".join(f"- {r}" for r in result.reasons),
                "org": event.organization.name,
                "missing": "; ".join(result.reasons),
                "link": notify.absolute(reverse("events:org_vendor", args=[event.id, link.vendor_id])),
            },
            dedupe_key=f"vendor_red:{link.id}:{timezone.localdate()}",
        )
    return link


def recompute_for_vendor(vendor):
    docs = current_documents(vendor)
    links = EventVendor.objects.filter(vendor=vendor).exclude(status=EventVendor.Status.REMOVED)
    for link in links.select_related("event__requirement", "event__organization__owner_user", "vendor"):
        recompute(link, docs)


def recompute_for_event(event):
    for link in event.vendor_links.exclude(status=EventVendor.Status.REMOVED).select_related("vendor"):
        link.event = event
        recompute(link)


def recompute_upcoming(days=30):
    today = timezone.localdate()
    events = Event.objects.exclude(status=Event.Status.CLOSED).filter(
        is_standing=False, end_date__gte=today, start_date__lte=today + timedelta(days=days)
    ) | Event.objects.filter(is_standing=True).exclude(status=Event.Status.CLOSED)
    for event in events.distinct():
        recompute_for_event(event)


@transaction.atomic
def join_event(vendor, event, actor=None):
    """Joining shares the vendor's current documents with the organizer."""
    link, _ = EventVendor.objects.get_or_create(event=event, vendor=vendor)
    if link.status != EventVendor.Status.JOINED:
        link.status = EventVendor.Status.JOINED
        link.joined_at = timezone.now()
        link.save(update_fields=["status", "joined_at", "updated_at"])
        audit.record(actor, "event_join", link, event=event.id, vendor=vendor.id)
    recompute(link, notify_organizer=False)
    return link


def invite_vendor(event, vendor, actor=None):
    link, created = EventVendor.objects.get_or_create(event=event, vendor=vendor)
    if link.status == EventVendor.Status.REMOVED:
        link.status = EventVendor.Status.INVITED
        link.save(update_fields=["status", "updated_at"])
        created = True
    if created:
        recompute(link, notify_organizer=False)
        notify.send_sms(
            vendor.owner_user,
            "event_invite",
            {"org": event.organization.name, "event": event.name, "link": event.invite_url()},
            dedupe_key=f"invite:{link.id}",
        )
        audit.record(actor, "event_invite", link, event=event.id, vendor=vendor.id)
    return link, created
