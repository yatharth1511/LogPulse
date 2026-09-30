"""Validation + normalization: turn raw parsed fields into a typed, clean LogRecord."""
import ipaddress
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlsplit

from .record import LogRecord, RecordRejected

MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}
NGINX_TIME_RE = re.compile(r"^(\d{2})/([A-Za-z]{3})/(\d{4}):(\d{2}):(\d{2}):(\d{2})(?: ([+-])(\d{2})(\d{2}))?$")
EPOCH_RE = re.compile(r"^\d+(?:\.\d+)?$")

LEVEL_ALIASES = {
    "DEBUG": "DEBUG", "TRACE": "DEBUG",
    "INFO": "INFO", "INFORMATION": "INFO", "NOTICE": "INFO",
    "WARN": "WARNING", "WARNING": "WARNING",
    "ERROR": "ERROR", "ERR": "ERROR",
    "CRITICAL": "CRITICAL", "CRIT": "CRITICAL", "FATAL": "CRITICAL",
    "ALERT": "CRITICAL", "EMERG": "CRITICAL", "PANIC": "CRITICAL",
}
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "CONNECT", "TRACE"}
MIN_YEAR = 2000
MAX_ENDPOINT_LENGTH = 512
MAX_NAME_LENGTH = 100


def _from_epoch(value: float) -> datetime:
    if value > 1e11:  # milliseconds
        value = value / 1000.0
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise RecordRejected("invalid_timestamp", str(value)) from exc


def _parse_timestamp_string(text: str) -> datetime:
    match = NGINX_TIME_RE.match(text)
    if match:
        day, mon, year, hh, mm, ss, sign, tzh, tzm = match.groups()
        if mon not in MONTHS:
            raise RecordRejected("invalid_timestamp", text)
        offset = timezone.utc
        if sign:
            delta = timedelta(hours=int(tzh), minutes=int(tzm))
            offset = timezone(delta if sign == "+" else -delta)
        try:
            return datetime(int(year), MONTHS[mon], int(day), int(hh), int(mm), int(ss), tzinfo=offset)
        except ValueError as exc:
            raise RecordRejected("invalid_timestamp", text) from exc
    if EPOCH_RE.match(text):
        return _from_epoch(float(text))
    iso = text.replace(",", ".")
    if iso.endswith(("Z", "z")):
        iso = iso[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(iso)
    except ValueError as exc:
        raise RecordRejected("invalid_timestamp", text) from exc


def parse_timestamp(value, now: Optional[datetime] = None) -> datetime:
    """Return an aware UTC datetime or raise RecordRejected."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise RecordRejected("missing_timestamp")
    if isinstance(value, bool):
        raise RecordRejected("invalid_timestamp", str(value))
    if isinstance(value, (int, float)):
        parsed = _from_epoch(float(value))
    elif isinstance(value, str):
        parsed = _parse_timestamp_string(value.strip())
    else:
        raise RecordRejected("invalid_timestamp", repr(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    upper = (now or datetime.now(timezone.utc)) + timedelta(days=1)
    if parsed.year < MIN_YEAR or parsed > upper:
        raise RecordRejected("timestamp_out_of_range", parsed.isoformat())
    return parsed


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _level(value) -> Optional[str]:
    text = _text(value)
    if not text:
        return None
    try:
        return LEVEL_ALIASES[text.upper()]
    except KeyError as exc:
        raise RecordRejected("invalid_level", text) from exc


def _method(value) -> str:
    text = _text(value).upper()
    if text and text not in HTTP_METHODS:
        raise RecordRejected("invalid_http_method", text)
    return text


def _endpoint(value) -> str:
    text = _text(value)
    if not text:
        return ""
    path = urlsplit(text).path or "/"  # drops scheme/host, query string and fragment
    return path[:MAX_ENDPOINT_LENGTH]


def _status(value) -> Optional[int]:
    if value is None or _text(value) == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RecordRejected("invalid_status_code", _text(value)) from exc
    if not number.is_integer() or not 100 <= number <= 599:
        raise RecordRejected("invalid_status_code", _text(value))
    return int(number)


def _response_time(value, unit: str) -> Optional[float]:
    if value is None or _text(value) == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RecordRejected("invalid_response_time", _text(value)) from exc
    if math.isnan(number) or math.isinf(number) or number < 0:
        raise RecordRejected("invalid_response_time", _text(value))
    return number * 1000.0 if unit == "s" else number


def _ip(value) -> Optional[str]:
    text = _text(value)
    if text in ("", "-"):
        return None
    try:
        return str(ipaddress.ip_address(text))
    except ValueError as exc:
        raise RecordRejected("invalid_ip", text) from exc


def _name(value) -> str:
    return (_text(value).lower() or "unknown")[:MAX_NAME_LENGTH]


def validate_record(raw: dict, raw_line: str = "", now: Optional[datetime] = None) -> LogRecord:
    """Validate and normalize parsed fields. Raises RecordRejected with a reason code."""
    timestamp = parse_timestamp(raw.get("timestamp"), now=now)
    level = _level(raw.get("level"))
    method = _method(raw.get("http_method"))
    endpoint = _endpoint(raw.get("endpoint"))
    status = _status(raw.get("status_code"))
    response_time = _response_time(raw.get("response_time"), raw.get("response_time_unit") or "ms")
    ip = _ip(raw.get("ip_address"))
    message = _text(raw.get("message"))

    if not message and not (method and endpoint):
        raise RecordRejected("missing_message")
    if level is None and status is None:
        raise RecordRejected("missing_level")

    return LogRecord(
        timestamp=timestamp,
        service=_name(raw.get("service")),
        host=_name(raw.get("host")),
        message=message,
        level=level,
        http_method=method,
        endpoint=endpoint,
        status_code=status,
        response_time_ms=response_time,
        ip_address=ip,
        source_format=raw.get("source_format", ""),
        raw=raw_line,
    )
