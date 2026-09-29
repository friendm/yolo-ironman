from django.contrib import admin

from .models import Vendor


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("business_name", "vendor_type", "owner_user", "deleted_at", "created_at")
    list_filter = ("vendor_type",)
    search_fields = ("business_name", "owner_user__phone")
