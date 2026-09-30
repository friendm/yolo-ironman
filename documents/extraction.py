"""AI extraction of document fields with Claude.

Extraction only pre-fills forms; it never marks anything verified. On any
failure the raw response is saved and the vendor sees an empty form.
"""

import base64
import json
import logging
import re
from datetime import date

from django.conf import settings
from django.core.files.storage import default_storage
from pydantic import BaseModel, ValidationError, field_validator

log = logging.getLogger(__name__)
PROMPT_VERSION = "2026-09-29.1"
LOW_CONFIDENCE = 0.7


class _Base(BaseModel):
    confidence: dict[str, float] = {}

    @field_validator("confidence", mode="before")
    @classmethod
    def clean_confidence(cls, value):
        if not isinstance(value, dict):
            return {}
        out = {}
        for key, score in value.items():
            try:
                out[str(key)] = max(0.0, min(1.0, float(score)))
            except (TypeError, ValueError):
                continue
        return out


def _money(value):
    """Accept 1000000, "1,000,000", "$1M", "2 million"; return whole dollars or None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).lower().replace(",", "").replace("$", "").strip()
    match = re.match(r"^(\d+(?:\.\d+)?)\s*(m|mm|million|k|thousand)?$", text)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or ""
    if unit in ("m", "mm", "million"):
        number *= 1_000_000
    elif unit in ("k", "thousand"):
        number *= 1_000
    return int(number)


class COIExtraction(_Base):
    insurer_name: str | None = None
    naic_number: str | None = None
    insured_name: str | None = None
    policy_number: str | None = None
    policy_types: list[str] = []
    effective_date: date | None = None
    expiration_date: date | None = None
    gl_per_occurrence: int | None = None
    gl_aggregate: int | None = None
    auto_liability: int | None = None
    workers_comp: bool | None = None
    liquor_liability: int | None = None
    certificate_holder: str | None = None
    additional_insured_text: str | None = None

    @field_validator("gl_per_occurrence", "gl_aggregate", "auto_liability", "liquor_liability", mode="before")
    @classmethod
    def parse_money(cls, value):
        return _money(value)


class PermitExtraction(_Base):
    issuing_authority: str | None = None
    permit_number: str | None = None
    holder_name: str | None = None
    issue_date: date | None = None
    expiration_date: date | None = None


def schema_for(document_type):
    return COIExtraction if document_type.key == "coi" else PermitExtraction


SYSTEM_PROMPT = """You read documents that event vendors upload: certificates of insurance (ACORD 25 and similar), \
health permits, fire inspection certificates, and business licenses.

Reply with a single JSON object and nothing else: no prose, no code fences.
Use exactly the keys in this JSON schema; use null for anything not shown on the document:
{schema}

Rules:
- Dates are ISO format YYYY-MM-DD.
- Dollar limits are whole numbers of US dollars (1000000, not "$1M").
- "confidence" maps each key you filled to a number from 0 to 1 for how sure you are it is read correctly.
- Never guess a value that is not printed on the document."""


def strip_fences(text):
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def parse_response(text, document_type):
    """Return a dict of validated fields, or None if the reply can't be trusted."""
    model = schema_for(document_type)
    try:
        data = json.loads(strip_fences(text))
        if not isinstance(data, dict):
            return None
        return model.model_validate(data).model_dump(mode="json")
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
        return None


def content_block(document):
    with default_storage.open(document.file_path, "rb") as fh:
        data = base64.standard_b64encode(fh.read()).decode("ascii")
    if document.content_type == "application/pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
    return {"type": "image", "source": {"type": "base64", "media_type": document.content_type, "data": data}}


def call_claude(document):
    import anthropic

    schema = schema_for(document.document_type).model_json_schema()
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.beta.messages.create(
        model=settings.EXTRACTION_MODEL,
        max_tokens=4000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low"},
        system=SYSTEM_PROMPT.format(schema=json.dumps(schema)),
        messages=[
            {
                "role": "user",
                "content": [
                    content_block(document),
                    {"type": "text", "text": f"Extract the fields from this {document.document_type.label}."},
                ],
            }
        ],
    )
    if response.stop_reason == "refusal":
        return "", response.model
    text = "".join(block.text for block in response.content if block.type == "text")
    return text, response.model


def run_extraction(document):
    """Fill document.extracted. Never raises: failures leave an empty form."""
    from .models import Document

    if _read_pdf_form(document):
        return document
    document.extraction_prompt_version = PROMPT_VERSION
    if not settings.ANTHROPIC_API_KEY:
        document.extraction_status = Document.Extraction.SKIPPED
        document.save(update_fields=["extraction_status", "extraction_prompt_version", "updated_at"])
        return document
    try:
        text, model_name = call_claude(document)
    except Exception as exc:
        log.exception("Extraction call failed for %s", document.id)
        document.extraction_status = Document.Extraction.FAILED
        document.extraction_raw = f"error: {exc}"[:5000]
        document.extraction_model = settings.EXTRACTION_MODEL
        document.save()
        return document
    document.extraction_raw = text[:20000]
    document.extraction_model = model_name
    parsed = parse_response(text, document.document_type)
    if parsed is None:
        document.extraction_status = Document.Extraction.FAILED
        document.extracted = {}
    else:
        document.extraction_status = Document.Extraction.DONE
        document.extracted = parsed
    document.save()
    return document


def _read_pdf_form(document):
    """Fillable COI PDFs carry their values as form fields: read those for free instead of calling Claude."""
    from . import pdf_forms
    from .models import Document

    if document.document_type.key != "coi" or document.content_type != "application/pdf":
        return False
    try:
        with default_storage.open(document.file_path, "rb") as fh:
            fields = pdf_forms.extract_coi(fh.read())
    except Exception:
        log.exception("Reading PDF form fields failed for %s", document.id)
        return False
    if not fields:
        return False
    document.extracted = fields
    document.extraction_status = Document.Extraction.DONE
    document.extraction_model = pdf_forms.SOURCE
    document.extraction_prompt_version = pdf_forms.VERSION
    document.extraction_raw = ""
    document.save()
    return True


def low_confidence_fields(extracted):
    scores = (extracted or {}).get("confidence") or {}
    return {key for key, score in scores.items() if score < LOW_CONFIDENCE}
