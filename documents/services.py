from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django_q.tasks import async_task

from notifications import services as notify
from ops import audit

from .models import COIDetails, Document


def queue_extraction(document):
    async_task("documents.tasks.extract_document", document.id)


def save_upload(vendor, document_type, clean, *, original_name="", source=Document.Source.VENDOR, event=None):
    """Store a validated upload privately and queue AI extraction."""
    document = Document(
        vendor=vendor,
        document_type=document_type,
        source=source,
        event=event,
        content_type=clean.content_type,
        original_filename=original_name[:255],
    )
    base = f"documents/{vendor.id}/{document.id}"
    document.file_path = default_storage.save(f"{base}/original.{clean.extension}", ContentFile(clean.content))
    if clean.thumbnail:
        document.thumbnail_path = default_storage.save(f"{base}/thumb.jpg", ContentFile(clean.thumbnail))
    if source == Document.Source.AGENT:
        document.status = Document.Status.PENDING
        document.submitted_at = timezone.now()
    document.save()
    queue_extraction(document)
    return document


def _apply_fields(document, data):
    document.effective_date = data.get("effective_date") or data.get("issue_date") or None
    document.expiration_date = data.get("expiration_date") or None
    if document.document_type.key == "coi":
        insureds = [line.strip() for line in (data.get("additional_insured_text") or "").splitlines() if line.strip()]
        COIDetails.objects.update_or_create(
            document=document,
            defaults={
                "insurer_name": data.get("insurer_name") or "",
                "naic_number": data.get("naic_number") or "",
                "policy_number": data.get("policy_number") or "",
                "gl_per_occurrence": data.get("gl_per_occurrence"),
                "gl_aggregate": data.get("gl_aggregate"),
                "auto_liability": data.get("auto_liability"),
                "liquor_liability": data.get("liquor_liability"),
                "workers_comp": bool(data.get("workers_comp")),
                "additional_insureds": insureds,
            },
        )


def _supersede_older(document):
    """A new version replaces the old one; the old file is kept for history."""
    Document.objects.filter(
        vendor=document.vendor,
        document_type=document.document_type,
        superseded_by__isnull=True,
        created_at__lt=document.created_at,
    ).exclude(pk=document.pk).update(superseded_by=document)


def _refresh_statuses(vendor):
    from events.services import recompute_for_vendor

    recompute_for_vendor(vendor)


@transaction.atomic
def submit(document, form, actor):
    """The vendor confirmed or corrected the fields: status becomes Pending verification."""
    data = form.cleaned_data
    document.confirmed = form.json_data()
    document.status = Document.Status.PENDING
    document.submitted_at = timezone.now()
    _apply_fields(document, data)
    document.save()
    _supersede_older(document)
    audit.record(actor, "document_submit", document, type=document.document_type.key)
    _refresh_statuses(document.vendor)
    return document


@transaction.atomic
def verify(document, actor, method, notes="", form=None):
    if form is not None:
        document.admin_confirmed = form.json_data()
        _apply_fields(document, form.cleaned_data)
    document.status = Document.Status.VERIFIED
    document.verified_by = actor
    document.verified_at = timezone.now()
    document.verification_method = method
    document.reviewer_notes = notes
    document.rejection_reason = ""
    if document.expiration_date and document.expiration_date < timezone.localdate():
        document.status = Document.Status.EXPIRED
    document.save()
    _supersede_older(document)
    if document.source == Document.Source.AGENT and document.event_id:
        document.event.ai_requests.filter(vendor=document.vendor).update(status="received")
    audit.record(actor, "document_verify", document, method=method)
    vendor = document.vendor
    _refresh_statuses(vendor)
    transaction.on_commit(
        lambda: notify.send_sms(
            vendor.owner_user,
            "document_verified",
            {"document": document.document_type.label.lower(), "link": notify.absolute(reverse("vendors:home"))},
            dedupe_key=f"verified:{document.id}",
        )
    )
    return document


@transaction.atomic
def reject(document, actor, reason, notes="", method=""):
    document.status = Document.Status.REJECTED
    document.rejection_reason = reason
    document.reviewer_notes = notes
    document.verification_method = method
    document.verified_by = actor
    document.verified_at = timezone.now()
    document.save()
    audit.record(actor, "document_reject", document, reason=reason)
    vendor = document.vendor
    link = notify.absolute(reverse("vendors:upload", args=[document.document_type.key]))
    _refresh_statuses(vendor)
    transaction.on_commit(
        lambda: notify.send_sms(
            vendor.owner_user,
            "document_rejected",
            {"document": document.document_type.label.lower(), "reason": reason.rstrip(".") + ".", "link": link},
            dedupe_key=f"rejected:{document.id}",
        )
    )
    return document


def mark_expired(today=None):
    today = today or timezone.localdate()
    expired = Document.objects.filter(
        status__in=[Document.Status.PENDING, Document.Status.VERIFIED], expiration_date__lt=today
    )
    vendors = set(expired.values_list("vendor_id", flat=True))
    count = expired.update(status=Document.Status.EXPIRED, updated_at=timezone.now())
    return count, vendors


def admin_flags(document):
    """Mismatches worth a closer look before verifying."""
    flags = []
    fields = document.confirmed or document.extracted or {}
    insured = (fields.get("insured_name") or fields.get("holder_name") or "").strip()
    if (
        insured
        and _normalize(insured) not in _normalize(document.vendor.business_name)
        and _normalize(document.vendor.business_name) not in _normalize(insured)
    ):
        flags.append(f'Name on document ("{insured}") differs from business name "{document.vendor.business_name}"')
    start = fields.get("effective_date") or fields.get("issue_date")
    end = fields.get("expiration_date")
    if start and end and str(end) < str(start):
        flags.append("Expiration date is before the effective date")
    if document.document_type.key == "coi":
        from events.models import EventVendor

        links = EventVendor.objects.filter(vendor=document.vendor, status="joined").select_related("event__requirement")
        for link in links:
            req = getattr(link.event, "requirement", None)
            if req is None:
                continue
            occ, agg = fields.get("gl_per_occurrence") or 0, fields.get("gl_aggregate") or 0
            if occ < req.min_gl_per_occurrence or agg < req.min_gl_aggregate:
                flags.append(f"Limits are below the minimums for {link.event.name}")
    return flags


def _normalize(text):
    return "".join(ch for ch in text.lower() if ch.isalnum())
