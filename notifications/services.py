"""Send and log every SMS and email.

Vendors get SMS first, organizers email first. SMS respects STOP opt-outs and is
held during quiet hours (9 p.m. to 8 a.m. Eastern), then sent by the hourly job.
"""

import logging
from datetime import time
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .messages import render_email, render_sms
from .models import Notification

log = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")
QUIET_START = time(21, 0)
QUIET_END = time(8, 0)


def in_quiet_hours(now=None):
    local = (now or timezone.now()).astimezone(EASTERN).time()
    return local >= QUIET_START or local < QUIET_END


def _twilio_send(to, body):
    if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_FROM_NUMBER):
        log.info("SMS to %s: %s", to, body)
        return
    from twilio.rest import Client

    Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN).messages.create(
        to=to, from_=settings.TWILIO_FROM_NUMBER, body=body
    )


def _deliver_sms(notification):
    try:
        _twilio_send(notification.to, notification.body)
    except Exception as exc:  # network or provider error: log it, never break the page
        log.exception("SMS send failed")
        notification.status = Notification.Status.FAILED
        notification.error = str(exc)[:1000]
    else:
        notification.status = Notification.Status.SENT
        notification.sent_at = timezone.now()
    notification.save()


def already_sent(dedupe_key):
    return (
        bool(dedupe_key)
        and Notification.objects.filter(dedupe_key=dedupe_key).exclude(status__in=[Notification.Status.FAILED]).exists()
    )


def send_sms(user, template, payload, *, phone=None, dedupe_key="", transactional=False):
    """Send (or queue) one SMS. Transactional messages (login codes) ignore quiet hours."""
    if already_sent(dedupe_key):
        return None
    to = phone or (user.phone if user else "")
    payload = {"site": settings.SITE_NAME, **payload}
    note = Notification(
        user=user,
        channel=Notification.Channel.SMS,
        template=template,
        payload=payload,
        to=to or "",
        body=render_sms(template, payload),
        dedupe_key=dedupe_key,
    )
    if not to or (user and user.sms_opt_out and not transactional):
        note.status = Notification.Status.SKIPPED
        note.error = "opted out" if to else "no phone number"
        note.save()
        return note
    if not transactional and in_quiet_hours():
        note.status = Notification.Status.QUEUED
        note.save()
        return note
    note.save()
    _deliver_sms(note)
    return note


def send_email(user, template, payload, *, email=None, dedupe_key=""):
    if already_sent(dedupe_key):
        return None
    to = email or (user.email if user else "")
    payload = {"site": settings.SITE_NAME, **payload}
    subject, body = render_email(template, payload)
    note = Notification(
        user=user,
        channel=Notification.Channel.EMAIL,
        template=template,
        payload=payload,
        to=to or "",
        body=f"{subject}\n\n{body}",
        dedupe_key=dedupe_key,
    )
    if not to:
        note.status = Notification.Status.SKIPPED
        note.error = "no email address"
        note.save()
        return note
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to])
    except Exception as exc:
        log.exception("Email send failed")
        note.status = Notification.Status.FAILED
        note.error = str(exc)[:1000]
    else:
        note.status = Notification.Status.SENT
        note.sent_at = timezone.now()
    note.save()
    return note


def notify_organizer(user, sms_template, email_template, payload, **kwargs):
    """Organizers get email first, SMS only when they have no email."""
    if user.email:
        return send_email(user, email_template, payload, **kwargs)
    return send_sms(user, sms_template, payload, **kwargs)


def flush_queued_sms():
    """Send SMS held for quiet hours. Called by the hourly job."""
    if in_quiet_hours():
        return 0
    sent = 0
    for note in Notification.objects.filter(channel=Notification.Channel.SMS, status=Notification.Status.QUEUED):
        if note.user and note.user.sms_opt_out:
            note.status = Notification.Status.SKIPPED
            note.error = "opted out"
            note.save()
            continue
        _deliver_sms(note)
        sent += 1
    return sent


def absolute(path):
    return settings.SITE_URL + path
