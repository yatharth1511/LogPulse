from datetime import timedelta

from django.test import TestCase

from apps.analytics import services
from apps.logs.models import LogEvent

from .factories import BASE_TIME, make_event


def http(status, *, minutes=0, endpoint="/api/a", rt=100.0, service="api", method="GET", **kw):
    level = "ERROR" if status >= 500 else "WARNING" if status >= 400 else "INFO"
    return make_event(service=service, level=level, timestamp=BASE_TIME + timedelta(minutes=minutes),
                      http_method=method, endpoint=endpoint, status_code=status, response_time_ms=rt,
                      message=f"{method} {endpoint} {status}", **kw)


class AnalyticsTests(TestCase):
    def setUp(self):
        # minute 0: 3 requests, minute 1: 1 request, minute 2: 2 requests
        http(200, minutes=0, rt=100); http(200, minutes=0, rt=200); http(500, minutes=0, rt=300)
        http(404, minutes=1, endpoint="/api/b", rt=400)
        http(200, minutes=2, endpoint="/api/b", rt=500); http(503, minutes=2, endpoint="/api/b", rt=600, service="pay")
        make_event(level="CRITICAL", message="Out of memory", service="pay", timestamp=BASE_TIME)
        make_event(level="ERROR", message="Out of memory", service="pay", timestamp=BASE_TIME + timedelta(minutes=1))
        make_event(level="ERROR", message="DB timeout", service="api", timestamp=BASE_TIME + timedelta(minutes=1))
        make_event(level="WARNING", message="slow", service="api", timestamp=BASE_TIME + timedelta(minutes=3))
        self.qs = LogEvent.objects.all()

    def test_summary(self):
        s = services.summary(self.qs)
        self.assertEqual(s["total_logs"], 10)
        self.assertEqual(s["error_count"], 5)     # 500, 503, CRITICAL, ERROR, ERROR
        self.assertEqual(s["warning_count"], 2)   # 404 + slow
        self.assertEqual(s["error_rate"], 50.0)
        self.assertEqual(s["avg_response_time_ms"], 350.0)  # only rows with a response time

    def test_summary_of_empty_queryset(self):
        s = services.summary(LogEvent.objects.none())
        self.assertEqual((s["total_logs"], s["error_rate"], s["avg_response_time_ms"]), (0, 0.0, None))

    def test_requests_per_minute(self):
        r = services.requests_per_minute(self.qs)
        self.assertEqual(r["total_requests"], 6)
        self.assertEqual(r["avg_per_minute"], 3.0)   # 6 requests over the 2-minute span
        self.assertEqual((r["peak_per_minute"], r["peak_minute"]), (3, BASE_TIME.isoformat()))

    def test_top_endpoints_and_status_distribution(self):
        top = services.top_endpoints(self.qs)
        self.assertEqual([(t["endpoint"], t["hits"]) for t in top], [("/api/a", 3), ("/api/b", 3)])
        dist = services.status_distribution(self.qs)
        self.assertEqual({c["class"]: c["count"] for c in dist["classes"]}, {"2xx": 3, "3xx": 0, "4xx": 1, "5xx": 2})
        self.assertEqual([c["status_code"] for c in dist["codes"]], [200, 404, 500, 503])

    def test_most_common_errors(self):
        errors = services.most_common_errors(self.qs)
        self.assertEqual((errors[0]["message"], errors[0]["service"], errors[0]["occurrences"]),
                         ("Out of memory", "pay", 2))

    def test_by_service_and_level(self):
        by_service = {r["service"]: (r["total"], r["errors"]) for r in services.by_service(self.qs)}
        self.assertEqual(by_service, {"api": (7, 2), "pay": (3, 3)})
        self.assertEqual({r["level"]: r["count"] for r in services.by_level(self.qs)},
                         {"INFO": 3, "WARNING": 2, "ERROR": 4, "CRITICAL": 1})

    def test_logs_over_time_uses_minute_buckets_for_short_spans(self):
        series = services.logs_over_time(self.qs, BASE_TIME, BASE_TIME + timedelta(minutes=3))
        self.assertEqual(series["bucket"], "minute")
        self.assertEqual(sum(p["total"] for p in series["points"]), 10)
        self.assertEqual(services.logs_over_time(self.qs, BASE_TIME, BASE_TIME + timedelta(days=10))["bucket"], "day")

    def test_recent_errors_are_newest_first(self):
        recent = services.recent_errors(self.qs, limit=3)
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent, sorted(recent, key=lambda e: (e.timestamp, e.id), reverse=True))
        self.assertTrue(all(e.is_error for e in recent))

    def test_sql_window_function_request_rate_trend(self):
        rows = services.request_rate_trend()
        self.assertEqual([r["requests"] for r in rows], [3, 1, 2])       # chronological
        self.assertEqual([r["moving_avg_5m"] for r in rows], [3.0, 2.0, 2.0])  # 3, (3+1)/2, (3+1+2)/3
        self.assertEqual([r["change_vs_prev_minute"] for r in rows], [None, -2, 1])  # LAG()
        self.assertEqual([r["server_errors"] for r in rows], [1, 0, 1])

    def test_sql_window_function_respects_time_window(self):
        rows = services.request_rate_trend(start=BASE_TIME + timedelta(minutes=1))
        self.assertEqual([r["requests"] for r in rows], [1, 2])

    def test_sql_window_function_top_errors_per_service(self):
        rows = services.top_errors_per_service(per_service=1)
        by_service = {r["service"]: r for r in rows}
        self.assertEqual(set(by_service), {"api", "pay"})
        self.assertEqual((by_service["pay"]["message"], by_service["pay"]["occurrences"]), ("Out of memory", 2))
        self.assertTrue(all(r["rank_in_service"] == 1 for r in rows))
        all_rows = services.top_errors_per_service(per_service=5)
        self.assertEqual(sorted(r["rank_in_service"] for r in all_rows if r["service"] == "api"), [1, 2])

    def test_build_report_has_every_section(self):
        report = services.build_report(self.qs)
        for key in ("summary", "requests", "logs_over_time", "by_level", "by_service", "status_distribution",
                    "top_endpoints", "most_common_errors", "top_errors_per_service", "request_rate_trend"):
            self.assertIn(key, report)
        self.assertNotIn("_first", report["summary"])
