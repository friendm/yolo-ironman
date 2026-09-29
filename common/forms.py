from django.forms.renderers import TemplatesSetting


class Renderer(TemplatesSetting):
    """Labels above inputs, inline errors: every form uses these two templates."""

    form_template_name = "forms/form.html"
    field_template_name = "forms/field.html"
