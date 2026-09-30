from datetime import timedelta

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from apps.logs.models import Host, LogEvent, PipelineRun, Service

from .factories import BASE_TIME, make_event


class ModelTests(TestCase):
    def test_service_and_host_names_are_unique(self):
        Service.objects.create(name="api")
        Host.objects.create(name="h1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Service.objects.create(name="api")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Host.objects.create(name="h1")

    def test_fingerprint_is_unique(self):
        make_event(fingerprint="dup")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_event(fingerprint="dup")

    def test_status_code_check_constraint(self):
        make_event(status_code=599)
        for bad in (99, 600):
            with self.assertRaises(IntegrityError), transaction.atomic():
                make_event(status_code=bad)

    def test_response_time_and_level_check_constraints(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_event(response_time_ms=-1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_event(level="LOUD")

    def test_nullable_http_fields_and_helpers(self):
        event = make_event(level="ERROR")
        self.assertIsNone(event.status_code)
        self.assertTrue(event.is_error)
        self.assertFalse(make_event(level="WARNING").is_error)
        self.assertEqual(event.get_absolute_url(), f"/logs/{event.pk}/")

    def test_service_in_use_cannot_be_deleted(self):
        event = make_event()
        with self.assertRaises(IntegrityError), transaction.atomic():
            event.service.delete()

    def test_pipeline_run_duration_and_constraint(self):
        run = PipelineRun.objects.create(source_file="a.log")
        self.assertIsNone(run.duration_seconds)
        run.finished_at = run.started_at + timedelta(seconds=2.5)
        run.save()
        self.assertEqual(run.duration_seconds, 2.5)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PipelineRun.objects.create(source_file="b.log", started_at=timezone.now(),
                                       finished_at=timezone.now() - timedelta(hours=1))

    def test_search_indexes_exist_in_postgres(self):
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, LogEvent._meta.db_table)
        indexes = {name for name, info in constraints.items() if info["index"]}
        for expected in ("logevent_ts_idx", "logevent_level_ts_idx", "logevent_service_ts_idx",
                         "logevent_status_idx", "logevent_endpoint_idx"):
            self.assertIn(expected, indexes)

    def test_ip_address_uses_postgres_inet(self):
        event = make_event(ip_address="10.1.2.3")
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_typeof(ip_address)::text FROM logs_logevent WHERE id = %s", [event.pk])
            self.assertEqual(cursor.fetchone()[0], "inet")
        self.assertEqual(LogEvent.objects.get(pk=event.pk).timestamp, BASE_TIME)
