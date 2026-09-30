import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Service",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Host",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="PipelineRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_file", models.CharField(max_length=500)),
                ("status", models.CharField(
                    choices=[("RUNNING", "Running"), ("SUCCESS", "Success"),
                             ("PARTIAL", "Completed with rejects"), ("FAILED", "Failed")],
                    default="RUNNING", max_length=10)),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("records_processed", models.PositiveIntegerField(default=0)),
                ("records_loaded", models.PositiveIntegerField(default=0)),
                ("records_rejected", models.PositiveIntegerField(default=0)),
                ("records_duplicate", models.PositiveIntegerField(default=0)),
                ("reject_reasons", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
            ],
        ),
        migrations.CreateModel(
            name="LogEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("timestamp", models.DateTimeField()),
                ("level", models.CharField(
                    choices=[("DEBUG", "Debug"), ("INFO", "Info"), ("WARNING", "Warning"),
                             ("ERROR", "Error"), ("CRITICAL", "Critical")],
                    max_length=10)),
                ("message", models.TextField()),
                ("http_method", models.CharField(blank=True, default="", max_length=10)),
                ("endpoint", models.CharField(blank=True, default="", max_length=512)),
                ("status_code", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("response_time_ms", models.FloatField(blank=True, null=True)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("source_format", models.CharField(blank=True, default="", max_length=10)),
                ("raw", models.TextField(blank=True, default="")),
                ("fingerprint", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("host", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                           related_name="events", to="logs.host")),
                ("pipeline_run", models.ForeignKey(blank=True, null=True,
                                                   on_delete=django.db.models.deletion.SET_NULL,
                                                   related_name="events", to="logs.pipelinerun")),
                ("service", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                              related_name="events", to="logs.service")),
            ],
        ),
        migrations.AddIndex(
            model_name="pipelinerun",
            index=models.Index(fields=["-started_at"], name="pipelinerun_started_idx"),
        ),
        migrations.AddConstraint(
            model_name="pipelinerun",
            constraint=models.CheckConstraint(
                condition=Q(finished_at__isnull=True) | Q(finished_at__gte=F("started_at")),
                name="pipelinerun_finished_after_started"),
        ),
        migrations.AddIndex(
            model_name="logevent", index=models.Index(fields=["timestamp"], name="logevent_ts_idx")),
        migrations.AddIndex(
            model_name="logevent",
            index=models.Index(fields=["level", "timestamp"], name="logevent_level_ts_idx")),
        migrations.AddIndex(
            model_name="logevent",
            index=models.Index(fields=["service", "timestamp"], name="logevent_service_ts_idx")),
        migrations.AddIndex(
            model_name="logevent", index=models.Index(fields=["status_code"], name="logevent_status_idx")),
        migrations.AddIndex(
            model_name="logevent", index=models.Index(fields=["endpoint"], name="logevent_endpoint_idx")),
        migrations.AddConstraint(
            model_name="logevent",
            constraint=models.CheckConstraint(
                condition=Q(status_code__isnull=True) | Q(status_code__gte=100, status_code__lte=599),
                name="logevent_status_code_range"),
        ),
        migrations.AddConstraint(
            model_name="logevent",
            constraint=models.CheckConstraint(
                condition=Q(response_time_ms__isnull=True) | Q(response_time_ms__gte=0),
                name="logevent_response_time_nonneg"),
        ),
        migrations.AddConstraint(
            model_name="logevent",
            constraint=models.CheckConstraint(
                condition=Q(level__in=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]),
                name="logevent_level_valid"),
        ),
    ]
