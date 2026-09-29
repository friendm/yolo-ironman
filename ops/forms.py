from django import forms

from documents.models import Document, DocumentType
from events.models import RequirementTemplate


class VerifyForm(forms.Form):
    decision = forms.ChoiceField(choices=[("verify", "Verify"), ("reject", "Reject")], widget=forms.RadioSelect)
    method = forms.ChoiceField(
        label="Verification method", choices=[("", "Choose a method")] + list(Document.Method.choices), required=False
    )
    notes = forms.CharField(label="Reviewer notes", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    reason = forms.CharField(
        label="Rejection reason (texted to the vendor)", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def clean(self):
        data = super().clean()
        if data.get("decision") == "verify" and not data.get("method"):
            self.add_error("method", "Pick how you verified this document.")
        if data.get("decision") == "reject" and not data.get("reason"):
            self.add_error("reason", "Give the vendor a reason.")
        return data


class DirectorySearchForm(forms.Form):
    q = forms.CharField(label="Search", required=False, max_length=100)


class DocumentTypeForm(forms.ModelForm):
    class Meta:
        model = DocumentType
        fields = ["key", "label", "has_expiration", "sort_order", "extraction_schema"]


class RequirementTemplateForm(forms.ModelForm):
    required_document_types = forms.ModelMultipleChoiceField(
        queryset=DocumentType.objects.all(), widget=forms.CheckboxSelectMultiple, required=False
    )

    class Meta:
        model = RequirementTemplate
        fields = [
            "name",
            "is_default",
            "required_document_types",
            "min_gl_per_occurrence",
            "min_gl_aggregate",
            "require_auto",
            "require_liquor",
        ]


class AuditFilterForm(forms.Form):
    entity_id = forms.UUIDField(label="Vendor or document id", required=False)
    action = forms.CharField(required=False, max_length=60)
