from django.contrib import admin

from .models import AICertificateRequest, Event, EventRequirement, EventVendor, Organization, RequirementTemplate

admin.site.register([Organization, EventRequirement, AICertificateRequest, RequirementTemplate])


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "start_date", "end_date", "invite_code", "status")
    search_fields = ("name", "invite_code")


@admin.register(EventVendor)
class EventVendorAdmin(admin.ModelAdmin):
    list_display = ("event", "vendor", "status", "computed_status", "updated_at")
    list_filter = ("status", "computed_status")
