from django.conf import settings
from django.db import models

from common.models import TimeStampedModel


class Notification(TimeStampedModel):
    class Channel(models.TextChoices):
        SMS = "sms", "SMS"
        EMAIL = "email", "Email"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"  # held for quiet hours
        SENT = "sent", "Sent"
        SKIPPED = "skipped", "Skipped"  # opted out or no address
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="notifications"
    )
    channel = models.CharField(max_length=8, choices=Channel.choices)
    template = models.CharField(max_length=60, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    to = models.CharField(max_length=254, blank=True)
    body = models.TextField(blank=True)
    dedupe_key = models.CharField(max_length=200, blank=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.channel} {self.template} to {self.to}"
