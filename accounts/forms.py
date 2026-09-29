from django import forms

from common.phone import InvalidPhone, normalize_phone

from .models import User


class PhoneForm(forms.Form):
    phone = forms.CharField(
        label="Mobile phone number",
        max_length=20,
        widget=forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel", "placeholder": "(404) 555-0123"}),
    )

    def clean_phone(self):
        try:
            return normalize_phone(self.cleaned_data["phone"])
        except InvalidPhone as exc:
            raise forms.ValidationError(str(exc)) from exc


class CodeForm(forms.Form):
    code = forms.CharField(
        label="6-digit code",
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "pattern": "[0-9]{6}"}),
    )


class EmailForm(forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={"autocomplete": "email"}))


class EmailPasswordForm(forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class RoleForm(forms.Form):
    role = forms.ChoiceField(
        choices=[(User.Role.VENDOR, "I'm a vendor"), (User.Role.ORGANIZER, "I organize events")],
        widget=forms.RadioSelect,
    )
