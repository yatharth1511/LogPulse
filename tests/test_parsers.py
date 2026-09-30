import unittest

from pipelines.parsers import parse_line
from pipelines.record import RecordRejected


class ParserTests(unittest.TestCase):
    def test_json_line_with_canonical_keys(self):
        raw = parse_line('{"timestamp":"2026-09-30T10:00:00Z","level":"ERROR","service":"auth","host":"a1",'
                         '"message":"boom","method":"POST","path":"/login","status":500,'
                         '"response_time_ms":12.5,"ip":"10.0.0.1"}')
        self.assertEqual(raw["source_format"], "json")
        self.assertEqual(raw["http_method"], "POST")
        self.assertEqual(raw["endpoint"], "/login")
        self.assertEqual(raw["status_code"], 500)
        self.assertEqual((raw["response_time"], raw["response_time_unit"]), (12.5, "ms"))
        self.assertEqual(raw["ip_address"], "10.0.0.1")

    def test_json_aliases_and_seconds_unit(self):
        raw = parse_line('{"@timestamp":"2026-09-30T10:00:00Z","severity":"warn","app":"x","hostname":"h",'
                         '"msg":"m","request_time":0.25}')
        self.assertEqual((raw["level"], raw["service"], raw["host"], raw["message"]), ("warn", "x", "h", "m"))
        self.assertEqual((raw["response_time"], raw["response_time_unit"]), (0.25, "s"))

    def test_json_uses_defaults_for_missing_service_and_host(self):
        raw = parse_line('{"timestamp":"2026-09-30T10:00:00Z","level":"INFO","message":"m"}', "svc", "hst")
        self.assertEqual((raw["service"], raw["host"]), ("svc", "hst"))

    def test_invalid_json_is_rejected(self):
        for line in ('{"timestamp": "2026-09-30T10:00:00Z", "level": ', '{bad json}'):
            with self.assertRaises(RecordRejected) as ctx:
                parse_line(line)
            self.assertEqual(ctx.exception.reason, "invalid_json")

    def test_nginx_combined_with_response_time(self):
        line = ('203.0.113.9 - - [30/Sep/2026:10:15:32 +0000] "GET /api/orders?page=2 HTTP/1.1" 502 1234 '
                '"-" "curl/8.5" rt=0.250')
        raw = parse_line(line)
        self.assertEqual(raw["source_format"], "access")
        self.assertEqual((raw["ip_address"], raw["http_method"], raw["endpoint"], raw["status_code"]),
                         ("203.0.113.9", "GET", "/api/orders?page=2", "502"))
        self.assertEqual((raw["response_time"], raw["response_time_unit"]), ("0.250", "s"))
        self.assertEqual(raw["service"], "nginx")

    def test_apache_common_format_without_referer_or_response_time(self):
        raw = parse_line('127.0.0.1 - frank [10/Oct/2026:13:55:36 -0700] "POST /apache_pb.gif HTTP/1.0" 200 2326',
                         default_service="web", default_host="h1")
        self.assertEqual((raw["service"], raw["host"], raw["response_time"]), ("web", "h1", None))

    def test_application_log_with_context_pairs(self):
        line = ("2026-09-30 10:00:01,123 ERROR    [payment-service] (pay-01) gateway failed "
                "method=POST path=/api/payments status=502 duration_ms=812.5 ip=10.1.1.1")
        raw = parse_line(line)
        self.assertEqual(raw["source_format"], "app")
        self.assertEqual((raw["level"], raw["service"], raw["host"]), ("ERROR", "payment-service", "pay-01"))
        self.assertEqual((raw["http_method"], raw["endpoint"], raw["status_code"], raw["response_time"]),
                         ("POST", "/api/payments", "502", "812.5"))

    def test_application_log_without_host(self):
        raw = parse_line("2026-09-30T10:00:01Z INFO [svc] hello world")
        self.assertEqual((raw["host"], raw["message"]), (None, "hello world"))

    def test_unrecognised_line_is_malformed(self):
        with self.assertRaises(RecordRejected) as ctx:
            parse_line("this is not a log line")
        self.assertEqual(ctx.exception.reason, "malformed_line")


if __name__ == "__main__":
    unittest.main()
