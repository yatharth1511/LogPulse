import unittest
from datetime import datetime, timedelta, timezone

from pipelines.record import RecordRejected
from pipelines.transform import transform_record
from pipelines.validation import parse_timestamp, validate_record

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def base(**overrides):
    raw = {"timestamp": "2026-09-30T10:00:00Z", "level": "info", "service": "Auth", "host": "H1",
           "message": "hello", "http_method": None, "endpoint": None, "status_code": None,
           "response_time": None, "response_time_unit": "ms", "ip_address": None, "source_format": "json"}
    raw.update(overrides)
    return raw


class TimestampTests(unittest.TestCase):
    def test_supported_formats(self):
        expected = datetime(2026, 9, 30, 10, 15, 32, tzinfo=timezone.utc)
        for value in ("2026-09-30T10:15:32Z", "2026-09-30 10:15:32", "2026-09-30 10:15:32,000",
                      "30/Sep/2026:10:15:32 +0000", "30/Sep/2026:12:15:32 +0200", int(expected.timestamp()),
                      str(int(expected.timestamp())), int(expected.timestamp() * 1000)):
            self.assertEqual(parse_timestamp(value, now=NOW), expected, value)

    def test_naive_is_treated_as_utc_and_offsets_are_converted(self):
        self.assertEqual(parse_timestamp("2026-09-30T10:00:00+02:00", now=NOW).hour, 8)
        self.assertEqual(parse_timestamp("2026-09-30T10:00:00", now=NOW).tzinfo, timezone.utc)

    def test_invalid_values_are_rejected_with_reason(self):
        cases = {None: "missing_timestamp", "": "missing_timestamp", "yesterday": "invalid_timestamp",
                 "2026-13-45 99:99:99": "invalid_timestamp", "31/Foo/2026:10:00:00 +0000": "invalid_timestamp",
                 "1999-12-31T00:00:00Z": "timestamp_out_of_range", True: "invalid_timestamp",
                 (NOW + timedelta(days=5)).isoformat(): "timestamp_out_of_range"}
        for value, reason in cases.items():
            with self.assertRaises(RecordRejected, msg=repr(value)) as ctx:
                parse_timestamp(value, now=NOW)
            self.assertEqual(ctx.exception.reason, reason, repr(value))


class ValidationTests(unittest.TestCase):
    def test_normalizes_fields(self):
        record = validate_record(base(level="WARN", http_method="get", endpoint="http://x.io/api/a?b=1#f",
                                      status_code="404", response_time="0.5", response_time_unit="s",
                                      ip_address="::1"), raw_line="line", now=NOW)
        self.assertEqual((record.service, record.host, record.level), ("auth", "h1", "WARNING"))
        self.assertEqual((record.http_method, record.endpoint, record.status_code), ("GET", "/api/a", 404))
        self.assertEqual((record.response_time_ms, record.ip_address, record.raw), (500.0, "::1", "line"))

    def test_missing_service_and_host_become_unknown(self):
        record = validate_record(base(service=None, host=""), now=NOW)
        self.assertEqual((record.service, record.host), ("unknown", "unknown"))

    def test_rejections(self):
        cases = [
            (dict(timestamp=None), "missing_timestamp"),
            (dict(level="LOUD"), "invalid_level"),
            (dict(http_method="YEET", endpoint="/x"), "invalid_http_method"),
            (dict(status_code="999"), "invalid_status_code"),
            (dict(status_code="abc"), "invalid_status_code"),
            (dict(status_code=200.5), "invalid_status_code"),
            (dict(response_time="-1"), "invalid_response_time"),
            (dict(response_time="nan"), "invalid_response_time"),
            (dict(ip_address="999.1.1.1"), "invalid_ip"),
            (dict(message=""), "missing_message"),
            (dict(level=None), "missing_level"),
        ]
        for overrides, reason in cases:
            with self.assertRaises(RecordRejected, msg=str(overrides)) as ctx:
                validate_record(base(**overrides), now=NOW)
            self.assertEqual(ctx.exception.reason, reason, str(overrides))

    def test_access_log_without_message_or_level_is_valid(self):
        record = validate_record(base(level=None, message="", http_method="GET", endpoint="/a", status_code=503), now=NOW)
        transform_record(record)
        self.assertEqual((record.level, record.message), ("ERROR", "GET /a 503"))


class TransformTests(unittest.TestCase):
    def test_level_derived_from_status(self):
        for status, level in ((200, "INFO"), (302, "INFO"), (404, "WARNING"), (500, "ERROR")):
            record = validate_record(base(level=None, message="", http_method="GET", endpoint="/a",
                                          status_code=status), now=NOW)
            self.assertEqual(transform_record(record).level, level)

    def test_explicit_level_is_preserved_and_values_are_bounded(self):
        record = validate_record(base(level="DEBUG", message="x" * 20000, response_time="1.23456789"), now=NOW)
        transform_record(record)
        self.assertEqual(record.level, "DEBUG")
        self.assertEqual(len(record.message), 10_000)
        self.assertEqual(record.response_time_ms, 1.235)


if __name__ == "__main__":
    unittest.main()
