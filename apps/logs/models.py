from django.db import models
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone


class Service(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Host(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PipelineRun(models.Model):
    """One execution of the ETL pipeline for one source file."""

    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        SUCCESS = "SUCCESS", "Success"
        PARTIAL = "PARTIAL", "Completed with rejects"
        FAILED = "FAILED", "Failed"

    source_file = models.CharField(max_length=500)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    records_processed = models.PositiveIntegerField(default=0)  # non-blank lines read
    records_loaded = models.PositiveIntegerField(default=0)
    records_rejected = models.PositiveIntegerField(default=0)
    records_duplicate = models.PositiveIntegerField(default=0)
    reject_reasons = models.JSONField(default=dict, blank=True)  # {"invalid_timestamp": 3, ...}
    error_message = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["-started_at"], name="pipelinerun_started_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(finished_at__isnull=True) | Q(finished_at__gte=F("started_at")),
                name="pipelinerun_finished_after_started",
            ),
        ]

    def __str__(self):
        return f"Run #{self.pk} {self.source_file} [{self.status}]"

    @property
    def duration_seconds(self):
        if self.finished_at is None:
            return None
        return round((self.finished_at - self.started_at).total_seconds(), 3)


class LogEvent(models.Model):
    class Level(models.TextChoices):
        DEBUG = "DEBUG", "Debug"
        INFO = "INFO", "Info"
        WARNING = "WARNING", "Warning"
        ERROR = "ERROR", "Error"
        CRITICAL = "CRITICAL", "Critical"

    timestamp = models.DateTimeField()
    level = models.CharField(max_length=10, choices=Level.choices)
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="events")
    host = models.ForeignKey(Host, on_delete=models.PROTECT, related_name="events")
    message = models.TextField()
    http_method = models.CharField(max_length=10, blank=True, default="")
    endpoint = models.CharField(max_length=512, blank=True, default="")
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response_time_ms = models.FloatField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)  # PostgreSQL inet
    source_format = models.CharField(max_length=10, blank=True, default="")
    raw = models.TextField(blank=True, default="")
    fingerprint = models.CharField(max_length=64, unique=True)  # sha256 hex, used for deduplication
    pipeline_run = models.ForeignKey(
        PipelineRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="events"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["timestamp"], name="logevent_ts_idx"),
            models.Index(fields=["level", "timestamp"], name="logevent_level_ts_idx"),
            models.Index(fields=["service", "timestamp"], name="logevent_service_ts_idx"),
            models.Index(fields=["status_code"], name="logevent_status_idx"),
            models.Index(fields=["endpoint"], name="logevent_endpoint_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(status_code__isnull=True) | Q(status_code__gte=100, status_code__lte=599),
                name="logevent_status_code_range",
            ),
            models.CheckConstraint(
                condition=Q(response_time_ms__isnull=True) | Q(response_time_ms__gte=0),
                name="logevent_response_time_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(level__in=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]),
                name="logevent_level_valid",
            ),
        ]

    def __str__(self):
        return f"[{self.level}] {self.service_id} {self.message[:60]}"

    @property
    def is_error(self):
        return self.level in (self.Level.ERROR, self.Level.CRITICAL)

    def get_absolute_url(self):
        return reverse("logs:detail", args=[self.pk])
