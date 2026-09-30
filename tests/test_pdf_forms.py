import io
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, RectangleObject, TextStringObject

from documents import extraction, pdf_forms
from documents.models import Document
from tests.conftest import login

pytestmark = pytest.mark.django_db  # the shared cache-clearing fixture uses the database cache
ACORD_FIELDS = {
    "F[0].P1[0].NamedInsured_FullName_A[0]": "Test Truck LLC",
    "F[0].P1[0].Insurer_FullName_A[0]": "Peachtree Mutual Insurance Co.",
    "F[0].P1[0].Insurer_NAICCode_A[0]": "12345",
    "F[0].P1[0].Insurer_FullName_B[0]": "Other Auto Insurer",
    "F[0].P1[0].Insurer_NAICCode_B[0]": "99999",
    "F[0].P1[0].GeneralLiability_InsurerLetterCode_A[0]": "A",
    "F[0].P1[0].Policy_GeneralLiability_PolicyNumberIdentifier_A[0]": "GL-2026-000123",
    "F[0].P1[0].Policy_GeneralLiability_EffectiveDate_A[0]": "01/15/2026",
    "F[0].P1[0].Policy_GeneralLiability_ExpirationDate_A[0]": "01/15/2027",
    "F[0].P1[0].GeneralLiability_EachOccurrence_LimitAmount_A[0]": "1,000,000",
    "F[0].P1[0].GeneralLiability_GeneralAggregate_LimitAmount_A[0]": "2,000,000",
    "F[0].P1[0].Vehicle_CombinedSingleLimit_LimitAmount_A[0]": "$1,000,000",
    "F[0].P1[0].ExcessUmbrella_EachOccurrence_LimitAmount_A[0]": "5,000,000",
    "F[0].P1[0].CertificateHolder_FullName_A[0]": "Piedmont Food Fest LLC",
    "F[0].P1[0].Unchecked_Box[0]": "/Off",
}


def fillable_pdf(fields):
    writer = PdfWriter()
    page = writer.add_blank_page(612, 792)
    refs = ArrayObject()
    for name, value in fields.items():
        widget = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/FT"): NameObject("/Tx"),
                NameObject("/T"): TextStringObject(name),
                NameObject("/V"): TextStringObject(value),
                NameObject("/Rect"): RectangleObject([0, 0, 10, 10]),
            }
        )
        refs.append(writer._add_object(widget))
    page[NameObject("/Annots")] = refs
    writer._root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/Fields"): refs})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_maps_acord_style_fields():
    result = pdf_forms.extract_coi(fillable_pdf(ACORD_FIELDS))
    assert result["insured_name"] == "Test Truck LLC"
    assert result["insurer_name"] == "Peachtree Mutual Insurance Co." and result["naic_number"] == "12345"
    assert result["policy_number"] == "GL-2026-000123"
    assert (result["effective_date"], result["expiration_date"]) == ("2026-01-15", "2027-01-15")
    assert (result["gl_per_occurrence"], result["gl_aggregate"]) == (1_000_000, 2_000_000)
    assert result["auto_liability"] == 1_000_000
    assert result["certificate_holder"] == "Piedmont Food Fest LLC"
    assert set(result["confidence"].values()) == {pdf_forms.CONFIDENCE}


def test_uses_the_insurer_named_on_the_general_liability_row():
    fields = {**ACORD_FIELDS, "F[0].P1[0].GeneralLiability_InsurerLetterCode_A[0]": "B"}
    result = pdf_forms.extract_coi(fillable_pdf(fields))
    assert result["insurer_name"] == "Other Auto Insurer" and result["naic_number"] == "99999"


@pytest.mark.parametrize(
    "data",
    [
        fillable_pdf({}),
        fillable_pdf({"F[0].NamedInsured_FullName_A[0]": "Test Truck LLC"}),  # no dates or limits
        fillable_pdf({k: v for k, v in ACORD_FIELDS.items() if "ExpirationDate" not in k}),
        b"%PDF-1.4 not really a pdf",
        b"",
    ],
    ids=["no-fields", "no-dates-or-limits", "no-expiration", "not-a-pdf", "empty"],
)
def test_returns_none_when_the_form_is_not_usable(data):
    assert pdf_forms.extract_coi(data) is None


def upload(client, key, content, name="coi.pdf"):
    return client.post(
        reverse("vendors:upload", args=[key]),
        {"file": SimpleUploadedFile(name, content, content_type="application/pdf")},
    )


def test_fillable_coi_is_read_without_calling_claude(client, vendor, types, settings):
    settings.ANTHROPIC_API_KEY = "test-key"
    login(client, vendor.owner_user)
    with mock.patch.object(extraction, "call_claude") as claude:
        response = upload(client, "coi", fillable_pdf(ACORD_FIELDS))
    claude.assert_not_called()
    doc = Document.objects.get()
    assert doc.extraction_status == "done" and doc.extraction_model == pdf_forms.SOURCE
    page = client.get(response.url).content.decode()
    assert 'value="Peachtree Mutual Insurance Co."' in page and 'value="1,000,000"' in page


def test_fillable_coi_works_without_an_api_key(client, vendor, types, settings):
    settings.ANTHROPIC_API_KEY = ""
    login(client, vendor.owner_user)
    upload(client, "coi", fillable_pdf(ACORD_FIELDS))
    assert Document.objects.get().extracted["gl_aggregate"] == 2_000_000


def test_flat_pdf_falls_back_to_claude(client, vendor, types, settings):
    settings.ANTHROPIC_API_KEY = "test-key"
    login(client, vendor.owner_user)
    with mock.patch.object(
        extraction, "call_claude", return_value=('{"insurer_name": "X"}', "claude-opus-5-5")
    ) as claude:
        upload(client, "coi", fillable_pdf({}))
    claude.assert_called_once()
    assert Document.objects.get().extraction_model == "claude-opus-5-5"


def test_only_certificates_of_insurance_are_read_this_way(client, vendor, types, settings):
    settings.ANTHROPIC_API_KEY = "test-key"
    login(client, vendor.owner_user)
    with mock.patch.object(extraction, "call_claude", return_value=("{}", "claude-opus-5-5")) as claude:
        upload(client, "health_permit", fillable_pdf(ACORD_FIELDS), name="permit.pdf")
    claude.assert_called_once()
