import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """Every table has a uuid id plus created_at and updated_at."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
