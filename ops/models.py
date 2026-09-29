from django.conf import settings
from django.db import models

from common.models import TimeStampedModel


class AuditLog(TimeStampedModel):
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    action = models.CharField(max_length=60, db_index=True)
    entity = models.CharField(max_length=60, db_index=True)
    entity_id = models.UUIDField(null=True, blank=True, db_index=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} {self.entity} {self.entity_id}"
