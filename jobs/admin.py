from django.contrib import admin

from .models import FetchRun, Job, Source, SourceRunResult


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("company_name", "adapter_key", "active", "last_status", "last_success_at")
    list_filter = ("adapter_key", "active", "last_status")
    search_fields = ("company_name",)


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("title", "company_name", "location", "status", "first_seen_at")
    list_filter = ("status", "summary_status", "source")
    search_fields = ("title", "company_name", "location")


class ResultInline(admin.TabularInline):
    model = SourceRunResult
    extra = 0
    can_delete = False


@admin.register(FetchRun)
class FetchRunAdmin(admin.ModelAdmin):
    list_display = ("id", "trigger_type", "status", "started_at", "jobs_created", "jobs_updated")
    inlines = [ResultInline]
