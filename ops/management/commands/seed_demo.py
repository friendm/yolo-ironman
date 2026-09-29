from datetime import timedelta
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from PIL import Image

from accounts.models import User
from common.uploads import CleanUpload, make_thumbnail
from documents.models import COIDetails, Document, DocumentType
from events.models import Event, EventVendor, Organization
from events.services import ensure_requirement, join_event, recompute_for_event
from vendors.models import Vendor

from ... import sample_docs

VENDORS = [
    ("+14045550101", "Smokestack BBQ Truck", "food_truck", "all_verified"),
    ("+14045550102", "Tacos La Perla", "food_truck", "pending_permit"),
    ("+14045550103", "Sweet Peach Creamery", "food_truck", "expiring_soon"),
    ("+14045550104", "Midtown Bao", "food_truck", "low_limits"),
    ("+14045550105", "Big Tent Rentals", "rentals", "missing"),
]


def _png(content):
    return CleanUpload(content, "png", "image/png", make_thumbnail(Image.open(BytesIO(content))))


class Command(BaseCommand):
    help = "Create one admin, two organizers, and five vendors with sample documents. Safe to re-run."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing demo users first.")

    @transaction.atomic
    def handle(self, *args, reset=False, **options):
        phones = [v[0] for v in VENDORS] + ["+14045550100", "+14045550201", "+14045550202"]
        if reset:
            User.objects.filter(phone__in=phones).delete()
            User.objects.filter(email__in=["festival@example.com", "brewery@example.com"]).delete()
        if User.objects.filter(phone="+14045550100").exists():
            self.stdout.write("Demo data already present. Use --reset to rebuild it.")
            return

        today = timezone.localdate()
        types = {t.key: t for t in DocumentType.objects.all()}
        admin = User.objects.create_user(
            phone="+14045550100",
            email="admin@example.com",
            full_name="Ops Admin",
            role=User.Role.ADMIN,
            is_staff=True,
            is_superuser=True,
            password="demo-admin-pass",
        )

        festival_owner = User.objects.create_user(
            phone="+14045550201",
            email="festival@example.com",
            full_name="Dana Rivers",
            role=User.Role.ORGANIZER,
            password="demo-organizer-pass",
        )
        festival = Organization.objects.create(
            owner_user=festival_owner, name="Piedmont Food Fest", org_type="festival"
        )
        brewery_owner = User.objects.create_user(
            phone="+14045550202",
            email="brewery@example.com",
            full_name="Sam Okafor",
            role=User.Role.ORGANIZER,
            password="demo-organizer-pass",
        )
        brewery = Organization.objects.create(
            owner_user=brewery_owner, name="Westside Brewing", org_type="brewery", recurring_host=True
        )

        fest = Event.objects.create(
            organization=festival,
            name="Spring Food Truck Festival",
            start_date=today + timedelta(days=12),
            end_date=today + timedelta(days=13),
            location_name="Piedmont Park",
            address="1320 Monroe Dr NE, Atlanta, GA",
            invite_code="SPRING",
        )
        req = ensure_requirement(fest)
        req.additional_insured_text = "Piedmont Food Fest LLC, its officers, agents, and employees"
        req.save()
        taproom = Event.objects.create(
            organization=brewery,
            name="Taproom truck rotation",
            is_standing=True,
            location_name="Westside Brewing taproom",
            invite_code="TAPRM1",
        )
        ensure_requirement(taproom)

        for phone, name, vtype, scenario in VENDORS:
            user = User.objects.create_user(phone=phone, full_name=f"Owner of {name}", role=User.Role.VENDOR)
            vendor = Vendor.objects.create(
                owner_user=user,
                business_name=name,
                vendor_type=vtype,
                service_area="Metro Atlanta",
                agent_name="Jordan Lee",
                agent_email="agent@example.com",
                agent_phone="+14045550999",
                insurer_name="Peachtree Mutual Insurance Co.",
            )
            self._documents(vendor, types, scenario, admin, today)
            if scenario == "missing":
                EventVendor.objects.get_or_create(event=fest, vendor=vendor)
                continue
            join_event(vendor, fest, user)
            if scenario in ("all_verified", "expiring_soon"):
                join_event(vendor, taproom, user)
        for event in (fest, taproom):
            recompute_for_event(event)
        self.stdout.write(
            self.style.SUCCESS(
                "Seeded. Admin +14045550100, organizers festival@example.com / brewery@example.com "
                "(password demo-organizer-pass), vendors +14045550101 to +14045550105. "
                "Without Twilio, login codes are printed to the server log."
            )
        )

    def _documents(self, vendor, types, scenario, admin, today):
        if scenario == "missing":
            return
        year = today + timedelta(days=300)
        limits = (500_000, 1_000_000) if scenario == "low_limits" else (1_000_000, 2_000_000)
        coi_end = today + timedelta(days=20) if scenario == "expiring_soon" else year
        coi = self._doc(
            vendor,
            types["coi"],
            sample_docs.coi(
                vendor.business_name,
                start=str(today - timedelta(days=60)),
                end=str(coi_end),
                occurrence=limits[0],
                aggregate=limits[1],
            ),
            today - timedelta(days=60),
            coi_end,
        )
        COIDetails.objects.create(
            document=coi,
            insurer_name="Peachtree Mutual Insurance Co.",
            naic_number="12345",
            policy_number="GL-2026-000123",
            gl_per_occurrence=limits[0],
            gl_aggregate=limits[1],
            auto_liability=1_000_000,
            workers_comp=True,
            additional_insureds=["Piedmont Food Fest LLC, its officers, agents, and employees"],
        )
        permits = [
            ("health_permit", "Health permit", "Fulton County Board of Health", "FCBH-88213"),
            ("fire_inspection", "Fire inspection", "Atlanta Fire Rescue Department", "AFRD-4471"),
            ("business_license", "Business license", "City of Atlanta", "BL-2026-5520"),
        ]
        for key, label, authority, number in permits:
            self._doc(
                vendor,
                types[key],
                sample_docs.permit(
                    label,
                    vendor.business_name,
                    authority,
                    number,
                    issued=str(today - timedelta(days=30)),
                    expires=str(year),
                ),
                today - timedelta(days=30),
                year,
            )
        pending_keys = {"health_permit"} if scenario == "pending_permit" else set()
        for doc in Document.objects.filter(vendor=vendor):
            if doc.document_type.key in pending_keys:
                continue
            doc.status = Document.Status.VERIFIED
            doc.verified_by = admin
            doc.verified_at = timezone.now()
            doc.verification_method = (
                Document.Method.AGENT_EMAIL if doc.document_type.key == "coi" else Document.Method.VISUAL
            )
            doc.save()

    def _doc(self, vendor, dtype, png, start, end):
        document = Document(
            vendor=vendor, document_type=dtype, content_type="image/png", original_filename="sample.png"
        )
        clean = _png(png)
        base = f"documents/{vendor.id}/{document.id}"
        document.file_path = default_storage.save(f"{base}/original.png", ContentFile(clean.content))
        document.thumbnail_path = default_storage.save(f"{base}/thumb.jpg", ContentFile(clean.thumbnail))
        fields = {"expiration_date": str(end)}
        fields["effective_date" if dtype.key == "coi" else "issue_date"] = str(start)
        document.extraction_status = Document.Extraction.SKIPPED
        document.confirmed = {**fields, "insured_name" if dtype.key == "coi" else "holder_name": vendor.business_name}
        document.effective_date = start
        document.expiration_date = end
        document.status = Document.Status.PENDING
        document.submitted_at = timezone.now() - timedelta(days=2)
        document.save()
        return document
