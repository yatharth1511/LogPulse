import os
import tempfile
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.ingestion.services import run_pipeline
from apps.logs.models import Host, LogEvent, PipelineRun, Service

GOOD_JSON = '{"timestamp":"2026-09-29T10:00:00Z","level":"ERROR","service":"Auth","host":"A1","message":"boom"}'
GOOD_APP = "2026-09-29 10:00:01,000 INFO     [order] (o1) fine"
GOOD_NGINX = '10.0.0.1 - - [29/Sep/2026:10:00:02 +0000] "GET /x?y=1 HTTP/1.1" 500 12 "-" "curl" rt=0.100'


class PipelineToPostgresTests(TestCase):
    def write(self, *lines):
        handle, path = tempfile.mkstemp(suffix=".log")
        with os.fdopen(handle, "w") as f:
            f.write("\n".join(lines) + "\n")
        self.addCleanup(os.unlink, path)
        return path

    def test_full_run_records_pipeline_run_and_rows(self):
        path = self.write(GOOD_JSON, GOOD_APP, GOOD_NGINX, "garbage", GOOD_JSON,
                          '{"timestamp":"bad","level":"INFO","message":"x"}')
        run = run_pipeline(path, batch_size=2)
        self.assertEqual(run.status, PipelineRun.Status.PARTIAL)
        self.assertEqual((run.records_processed, run.records_loaded, run.records_rejected, run.records_duplicate),
                         (6, 3, 2, 1))
        self.assertEqual(run.reject_reasons, {"malformed_line": 1, "invalid_timestamp": 1})
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(LogEvent.objects.count(), 3)
        self.assertEqual(set(Service.objects.values_list("name", flat=True)), {"auth", "order", "nginx"})
        self.assertEqual(Host.objects.count(), 3)
        access = LogEvent.objects.get(source_format="access")
        self.assertEqual((access.endpoint, access.status_code, access.level, access.response_time_ms),
                         ("/x", 500, "ERROR", 100.0))
        self.assertEqual(access.pipeline_run_id, run.pk)

    def test_rerunning_same_file_creates_no_duplicates(self):
        path = self.write(GOOD_JSON, GOOD_APP, GOOD_NGINX)
        first = run_pipeline(path)
        second = run_pipeline(path)
        self.assertEqual((first.status, first.records_loaded), (PipelineRun.Status.SUCCESS, 3))
        self.assertEqual((second.records_loaded, second.records_duplicate), (0, 3))
        self.assertEqual(LogEvent.objects.count(), 3)
        self.assertEqual(PipelineRun.objects.count(), 2)

    def test_all_rejected_marks_run_failed(self):
        run = run_pipeline(self.write("nope", "still nope"))
        self.assertEqual(run.status, PipelineRun.Status.FAILED)
        self.assertEqual(LogEvent.objects.count(), 0)

    def test_rejects_file_is_written(self):
        path = self.write(GOOD_APP, "garbage")
        rejects = path + ".rejects"
        self.addCleanup(lambda: os.path.exists(rejects) and os.unlink(rejects))
        run_pipeline(path, rejects_path=rejects)
        with open(rejects) as f:
            self.assertEqual(f.read().strip(), "2\tmalformed_line\tgarbage")

    def test_database_unique_constraint_backs_up_in_memory_dedupe(self):
        # With a 1-entry dedupe window the repeated first line has been evicted, so only PostgreSQL can catch it.
        path = self.write(GOOD_JSON, GOOD_APP, GOOD_JSON)
        with override_settings(LOGPULSE_DEDUPE_WINDOW=1):
            run = run_pipeline(path, batch_size=1)
        self.assertEqual((run.records_loaded, run.records_duplicate), (2, 1))
        self.assertEqual(LogEvent.objects.count(), 2)

    def test_loader_failure_marks_run_failed(self):
        from unittest import mock
        path = self.write(GOOD_APP)
        with mock.patch("apps.ingestion.services.PostgresLoader.__call__", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                run_pipeline(path)
        run = PipelineRun.objects.get()
        self.assertEqual(run.status, PipelineRun.Status.FAILED)
        self.assertIn("db down", run.error_message)


class ManagementCommandTests(TestCase):
    def test_generate_then_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "gen.log")
            call_command("generate_logs", count=500, output=path, seed=1, stdout=StringIO())
            with open(path) as f:
                self.assertEqual(len(f.readlines()), 500)
            out = StringIO()
            call_command("process_logs", path, batch_size=100, stdout=out)
        run = PipelineRun.objects.get()
        self.assertIn(run.status, {PipelineRun.Status.SUCCESS, PipelineRun.Status.PARTIAL})
        self.assertEqual(run.records_loaded + run.records_rejected + run.records_duplicate, 500)
        self.assertEqual(LogEvent.objects.count(), run.records_loaded)
        self.assertIn("loaded=", out.getvalue())

    def test_process_logs_missing_file(self):
        with self.assertRaises(CommandError):
            call_command("process_logs", "/nonexistent/file.log", stdout=StringIO())

    def test_process_logs_raises_when_file_fully_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
            f.write("garbage\n")
        self.addCleanup(os.unlink, f.name)
        with self.assertRaises(CommandError):
            call_command("process_logs", f.name, stdout=StringIO())

    def test_seed_demo_only_runs_on_empty_database(self):
        call_command("seed_demo", count=200, stdout=StringIO())
        loaded = LogEvent.objects.count()
        self.assertGreater(loaded, 0)
        call_command("seed_demo", count=200, stdout=StringIO())
        self.assertEqual(LogEvent.objects.count(), loaded)
