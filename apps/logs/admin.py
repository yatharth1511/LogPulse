from django.contrib import admin

from .models import Host, LogEvent, PipelineRun, Service

admin.site.register(Service)
admin.site.register(Host)


@admin.register(PipelineRun)
class PipelineRunAdmin(admin.ModelAdmin):
    list_display = ("id", "source_file", "status", "started_at", "records_processed",
                    "records_loaded", "records_rejected")
    list_filter = ("status",)


@admin.register(LogEvent)
class LogEventAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "level", "service", "host", "status_code", "message")
    list_filter = ("level", "service")
    search_fields = ("message", "endpoint")
    raw_id_fields = ("pipeline_run",)
