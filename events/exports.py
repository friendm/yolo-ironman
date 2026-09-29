import csv
import io
import zipfile

from django.core.files.storage import default_storage
from django.utils.text import slugify

from documents.models import Document
from ops import audit

from .status import current_documents


def vendors_csv(event):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Vendor", "Vendor type", "Participation", "Status", "Reasons", "Last updated"])
    for link in event.vendor_links.exclude(status="removed").select_related("vendor").order_by("vendor__business_name"):
        writer.writerow(
            [
                link.vendor.business_name,
                link.vendor.get_vendor_type_display(),
                link.get_status_display(),
                link.get_computed_status_display() if link.status == "joined" else "Not joined",
                "; ".join(link.status_reasons),
                link.updated_at.strftime("%Y-%m-%d %H:%M"),
            ]
        )
    return out.getvalue()


def verified_zip(event, actor):
    """ZIP of every joined vendor's verified documents relevant to this event. Each file is audited."""
    buffer = io.BytesIO()
    required = set(event.requirement.required_document_types.values_list("id", flat=True))
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for link in event.vendor_links.filter(status="joined").select_related("vendor"):
            folder = slugify(link.vendor.business_name) or str(link.vendor_id)
            for doc in current_documents(link.vendor).values():
                if doc.status != Document.Status.VERIFIED or doc.document_type_id not in required:
                    continue
                extension = doc.file_path.rsplit(".", 1)[-1]
                with default_storage.open(doc.file_path, "rb") as fh:
                    archive.writestr(f"{folder}/{doc.document_type.key}.{extension}", fh.read())
                audit.record(actor, "document_download", doc, vendor=doc.vendor_id, via="event_zip", event=event.id)
    return buffer.getvalue()
