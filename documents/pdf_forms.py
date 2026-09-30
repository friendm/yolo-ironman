"""Read fillable PDF form fields from certificates of insurance, for free.

Agency software (and ACORD's own fillable ACORD 25) produces PDFs whose values
live in form fields such as ``GeneralLiability_EachOccurrence_LimitAmount_A``.
When those fields are present we map them straight to extraction fields and
skip the Claude call. Photos, scans, and flattened PDFs return nothing here and
fall through to Claude. The vendor still confirms every field either way.
"""

import io
import logging
import re
from datetime import datetime

from pypdf import PdfReader

log = logging.getLogger(__name__)

SOURCE = "pdf-form-fields"
VERSION = "2026-09-30.1"
CONFIDENCE = 0.95  # typed data, but the field-name mapping is a heuristic
LETTER_SUFFIX = re.compile(r"_([A-F])(\[\d+\])?$")


def read_fields(data):
    """Return {field name: value} for every filled form field, or {} if there are none or the PDF is unreadable."""
    try:
        fields = PdfReader(io.BytesIO(data)).get_fields() or {}
    except Exception:  # malformed, encrypted, or not a PDF: let Claude try instead
        log.info("Could not read PDF form fields", exc_info=True)
        return {}
    out = {}
    for name, field in fields.items():
        value = field.get("/V") if hasattr(field, "get") else None
        text = str(value).strip() if value is not None else ""
        if text and text not in ("/Off", "Off"):
            out[str(name)] = text
    return out


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _letter(name):
    match = LETTER_SUFFIX.search(name)
    return match.group(1) if match else None


def _find(fields, *required, avoid=(), letter=None):
    """First field whose normalized name contains every `required` part and no `avoid` part.

    Fields for insurer/coverage row "A" (or the requested letter) win over others.
    """
    matches = [
        name
        for name in fields
        if all(part in _norm(name) for part in required) and not any(part in _norm(name) for part in avoid)
    ]
    if not matches:
        return None
    preferred = letter or "A"
    matches.sort(key=lambda name: (0 if _letter(name) == preferred else 1 if _letter(name) is None else 2, name))
    return fields[matches[0]]


def _date(value):
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def extract_coi(data):
    """Map ACORD 25 style form fields to COI extraction fields. Returns None when too little is filled in."""
    from .extraction import COIExtraction, _money

    fields = read_fields(data)
    if not fields:
        return None
    gl_letter = _find(fields, "generalliability", "insurerletter")
    gl_letter = gl_letter.strip().upper()[:1] if gl_letter else "A"
    values = {
        "insured_name": _find(fields, "namedinsured", "fullname")
        or _find(fields, "insured", "name", avoid=("insurer",)),
        "insurer_name": _find(fields, "insurer", "fullname", letter=gl_letter),
        "naic_number": _find(fields, "insurer", "naic", letter=gl_letter),
        "policy_number": _find(fields, "generalliability", "policynumber"),
        "effective_date": _date(
            _find(fields, "generalliability", "effectivedate") or _find(fields, "policy", "effectivedate")
        ),
        "expiration_date": _date(
            _find(fields, "generalliability", "expirationdate") or _find(fields, "policy", "expirationdate")
        ),
        "gl_per_occurrence": _money(_find(fields, "eachoccurrence", avoid=("umbrella", "excess"))),
        "gl_aggregate": _money(_find(fields, "generalaggregate")),
        "auto_liability": _money(_find(fields, "combinedsinglelimit")),
        "liquor_liability": _money(_find(fields, "liquor", "limit")),
        "certificate_holder": _find(fields, "certificateholder", "fullname"),
    }
    # Only trust the form when the fields that drive event status are there.
    if not values["expiration_date"] or not (values["gl_per_occurrence"] or values["gl_aggregate"]):
        return None
    values = {key: value for key, value in values.items() if value not in (None, "")}
    values["confidence"] = {key: CONFIDENCE for key in values}
    return COIExtraction.model_validate(values).model_dump(mode="json")
