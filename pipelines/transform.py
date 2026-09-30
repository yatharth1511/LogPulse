"""Transformation: derive missing fields and enforce storage limits."""
from .record import LogRecord

MAX_MESSAGE_LENGTH = 10_000
MAX_RAW_LENGTH = 10_000


def level_from_status(status_code) -> str:
    if status_code is not None and status_code >= 500:
        return "ERROR"
    if status_code is not None and status_code >= 400:
        return "WARNING"
    return "INFO"


def transform_record(record: LogRecord) -> LogRecord:
    if record.level is None:
        record.level = level_from_status(record.status_code)
    if not record.message:
        parts = [record.http_method, record.endpoint]
        if record.status_code is not None:
            parts.append(str(record.status_code))
        record.message = " ".join(parts)
    record.message = record.message[:MAX_MESSAGE_LENGTH]
    record.raw = record.raw[:MAX_RAW_LENGTH]
    if record.response_time_ms is not None:
        record.response_time_ms = round(record.response_time_ms, 3)
    return record
