from django import forms
from django.core.exceptions import ValidationError

from common.uploads import clean_upload

from .extraction import _money


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class MoneyField(forms.CharField):
    """Whole US dollars; accepts 1000000, 1,000,000, $1M."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        super().__init__(widget=forms.TextInput(attrs={"inputmode": "numeric", "placeholder": "1,000,000"}), **kwargs)

    def prepare_value(self, value):
        if isinstance(value, int):
            return f"{value:,}"
        return value

    def to_python(self, value):
        value = super().to_python(value)
        if not value:
            return None
        amount = _money(value)
        if amount is None:
            raise ValidationError("Enter a dollar amount, like 1,000,000.")
        return amount


class UploadForm(forms.Form):
    file = forms.FileField(
        label="Photo or PDF",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*,application/pdf,.heic"}),
    )

    def clean_file(self):
        return clean_upload(self.cleaned_data["file"])


class BaseConfirmForm(forms.Form):
    def clean(self):
        data = super().clean()
        start = data.get("effective_date") or data.get("issue_date")
        end = data.get("expiration_date")
        if start and end and end < start:
            self.add_error("expiration_date", "The expiration date is before the start date.")
        return data

    def json_data(self):
        out = {}
        for key, value in self.cleaned_data.items():
            out[key] = value.isoformat() if hasattr(value, "isoformat") else value
        return out


class COIConfirmForm(BaseConfirmForm):
    insured_name = forms.CharField(label="Insured (your business name on the COI)", required=False)
    insurer_name = forms.CharField(label="Insurance company", required=False)
    naic_number = forms.CharField(label="NAIC number", required=False)
    policy_number = forms.CharField(label="General liability policy number", required=False)
    effective_date = forms.DateField(label="Policy start date", widget=DateInput(), required=False)
    expiration_date = forms.DateField(label="Policy expiration date", widget=DateInput())
    gl_per_occurrence = MoneyField(label="General liability, each occurrence ($)")
    gl_aggregate = MoneyField(label="General liability, aggregate ($)")
    auto_liability = MoneyField(label="Auto liability, combined single limit ($)")
    liquor_liability = MoneyField(label="Liquor liability ($)")
    workers_comp = forms.BooleanField(label="Workers' compensation on this certificate", required=False)
    additional_insured_text = forms.CharField(
        label="Additional insureds (one per line)", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )


class PermitConfirmForm(BaseConfirmForm):
    holder_name = forms.CharField(label="Name on the document", required=False)
    issuing_authority = forms.CharField(label="Issued by", required=False)
    permit_number = forms.CharField(label="Permit or license number", required=False)
    issue_date = forms.DateField(label="Issue date", widget=DateInput(), required=False)
    expiration_date = forms.DateField(label="Expiration date", widget=DateInput(), required=False)

    def __init__(self, *args, document_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        if document_type is not None and document_type.has_expiration:
            self.fields["expiration_date"].required = True


def confirm_form_class(document_type):
    return COIConfirmForm if document_type.key == "coi" else PermitConfirmForm


def build_confirm_form(document, data=None, initial_source=None, prefix=None, low=()):
    """Confirm form for a document, prefilled from confirmed fields or the AI extraction.

    Fields named in `low` (extraction confidence under 0.7) are flagged yellow.
    """
    cls = confirm_form_class(document.document_type)
    source = initial_source if initial_source is not None else (document.confirmed or document.extracted or {})
    initial = {key: source.get(key) for key in cls.base_fields if source.get(key) not in (None, "")}
    kwargs = {"data": data, "initial": initial, "prefix": prefix}
    if cls is PermitConfirmForm:
        kwargs["document_type"] = document.document_type
    form = cls(**kwargs)
    for name in low:
        if name in form.fields:
            form.fields[name].low = True
    return form
