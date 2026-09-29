import json
from datetime import timedelta
from unittest import mock

import pytest
from django.urls import reverse

from documents import extraction
from documents.models import Document
from tests.conftest import heic_bytes, login, png_upload

pytestmark = pytest.mark.django_db


def upload(client, key, file):
    return client.post(reverse("vendors:upload", args=[key]), {"file": file})


def test_vendor_completes_all_four_documents_with_seed_files(client, vendor, types):
    login(client, vendor.owner_user)
    expires = "2027-06-30"
    for key in ("coi", "health_permit", "fire_inspection", "business_license"):
        response = upload(client, key, png_upload(f"{key}.png"))
        assert response.status_code == 302
        confirm_url = response.url
        page = client.get(confirm_url)
        assert page.status_code == 200
        data = {"expiration_date": expires}
        if key == "coi":
            data.update({"gl_per_occurrence": "1,000,000", "gl_aggregate": "$2M", "auto_liability": "1000000"})
        response = client.post(confirm_url, data)
        assert response.status_code == 302, page.content
    docs = Document.objects.filter(vendor=vendor)
    assert docs.count() == 4 and set(docs.values_list("status", flat=True)) == {"pending"}
    coi = docs.get(document_type__key="coi").coi
    assert (coi.gl_per_occurrence, coi.gl_aggregate) == (1_000_000, 2_000_000)
    home = client.get(reverse("vendors:home"))
    assert b"4 documents pending" in home.content


def test_unreadable_file_produces_empty_editable_form_not_error(client, vendor, types, settings):
    settings.ANTHROPIC_API_KEY = "test-key"
    login(client, vendor.owner_user)
    with mock.patch.object(extraction, "call_claude", return_value=("I can't read this image, sorry.", "m")):
        response = upload(client, "health_permit", png_upload())
    doc = Document.objects.get()
    assert doc.extraction_status == "failed" and doc.extracted == {}
    assert doc.extraction_raw.startswith("I can't read")
    page = client.get(response.url)
    assert page.status_code == 200
    assert b"couldn't read this one automatically" in page.content
    assert b'name="expiration_date"' in page.content


def test_api_error_also_produces_empty_form(client, vendor, types, settings):
    settings.ANTHROPIC_API_KEY = "test-key"
    login(client, vendor.owner_user)
    with mock.patch.object(extraction, "call_claude", side_effect=RuntimeError("boom")):
        response = upload(client, "coi", png_upload())
    assert client.get(response.url).status_code == 200
    assert Document.objects.get().extraction_status == "failed"


def test_extraction_prefills_and_flags_low_confidence(client, vendor, types, settings):
    settings.ANTHROPIC_API_KEY = "test-key"
    reply = (
        "```json\n"
        + json.dumps(
            {
                "insurer_name": "Peachtree Mutual",
                "gl_per_occurrence": "$1,000,000",
                "gl_aggregate": 2000000,
                "expiration_date": "2027-01-15",
                "insured_name": "Test Truck",
                "confidence": {"insurer_name": 0.95, "gl_aggregate": 0.4},
            }
        )
        + "\n```"
    )
    login(client, vendor.owner_user)
    with mock.patch.object(extraction, "call_claude", return_value=(reply, "claude-opus-5-5")):
        response = upload(client, "coi", png_upload())
    doc = Document.objects.get()
    assert doc.extraction_status == "done"
    assert doc.extracted["gl_per_occurrence"] == 1_000_000
    assert doc.extraction_model == "claude-opus-5-5" and doc.extraction_prompt_version == extraction.PROMPT_VERSION
    page = client.get(response.url).content.decode()
    assert 'value="Peachtree Mutual"' in page
    assert "field low" in page  # gl_aggregate flagged


def test_reading_page_refreshes_without_javascript(client, vendor, types):
    login(client, vendor.owner_user)
    with mock.patch("documents.services.queue_extraction"):
        response = upload(client, "coi", png_upload())
    page = client.get(response.url).content.decode()
    assert "Reading your document..." in page
    assert '<meta http-equiv="refresh" content="3">' in page


def test_upload_validation(client, vendor, types, settings):
    from django.core.files.uploadedfile import SimpleUploadedFile

    login(client, vendor.owner_user)
    bad = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")
    response = upload(client, "coi", bad)
    assert response.status_code == 200 and b"Upload a PDF, JPG, PNG, or HEIC file." in response.content
    fake_pdf = SimpleUploadedFile("x.pdf", b"not a pdf at all", content_type="application/pdf")
    assert upload(client, "coi", fake_pdf).status_code == 200
    settings.MAX_UPLOAD_BYTES = 8
    big = SimpleUploadedFile("big.pdf", b"%PDF-1.4 more than eight bytes", content_type="application/pdf")
    response = upload(client, "coi", big)
    assert b"larger than 15 MB" in response.content
    assert Document.objects.count() == 0


def test_heic_is_converted_to_jpg(client, vendor, types):
    from django.core.files.uploadedfile import SimpleUploadedFile

    login(client, vendor.owner_user)
    response = upload(
        client, "health_permit", SimpleUploadedFile("IMG_0001.HEIC", heic_bytes(), content_type="image/heic")
    )
    assert response.status_code == 302
    doc = Document.objects.get()
    assert doc.file_path.endswith(".jpg") and doc.content_type == "image/jpeg" and doc.thumbnail_path


def test_new_upload_supersedes_old_one_and_keeps_history(client, vendor, types):
    from tests.conftest import make_doc

    old = make_doc(vendor, types["health_permit"])
    login(client, vendor.owner_user)
    response = upload(client, "health_permit", png_upload())
    old.refresh_from_db()
    assert old.superseded_by is None  # still current until the new one is submitted
    client.post(response.url, {"expiration_date": "2027-01-01"})
    old.refresh_from_db()
    new = Document.objects.exclude(pk=old.pk).get()
    assert old.superseded_by == new and new.status == "pending"
    assert Document.objects.filter(vendor=vendor).count() == 2


def test_confirm_rejects_expiration_before_start(client, vendor, types):
    login(client, vendor.owner_user)
    response = upload(client, "health_permit", png_upload())
    page = client.post(response.url, {"issue_date": "2027-01-01", "expiration_date": "2026-01-01"})
    assert page.status_code == 200 and b"before the start date" in page.content


@pytest.mark.parametrize(
    "text,ok",
    [
        ('{"issuing_authority": "Fulton County", "expiration_date": "2027-02-28"}', True),
        ('Sure! ```json\n{"permit_number": "A1"}\n```', True),
        ('Here you go: {"permit_number": "A1"} hope that helps', True),
        ('{"expiration_date": "not a date"}', False),
        ("not json", False),
        ("[1, 2]", False),
    ],
)
def test_parse_response_is_defensive(types, text, ok):
    assert (extraction.parse_response(text, types["health_permit"]) is not None) is ok


def test_money_parsing():
    assert extraction._money("$1,000,000") == 1_000_000
    assert extraction._money("2M") == 2_000_000
    assert extraction._money("500k") == 500_000
    assert extraction._money("lots") is None


def test_vendor_home_status_card_messages(client, vendor, types, today):
    from tests.conftest import complete_vendor, make_doc

    login(client, vendor.owner_user)
    assert b"4 documents to add" in client.get(reverse("vendors:home")).content
    complete_vendor(vendor, types)
    assert b"Verified" in client.get(reverse("vendors:home")).content
    make_doc(vendor, types["health_permit"], expires=today + timedelta(days=21))
    assert b"Health permit expires in 21 days" in client.get(reverse("vendors:home")).content
