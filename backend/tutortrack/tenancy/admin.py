from django.contrib import admin

from .models import Organisation


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "status", "default_currency", "created_at")
    search_fields = ("name", "slug")
    list_filter = ("status",)
