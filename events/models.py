import secrets

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.urls import reverse
from django.utils import timezone

from common.models import TimeStampedModel

INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_invite_code():
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(6))


def new_token():
    return secrets.token_urlsafe(32)


class Organization(TimeStampedModel):
    class OrgType(models.TextChoices):
        FESTIVAL = "festival", "Festival"
        VENUE = "venue", "Venue"
        TRUCK_PARK = "truck_park", "Truck park"
        BREWERY = "brewery", "Brewery"
        OFFICE = "office", "Office park"
        OTHER = "other", "Other"

    owner_user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="organization")
    name = models.CharField(max_length=200)
    org_type = models.CharField(max_length=20, choices=OrgType.choices, default=OrgType.FESTIVAL)
    plan = models.CharField(max_length=40, default="pilot", help_text="Billing plan; unused until payments ship.")
    recurring_host = models.BooleanField(
        default=False, help_text="Keeps a standing vendor list evaluated against today's date."
    )

    def __str__(self):
        return self.name


class RequirementTemplate(TimeStampedModel):
    """Admin-editable defaults for the create-event requirements form."""

    name = models.CharField(max_length=120)
    is_default = models.BooleanField(default=False)
    required_document_types = models.ManyToManyField("documents.DocumentType", blank=True)
    min_gl_per_occurrence = models.PositiveIntegerField(default=1_000_000)
    min_gl_aggregate = models.PositiveIntegerField(default=2_000_000)
    require_auto = models.BooleanField(default=True)
    require_liquor = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class EventQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.role == "admin":
            return self
        if user.role == "organizer":
            return self.filter(organization__owner_user=user)
        if user.role == "vendor":
            return self.filter(vendor_links__vendor__owner_user=user).exclude(vendor_links__status="removed")
        return self.none()


class Event(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="events")
    name = models.CharField(max_length=200)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    location_name = models.CharField(max_length=200, blank=True)
    address = models.CharField(max_length=300, blank=True)
    invite_code = models.CharField(max_length=12, unique=True, default=new_invite_code)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    is_standing = models.BooleanField(
        default=False, help_text="Recurring host mode: a standing list not tied to a date."
    )
    last_bulk_reminder_at = models.DateTimeField(null=True, blank=True)

    objects = EventQuerySet.as_manager()

    class Meta:
        ordering = ["start_date", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("events:org_event", args=[self.id])

    def evaluation_date(self):
        """The date documents must be valid through: event end, or today for standing lists."""
        if self.is_standing or not self.end_date:
            return timezone.localdate()
        return self.end_date

    def invite_url(self):
        return settings.SITE_URL + reverse("events:invite", args=[self.invite_code])


class EventRequirement(TimeStampedModel):
    event = models.OneToOneField(Event, on_delete=models.CASCADE, related_name="requirement")
    required_document_types = models.ManyToManyField("documents.DocumentType", blank=True)
    min_gl_per_occurrence = models.PositiveIntegerField(default=1_000_000)
    min_gl_aggregate = models.PositiveIntegerField(default=2_000_000)
    require_auto = models.BooleanField(default=True)
    require_liquor = models.BooleanField(default=False)
    additional_insured_text = models.TextField(blank=True)

    def __str__(self):
        return f"Requirements for {self.event}"


class EventVendorQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.role == "admin":
            return self
        if user.role == "organizer":
            return self.filter(event__organization__owner_user=user)
        if user.role == "vendor":
            return self.filter(vendor__owner_user=user)
        return self.none()


class EventVendor(TimeStampedModel):
    class Status(models.TextChoices):
        INVITED = "invited", "Invited"
        JOINED = "joined", "Joined"
        REMOVED = "removed", "Removed"

    class Computed(models.TextChoices):
        GREEN = "green", "Green"
        YELLOW = "yellow", "Yellow"
        RED = "red", "Red"

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="vendor_links")
    vendor = models.ForeignKey("vendors.Vendor", on_delete=models.CASCADE, related_name="event_links")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.INVITED)
    joined_at = models.DateTimeField(null=True, blank=True)
    computed_status = models.CharField(max_length=10, choices=Computed.choices, default=Computed.RED)
    status_reasons = ArrayField(models.TextField(), default=list, blank=True)

    objects = EventVendorQuerySet.as_manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event", "vendor"], name="unique_event_vendor")]

    def __str__(self):
        return f"{self.vendor} at {self.event}"


class AICertificateRequest(TimeStampedModel):
    """An additional-insured certificate request emailed to a vendor's agent."""

    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        RECEIVED = "received", "Received"

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="ai_requests")
    vendor = models.ForeignKey("vendors.Vendor", on_delete=models.CASCADE, related_name="ai_requests")
    sent_to_email = models.EmailField()
    wording = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SENT)
    sent_at = models.DateTimeField(default=timezone.now)
    upload_token = models.CharField(max_length=64, unique=True, default=new_token)
    token_expires_at = models.DateTimeField()

    def upload_url(self):
        return settings.SITE_URL + reverse("events:agent_upload", args=[self.upload_token])
