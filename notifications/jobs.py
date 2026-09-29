"""Scheduled jobs run by Django-Q2 (see the setup_schedules management command)."""

import logging

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from documents.models import Document
from documents.services import mark_expired
from events.services import recompute_for_vendor, recompute_upcoming
from vendors.models import Vendor

from . import services

log = logging.getLogger(__name__)
REMINDER_DAYS = (30, 14, 3)


def send_expiration_reminders(today=None):
    """Text vendors 30, 14, and 3 days before a current document expires. Exactly once per document per step."""
    today = today or timezone.localdate()
    sent = 0
    for days in REMINDER_DAYS:
        target = today + timezone.timedelta(days=days)
        docs = (
            Document.objects.current()
            .filter(expiration_date=target, status__in=[Document.Status.VERIFIED, Document.Status.PENDING])
            .select_related("vendor__owner_user", "document_type")
        )
        for doc in docs:
            if doc.vendor.deleted_at:
                continue
            note = services.send_sms(
                doc.vendor.owner_user,
                "document_expiring",
                {
                    "document": doc.document_type.label,
                    "date": f"{doc.expiration_date:%b %-d}",
                    "link": services.absolute(reverse("vendors:upload", args=[doc.document_type.key])),
                },
                dedupe_key=f"expiring:{doc.id}:{days}",
            )
            if note is not None:
                sent += 1
    return sent


def daily():
    """7:00 a.m. Eastern: mark expired documents, send reminders, recompute statuses for the next 30 days."""
    today = timezone.localdate()
    count, vendor_ids = mark_expired(today)
    for vendor in Vendor.objects.filter(pk__in=vendor_ids):
        recompute_for_vendor(vendor)
    reminders = send_expiration_reminders(today)
    recompute_upcoming(days=30)
    log.info("daily job: %s expired, %s reminders", count, reminders)
    return {"expired": count, "reminders": reminders}


def hourly():
    """Admin digest of pending documents, and SMS held back during quiet hours."""
    flushed = services.flush_queued_sms()
    pending = Document.objects.filter(status=Document.Status.PENDING, superseded_by__isnull=True).count()
    if pending and settings.ADMIN_DIGEST_EMAILS:
        stamp = timezone.localtime().strftime("%Y%m%d%H")
        for email in settings.ADMIN_DIGEST_EMAILS:
            services.send_email(
                None,
                "admin_digest",
                {"count": pending, "link": services.absolute(reverse("ops:queue"))},
                email=email,
                dedupe_key=f"digest:{email}:{stamp}",
            )
    return {"flushed": flushed, "pending": pending}
