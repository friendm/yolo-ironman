import secrets

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse

from common.models import TimeStampedModel


class DocumentType(TimeStampedModel):
    key = models.SlugField(max_length=40, unique=True)
    label = models.CharField(max_length=120)
    has_expiration = models.BooleanField(default=True)
    extraction_schema = models.JSONField(default=dict, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "label"]

    def __str__(self):
        return self.label

    @property
    def is_coi(self):
        return self.key == "coi"


class DocumentQuerySet(models.QuerySet):
    def current(self):
        """Submitted documents that have not been replaced by a newer upload.

        An agent's upload only replaces the vendor's document once an admin verifies it.
        """
        return (
            self.filter(superseded_by__isnull=True)
            .exclude(status=Document.Status.DRAFT)
            .exclude(source=Document.Source.AGENT, status__in=[Document.Status.PENDING, Document.Status.REJECTED])
        )

    def visible_to(self, user):
        """Object-level rule: vendors see their own; organizers only via joined events; admins all."""
        if not user.is_authenticated:
            return self.none()
        if user.role == "admin":
            return self
        if user.role == "vendor":
            return self.filter(vendor__owner_user=user)
        if user.role == "organizer":
            return (
                self.filter(
                    vendor__event_links__event__organization__owner_user=user,
                    vendor__event_links__status="joined",
                )
                .exclude(status=Document.Status.DRAFT)
                .distinct()
            )
        return self.none()


def upload_path(document, filename):
    return f"documents/{document.vendor_id}/{document.id}/{filename}"


class Document(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"  # uploaded, waiting for the vendor to confirm fields
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"

    class Method(models.TextChoices):
        AGENT_EMAIL = "agent_email", "Agent email"
        AGENT_CALL = "agent_call", "Agent call"
        INSURER_PORTAL = "insurer_portal", "Insurer portal"
        VISUAL = "visual", "Visual only"

    class Extraction(models.TextChoices):
        QUEUED = "queued", "Queued"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    class Source(models.TextChoices):
        VENDOR = "vendor", "Vendor upload"
        AGENT = "agent", "Agent upload"

    vendor = models.ForeignKey("vendors.Vendor", on_delete=models.CASCADE, related_name="documents")
    document_type = models.ForeignKey(DocumentType, on_delete=models.PROTECT, related_name="documents")
    file_path = models.CharField(max_length=500)
    thumbnail_path = models.CharField(max_length=500, blank=True)
    content_type = models.CharField(max_length=60, blank=True)
    original_filename = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.VENDOR)
    event = models.ForeignKey(
        "events.Event",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="agent_documents",
        help_text="Set when an agent uploaded this certificate for a specific event.",
    )

    extracted = models.JSONField(default=dict, blank=True)
    extraction_status = models.CharField(max_length=10, choices=Extraction.choices, default=Extraction.QUEUED)
    extraction_model = models.CharField(max_length=80, blank=True)
    extraction_prompt_version = models.CharField(max_length=20, blank=True)
    extraction_raw = models.TextField(blank=True)
    confirmed = models.JSONField(default=dict, blank=True, help_text="Fields as confirmed by the vendor.")
    admin_confirmed = models.JSONField(default=dict, blank=True, help_text="Fields as confirmed by the admin.")

    effective_date = models.DateField(null=True, blank=True)
    expiration_date = models.DateField(null=True, blank=True, db_index=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_method = models.CharField(max_length=20, choices=Method.choices, blank=True)
    reviewer_notes = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)
    superseded_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="supersedes"
    )

    objects = DocumentQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["vendor", "document_type"], condition=Q(superseded_by__isnull=True), name="doc_current_idx"
            )
        ]

    def __str__(self):
        return f"{self.document_type} for {self.vendor}"

    def get_absolute_url(self):
        return reverse("documents:view", args=[self.id])

    @property
    def is_image(self):
        return self.content_type.startswith("image/")


class COIDetails(TimeStampedModel):
    """Structured COI fields, confirmed by the vendor and then the admin. Dollar amounts are integers."""

    document = models.OneToOneField(Document, on_delete=models.CASCADE, related_name="coi")
    insurer_name = models.CharField(max_length=200, blank=True)
    naic_number = models.CharField(max_length=20, blank=True)
    policy_number = models.CharField(max_length=80, blank=True)
    gl_per_occurrence = models.PositiveIntegerField(null=True, blank=True)
    gl_aggregate = models.PositiveIntegerField(null=True, blank=True)
    auto_liability = models.PositiveIntegerField(null=True, blank=True)
    workers_comp = models.BooleanField(default=False)
    liquor_liability = models.PositiveIntegerField(null=True, blank=True)
    additional_insureds = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"COI details for {self.document}"


class ShareLink(TimeStampedModel):
    """A 14-day read-only link to a vendor's verified documents."""

    vendor = models.ForeignKey("vendors.Vendor", on_delete=models.CASCADE, related_name="share_links")
    token = models.CharField(max_length=64, unique=True, default=secrets.token_urlsafe)
    expires_at = models.DateTimeField()
    revoked = models.BooleanField(default=False)

    def url(self):
        return settings.SITE_URL + reverse("documents:share", args=[self.token])
