from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "channel", "template", "to", "status")
    list_filter = ("channel", "status", "template")
