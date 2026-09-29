from django.contrib import admin

from .models import COIDetails, Document, DocumentType, ShareLink

admin.site.register([DocumentType, COIDetails, ShareLink])


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("vendor", "document_type", "status", "source", "expiration_date", "created_at")
    list_filter = ("status", "document_type", "source")
    search_fields = ("vendor__business_name",)
    raw_id_fields = ("vendor", "superseded_by", "event", "verified_by")
