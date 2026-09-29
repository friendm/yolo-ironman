import io
from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from PIL import Image

from accounts.models import User
from documents.models import COIDetails, Document, DocumentType
from events.models import Event, Organization
from events.services import ensure_requirement
from ops import sample_docs
from vendors.models import Vendor


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import cache

    cache.clear()


@pytest.fixture
def today():
    return timezone.localdate()


@pytest.fixture
def types(db):
    return {t.key: t for t in DocumentType.objects.all()}


def make_vendor(phone="+14045550111", name="Test Truck", vendor_type="food_truck"):
    user = User.objects.create_user(phone=phone, role=User.Role.VENDOR)
    return Vendor.objects.create(
        owner_user=user,
        business_name=name,
        vendor_type=vendor_type,
        agent_email="agent@example.com",
        agent_name="Pat Agent",
    )


def make_organizer(phone="+14045550211", email="org@example.com", name="Test Fest"):
    user = User.objects.create_user(phone=phone, email=email, role=User.Role.ORGANIZER)
    return Organization.objects.create(owner_user=user, name=name)


def make_event(org, start, end=None, **kwargs):
    event = Event.objects.create(
        organization=org, name=kwargs.pop("name", "Food Fest"), start_date=start, end_date=end or start, **kwargs
    )
    ensure_requirement(event)
    return event


def make_doc(vendor, dtype, status=Document.Status.VERIFIED, expires=None, gl=(1_000_000, 2_000_000), auto=1_000_000):
    doc = Document(
        vendor=vendor,
        document_type=dtype,
        content_type="image/png",
        status=status,
        expiration_date=expires or (timezone.localdate() + timedelta(days=365)),
    )
    doc.file_path = default_storage.save(
        f"documents/{vendor.id}/{doc.id}/original.png",
        ContentFile(sample_docs.render("SAMPLE", [("Name", vendor.business_name)])),
    )
    doc.submitted_at = timezone.now()
    doc.save()
    if status != Document.Status.DRAFT:  # mirror submit(): a newer submission replaces older ones
        Document.objects.filter(
            vendor=vendor, document_type=dtype, superseded_by__isnull=True, created_at__lt=doc.created_at
        ).update(superseded_by=doc)
    if dtype.key == "coi":
        COIDetails.objects.create(document=doc, gl_per_occurrence=gl[0], gl_aggregate=gl[1], auto_liability=auto)
    return doc


def complete_vendor(vendor, types, **kwargs):
    return {
        key: make_doc(vendor, types[key], **kwargs)
        for key in ("coi", "health_permit", "fire_inspection", "business_license")
    }


def png_upload(name="doc.png", content=None):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, content or sample_docs.render("SAMPLE", [("A", "B")]), content_type="image/png")


def heic_bytes():
    import pillow_heif

    image = Image.new("RGB", (40, 30), "red")
    out = io.BytesIO()
    pillow_heif.from_pillow(image).save(out, format="HEIF")
    return out.getvalue()


def login(client, user):
    client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
    return client


@pytest.fixture
def vendor(db):
    return make_vendor()


@pytest.fixture
def org(db):
    return make_organizer()


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(phone="+14045550100", role=User.Role.ADMIN, email="admin@example.com")
