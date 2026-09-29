from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor_user", "action", "entity", "entity_id")
    list_filter = ("action", "entity")
    search_fields = ("entity_id",)
