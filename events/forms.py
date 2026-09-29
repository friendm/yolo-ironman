from django import forms

from documents.forms import DateInput, MoneyField
from documents.models import DocumentType

from .models import Event, EventRequirement, Organization


class OrganizationForm(forms.ModelForm):
    email = forms.EmailField(label="Your email (for vendor alerts)", required=False)
    full_name = forms.CharField(label="Your name", required=False)
    password = forms.CharField(
        label="Password (optional, lets you sign in with email)",
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        min_length=10,
    )

    class Meta:
        model = Organization
        fields = ["name", "org_type", "recurring_host"]
        labels = {
            "name": "Organization name",
            "org_type": "Type",
            "recurring_host": "Recurring host mode (a standing vendor list, checked against today's date)",
        }


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ["name", "start_date", "end_date", "location_name", "address", "status"]
        labels = {"location_name": "Location", "status": "Status"}
        widgets = {"start_date": DateInput(), "end_date": DateInput()}

    def __init__(self, *args, standing=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.standing = standing
        if not standing:
            self.fields["start_date"].required = True
            self.fields["end_date"].required = True

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "The end date is before the start date.")
        return data


class RequirementForm(forms.ModelForm):
    required_document_types = forms.ModelMultipleChoiceField(
        queryset=DocumentType.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Required documents",
    )
    min_gl_per_occurrence = MoneyField(label="General liability minimum, each occurrence ($)", required=True)
    min_gl_aggregate = MoneyField(label="General liability minimum, aggregate ($)", required=True)

    class Meta:
        model = EventRequirement
        fields = [
            "required_document_types",
            "min_gl_per_occurrence",
            "min_gl_aggregate",
            "require_auto",
            "require_liquor",
            "additional_insured_text",
        ]
        labels = {
            "require_auto": "Require auto liability for food trucks",
            "require_liquor": "Require liquor liability",
            "additional_insured_text": "Additional insured wording (exactly as it must appear on the COI)",
        }
        widgets = {"additional_insured_text": forms.Textarea(attrs={"rows": 3})}


class VendorSearchForm(forms.Form):
    q = forms.CharField(label="Search vendors by business name", required=False, max_length=100)
