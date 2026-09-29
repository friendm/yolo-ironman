from django.contrib import admin

from .models import PhoneCode, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("phone", "email", "full_name", "role", "sms_opt_out", "created_at")
    list_filter = ("role", "sms_opt_out")
    search_fields = ("phone", "email", "full_name")
    exclude = ("password",)


@admin.register(PhoneCode)
class PhoneCodeAdmin(admin.ModelAdmin):
    list_display = ("phone", "expires_at", "attempts", "used_at")
    exclude = ("code_hash",)
