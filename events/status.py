"""The red / yellow / green rule for a vendor at an event.

Green: every required document is verified, unexpired on the event's end date,
and the COI meets every minimum.
Yellow: everything is uploaded but something is pending verification or expires
within 14 days after the event.
Red: anything required is missing, rejected, expired before the event ends, or
below a minimum. Reasons list each problem in plain words.
"""

from dataclasses import dataclass, field
from datetime import timedelta

from documents.models import Document

GRACE_DAYS = 14


@dataclass
class Evaluation:
    red: list = field(default_factory=list)
    yellow: list = field(default_factory=list)

    @property
    def color(self):
        if self.red:
            return "red"
        if self.yellow:
            return "yellow"
        return "green"

    @property
    def reasons(self):
        return self.red + self.yellow


def money(value):
    return f"${value:,}"


def current_documents(vendor):
    """The latest submitted, non-superseded document per document type."""
    docs = {}
    for doc in Document.objects.current().filter(vendor=vendor).select_related("document_type", "coi"):
        existing = docs.get(doc.document_type_id)
        if existing is None or doc.created_at > existing.created_at:
            docs[doc.document_type_id] = doc
    return docs


def check_coi(doc, requirement, vendor, result):
    coi = getattr(doc, "coi", None)
    if coi is None:
        result.red.append("Insurance limits are missing from the COI")
        return
    checks = [
        (coi.gl_per_occurrence, requirement.min_gl_per_occurrence, "General liability per occurrence"),
        (coi.gl_aggregate, requirement.min_gl_aggregate, "General liability aggregate"),
    ]
    for actual, minimum, label in checks:
        if minimum and (actual or 0) < minimum:
            shown = money(actual) if actual else "not listed"
            result.red.append(f"{label} is {shown}, below the {money(minimum)} minimum")
    if requirement.require_auto and vendor.vendor_type == "food_truck" and not coi.auto_liability:
        result.red.append("Auto liability is required for food trucks and is not on the COI")
    if requirement.require_liquor and not coi.liquor_liability:
        result.red.append("Liquor liability is required and is not on the COI")


def evaluate(event, vendor, docs=None):
    requirement = getattr(event, "requirement", None)
    result = Evaluation()
    if requirement is None:
        return result
    docs = current_documents(vendor) if docs is None else docs
    through = event.evaluation_date()
    for dtype in requirement.required_document_types.all():
        doc = docs.get(dtype.id)
        label = dtype.label
        if doc is None:
            result.red.append(f"{label} is missing")
            continue
        if doc.status == Document.Status.REJECTED:
            reason = f": {doc.rejection_reason}" if doc.rejection_reason else ""
            result.red.append(f"{label} was rejected{reason}")
            continue
        expires = doc.expiration_date
        if doc.status == Document.Status.EXPIRED or (dtype.has_expiration and expires and expires < through):
            when = f" on {expires:%b %-d, %Y}" if expires else ""
            result.red.append(f"{label} expires{when}, before the event ends")
            continue
        if dtype.is_coi:
            check_coi(doc, requirement, vendor, result)
        if doc.status == Document.Status.PENDING:
            result.yellow.append(f"{label} is pending verification")
        if dtype.has_expiration and not expires:
            result.yellow.append(f"{label} has no expiration date on file")
        elif dtype.has_expiration and expires <= through + timedelta(days=GRACE_DAYS):
            result.yellow.append(f"{label} expires {expires:%b %-d, %Y}, within 14 days after the event")
    return result
