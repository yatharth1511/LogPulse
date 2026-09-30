from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.logs.models import LogEvent, PipelineRun

from .factories import BASE_TIME, make_event

GOOD_JSON = '{"timestamp":"2026-09-29T10:00:00Z","level":"ERROR","service":"auth","host":"a1","message":"boom"}'


class LogApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.a = make_event(service="api", level="INFO", message="user logged in", timestamp=BASE_TIME,
                            http_method="POST", endpoint="/api/login", status_code=200, response_time_ms=50.0)
        self.b = make_event(service="pay", level="ERROR", message="gateway timeout",
                            timestamp=BASE_TIME + timedelta(hours=1), http_method="POST",
                            endpoint="/api/payments", status_code=504, response_time_ms=900.0, ip_address="10.0.0.9")
        self.c = make_event(service="api", level="WARNING", message="slow query",
                            timestamp=BASE_TIME + timedelta(hours=2), status_code=404)

    def test_list_is_paginated_newest_first(self):
        response = self.client.get("/api/logs/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual([r["id"] for r in response.data["results"]], [self.c.id, self.b.id, self.a.id])
        first = response.data["results"][1]
        self.assertEqual((first["service"], first["host"], first["ip_address"]), ("pay", "h1", "10.0.0.9"))

    def test_page_size_and_next_link(self):
        for i in range(60):
            make_event(message=f"bulk {i}", timestamp=BASE_TIME - timedelta(minutes=i + 1))
        response = self.client.get("/api/logs/")
        self.assertEqual(len(response.data["results"]), 50)
        self.assertIsNotNone(response.data["next"])
        self.assertEqual(self.client.get("/api/logs/?page=2").status_code, 200)

    def test_filters(self):
        def ids(query):
            return {r["id"] for r in self.client.get(f"/api/logs/?{query}").data["results"]}

        self.assertEqual(ids("level=ERROR"), {self.b.id})
        self.assertEqual(ids("level=error,warning"), {self.b.id, self.c.id})
        self.assertEqual(ids("service=api"), {self.a.id, self.c.id})
        self.assertEqual(ids("status_code=504"), {self.b.id})
        self.assertEqual(ids("status_code=5xx"), {self.b.id})
        self.assertEqual(ids("status_code=4xx"), {self.c.id})
        self.assertEqual(ids("endpoint=payments"), {self.b.id})
        self.assertEqual(ids("q=SLOW"), {self.c.id})
        self.assertEqual(ids("start=2026-09-29T10:30:00Z&end=2026-09-29T11:30:00Z"), {self.b.id})
        self.assertEqual(ids("start=2026-09-29T11:30:00"), {self.c.id})
        self.assertEqual(ids("start=2026-09-30"), set())
        self.assertEqual(ids("level=ERROR&service=api"), set())

    def test_invalid_filters_return_400(self):
        for query in ("level=LOUD", "status_code=abc", "status_code=999", "start=not-a-date",
                      "range=forever", "start=2026-10-01T00:00:00Z&end=2026-09-01T00:00:00Z"):
            response = self.client.get(f"/api/logs/?{query}")
            self.assertEqual(response.status_code, 400, query)
            self.assertIn("detail", response.data)

    def test_detail_and_404(self):
        response = self.client.get(f"/api/logs/{self.b.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["message"], "gateway timeout")
        self.assertEqual(response.data["response_time_ms"], 900.0)
        self.assertEqual(self.client.get("/api/logs/999999/").status_code, 404)

    def test_write_methods_not_allowed(self):
        self.assertEqual(self.client.post("/api/logs/", {"message": "x"}, format="json").status_code, 405)
        self.assertEqual(self.client.delete(f"/api/logs/{self.a.id}/").status_code, 405)

    def test_services_endpoint(self):
        response = self.client.get("/api/services/")
        self.assertEqual(response.status_code, 200)
        rows = {r["name"]: (r["log_count"], r["error_count"]) for r in response.data["results"]}
        self.assertEqual(rows, {"api": (2, 0), "pay": (1, 1)})


class AnalyticsApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        make_event(level="INFO", http_method="GET", endpoint="/a", status_code=200, response_time_ms=100.0)
        make_event(level="ERROR", http_method="GET", endpoint="/a", status_code=500, response_time_ms=300.0,
                   message="GET /a 500", timestamp=BASE_TIME + timedelta(minutes=1))
        make_event(level="WARNING", message="slow", timestamp=BASE_TIME + timedelta(minutes=2))

    def test_analytics_payload(self):
        response = self.client.get("/api/analytics/")
        self.assertEqual(response.status_code, 200)
        summary = response.data["summary"]
        self.assertEqual((summary["total_logs"], summary["error_count"], summary["warning_count"]), (3, 1, 1))
        self.assertEqual(summary["error_rate"], 33.33)
        self.assertEqual(summary["avg_response_time_ms"], 200.0)
        self.assertEqual(response.data["top_endpoints"][0]["endpoint"], "/a")
        self.assertEqual(response.data["most_common_errors"][0]["message"], "GET /a 500")
        self.assertEqual(len(response.data["recent_errors"]), 1)
        self.assertEqual(len(response.data["request_rate_trend"]), 2)
        self.assertEqual(response.data["requests"]["total_requests"], 2)

    def test_analytics_respects_filters(self):
        response = self.client.get("/api/analytics/?level=ERROR")
        self.assertEqual(response.data["summary"]["total_logs"], 1)
        self.assertEqual(response.data["summary"]["error_rate"], 100.0)

    def test_analytics_bad_filter_is_400(self):
        self.assertEqual(self.client.get("/api/analytics/?range=nope").status_code, 400)

    def test_analytics_on_empty_database(self):
        LogEvent.objects.all().delete()
        response = self.client.get("/api/analytics/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["summary"]["total_logs"], 0)
        self.assertEqual(response.data["top_endpoints"], [])


class PipelineApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def upload(self, content, name="upload.log", **extra):
        return self.client.post("/api/pipelines/", {"file": SimpleUploadedFile(name, content.encode()), **extra},
                                format="multipart")

    def test_upload_runs_pipeline_and_returns_201(self):
        response = self.upload(GOOD_JSON + "\nnot a log line\n", service="fallback")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "PARTIAL")
        self.assertEqual((response.data["records_processed"], response.data["records_loaded"],
                          response.data["records_rejected"]), (2, 1, 1))
        self.assertEqual(response.data["reject_reasons"], {"malformed_line": 1})
        self.assertEqual(response.data["source_file"], "upload:upload.log")
        self.assertEqual(LogEvent.objects.count(), 1)

    def test_upload_of_unusable_file_returns_422(self):
        response = self.upload("nothing useful here\n")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.data["status"], "FAILED")

    def test_upload_without_file_returns_400(self):
        response = self.client.post("/api/pipelines/", {}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.data)

    def test_list_and_detail(self):
        run = PipelineRun.objects.create(source_file="a.log", status="SUCCESS", records_processed=5)
        response = self.client.get("/api/pipelines/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["id"], run.id)
        detail = self.client.get(f"/api/pipelines/{run.id}/")
        self.assertEqual((detail.status_code, detail.data["records_processed"]), (200, 5))
        self.assertEqual(self.client.get("/api/pipelines/424242/").status_code, 404)
