from rest_framework import serializers

from .models import LogEvent, Service


class LogEventSerializer(serializers.ModelSerializer):
    service = serializers.CharField(source="service.name", read_only=True)
    host = serializers.CharField(source="host.name", read_only=True)

    class Meta:
        model = LogEvent
        fields = [
            "id", "timestamp", "level", "service", "host", "message", "http_method", "endpoint",
            "status_code", "response_time_ms", "ip_address", "source_format", "raw",
            "pipeline_run", "created_at",
        ]
        read_only_fields = fields


class ServiceSerializer(serializers.ModelSerializer):
    log_count = serializers.IntegerField(read_only=True)
    error_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Service
        fields = ["id", "name", "log_count", "error_count", "created_at"]
        read_only_fields = fields
