from django.conf import settings
from django.db import models

from common.models import TimeStampedModel


class VendorQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Vendors see themselves; organizers see vendors joined to their events; admins see all."""
        if not user.is_authenticated:
            return self.none()
        if user.role == "admin":
            return self
        if user.role == "vendor":
            return self.filter(owner_user=user)
        if user.role == "organizer":
            return self.filter(
                event_links__event__organization__owner_user=user,
                event_links__status="joined",
            ).distinct()
        return self.none()


class Vendor(TimeStampedModel):
    class VendorType(models.TextChoices):
        FOOD_TRUCK = "food_truck", "Food truck"
        CATERER = "caterer", "Caterer"
        RENTALS = "rentals", "Rentals"
        OTHER = "other", "Other"

    owner_user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vendor")
    business_name = models.CharField(max_length=200)
    vendor_type = models.CharField(max_length=20, choices=VendorType.choices, default=VendorType.FOOD_TRUCK)
    description = models.TextField(blank=True)
    service_area = models.CharField(max_length=200, blank=True)
    photo_url = models.CharField(max_length=500, blank=True, help_text="Storage path of the optional photo.")
    agent_name = models.CharField("Agent or insurer contact", max_length=200, blank=True)
    agent_email = models.EmailField(blank=True)
    agent_phone = models.CharField(max_length=20, blank=True)
    insurer_name = models.CharField(max_length=200, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = VendorQuerySet.as_manager()

    class Meta:
        ordering = ["business_name"]

    def __str__(self):
        return self.business_name
