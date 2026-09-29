from django import forms

from common.phone import InvalidPhone, normalize_phone
from common.uploads import clean_upload

from .models import Vendor


class VendorBasicsForm(forms.ModelForm):
    photo = forms.FileField(
        required=False,
        label="Photo of your truck or setup (optional)",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*"}),
    )

    class Meta:
        model = Vendor
        fields = [
            "business_name",
            "vendor_type",
            "service_area",
            "description",
            "agent_name",
            "agent_email",
            "agent_phone",
            "insurer_name",
        ]
        labels = {
            "service_area": "Where you work",
            "description": "What you serve or offer (optional)",
            "agent_name": "Insurance agent or insurer contact",
            "agent_email": "Agent email",
            "agent_phone": "Agent phone",
            "insurer_name": "Insurance company (optional)",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "agent_phone": forms.TextInput(attrs={"inputmode": "tel"}),
            "service_area": forms.TextInput(attrs={"placeholder": "Metro Atlanta"}),
        }

    def clean_agent_phone(self):
        raw = self.cleaned_data.get("agent_phone")
        if not raw:
            return ""
        try:
            return normalize_phone(raw)
        except InvalidPhone as exc:
            raise forms.ValidationError(str(exc)) from exc

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if not photo:
            return None
        clean = clean_upload(photo)
        if clean.extension == "pdf":
            raise forms.ValidationError("Upload a photo (JPG, PNG, or HEIC).")
        return clean


class JoinCodeForm(forms.Form):
    code = forms.CharField(
        label="Invite code",
        max_length=12,
        widget=forms.TextInput(attrs={"autocapitalize": "characters", "autocomplete": "off"}),
    )

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


class DeleteAccountForm(forms.Form):
    confirm = forms.CharField(label="Type DELETE to confirm")

    def clean_confirm(self):
        if self.cleaned_data["confirm"].strip().upper() != "DELETE":
            raise forms.ValidationError("Type DELETE to confirm.")
        return True
