from django.conf import settings
from rest_framework import serializers

from apps.logs.models import PipelineRun


class PipelineRunSerializer(serializers.ModelSerializer):
    duration_seconds = serializers.FloatField(read_only=True)

    class Meta:
        model = PipelineRun
        fields = [
            "id", "source_file", "status", "started_at", "finished_at", "duration_seconds",
            "records_processed", "records_loaded", "records_rejected", "records_duplicate",
            "reject_reasons", "error_message",
        ]
        read_only_fields = fields


class PipelineUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    service = serializers.CharField(required=False, allow_blank=True, max_length=100)
    host = serializers.CharField(required=False, allow_blank=True, max_length=100)

    def validate_file(self, value):
        limit = settings.LOGPULSE_MAX_UPLOAD_MB * 1024 * 1024
        if value.size > limit:
            raise serializers.ValidationError(f"File exceeds the {settings.LOGPULSE_MAX_UPLOAD_MB} MB limit.")
        return value
