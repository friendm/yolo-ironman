from django.db import migrations

COI_SCHEMA = {
    "fields": [
        "insurer_name",
        "naic_number",
        "insured_name",
        "policy_number",
        "policy_types",
        "effective_date",
        "expiration_date",
        "gl_per_occurrence",
        "gl_aggregate",
        "auto_liability",
        "workers_comp",
        "liquor_liability",
        "certificate_holder",
        "additional_insured_text",
    ],
    "confidence": "per field, 0 to 1",
}
PERMIT_SCHEMA = {
    "fields": ["issuing_authority", "permit_number", "holder_name", "issue_date", "expiration_date"],
    "confidence": "per field, 0 to 1",
}
TYPES = [
    ("coi", "Certificate of insurance", COI_SCHEMA, 1),
    ("health_permit", "Health permit", PERMIT_SCHEMA, 2),
    ("fire_inspection", "Fire inspection", PERMIT_SCHEMA, 3),
    ("business_license", "Business license", PERMIT_SCHEMA, 4),
]


def seed(apps, schema_editor):
    DocumentType = apps.get_model("documents", "DocumentType")
    for key, label, schema, order in TYPES:
        DocumentType.objects.update_or_create(
            key=key,
            defaults={"label": label, "has_expiration": True, "extraction_schema": schema, "sort_order": order},
        )


class Migration(migrations.Migration):
    dependencies = [("documents", "0002_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
