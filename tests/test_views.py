from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.logs.models import LogEvent, PipelineRun

from .factories import BASE_TIME, make_event


class WebViewTests(TestCase):
    def test_dashboard_renders_empty_and_with_data(self):
        response = self.client.get(reverse("analytics:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No logs in this range yet")

        make_event(level="ERROR", message="kaboom", http_method="GET", endpoint="/api/x", status_code=500,
                   response_time_ms=120.0)
        make_event(level="INFO", http_method="GET", endpoint="/api/x", status_code=200, response_time_ms=80.0)
        response = self.client.get(reverse("analytics:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "kaboom")
        self.assertContains(response, "50.0%")
        self.assertContains(response, "/api/x")
        self.assertEqual(response.context["data"]["summary"]["total_logs"], 2)
        self.assertEqual(response.context["chart_data"]["bucket"], "minute")

    def test_dashboard_range_filter_and_invalid_range(self):
        make_event(timestamp=BASE_TIME)  # far in the past
        self.assertEqual(self.client.get("/?range=1h").context["data"]["summary"]["total_logs"], 0)
        self.assertEqual(self.client.get("/?range=all").context["data"]["summary"]["total_logs"], 1)
        self.assertEqual(self.client.get("/?range=bogus").status_code, 200)

    def test_explorer_filters_and_pagination(self):
        for i in range(120):
            make_event(level="ERROR" if i % 2 else "INFO", message=f"event {i}",
                       timestamp=BASE_TIME + timedelta(minutes=i))
        response = self.client.get(reverse("logs:explorer"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 120)
        self.assertEqual(len(response.context["page_obj"]), 50)
        self.assertEqual(response.context["page_obj"][0].message, "event 119")  # newest first

        page3 = self.client.get(reverse("logs:explorer"), {"page": 3})
        self.assertEqual(len(page3.context["page_obj"]), 20)

        filtered = self.client.get(reverse("logs:explorer"), {"level": "ERROR", "q": "event 1"})
        self.assertTrue(all(e.level == "ERROR" and "event 1" in e.message for e in filtered.context["page_obj"]))
        self.assertIn("level=ERROR", filtered.context["query"])
        self.assertNotIn("page=", filtered.context["query"])

    def test_explorer_shows_error_for_invalid_filter(self):
        make_event()
        response = self.client.get(reverse("logs:explorer"), {"status_code": "zzz"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "status_code")
        self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_log_detail_shows_all_fields(self):
        event = make_event(level="ERROR", message="gateway down", http_method="POST", endpoint="/api/pay",
                           status_code=502, response_time_ms=812.5, ip_address="10.9.8.7", raw="the raw line",
                           source_format="json")
        response = self.client.get(event.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        for text in ("gateway down", "POST", "/api/pay", "502", "812.5", "10.9.8.7", "the raw line", event.fingerprint):
            self.assertContains(response, text)
        self.assertEqual(self.client.get("/logs/999999/").status_code, 404)

    def test_pipelines_page_upload_flow(self):
        self.assertEqual(self.client.get(reverse("ingestion:pipelines")).status_code, 200)
        upload = SimpleUploadedFile("web.log", b"2026-09-29 10:00:01,000 INFO     [web] (w1) hello\n")
        response = self.client.post(reverse("ingestion:pipelines"), {"file": upload}, follow=True)
        self.assertContains(response, "1 loaded")
        self.assertEqual(LogEvent.objects.count(), 1)
        self.assertEqual(PipelineRun.objects.get().status, "SUCCESS")
        self.assertContains(response, "upload:web.log")

    def test_pipelines_page_upload_without_file(self):
        response = self.client.post(reverse("ingestion:pipelines"), {}, follow=True)
        self.assertContains(response, "Choose a log file")
