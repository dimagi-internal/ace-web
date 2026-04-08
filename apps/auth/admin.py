from django.contrib import admin

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "display_name", "is_active", "is_staff", "created_at")
    search_fields = ("email", "display_name")
    readonly_fields = ("created_at", "updated_at")
