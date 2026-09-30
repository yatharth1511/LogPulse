"""Format detection and parsing. Parsers only extract raw fields; validation is a separate stage."""
import json
import re
from typing import Optional

from .record import RecordRejected

# JSON logs: accept common key aliases used by different logging libraries.
JSON_KEYS = {
    "timestamp": ("timestamp", "@timestamp", "time", "ts", "datetime"),
    "level": ("level", "severity", "lvl", "log_level"),
    "service": ("service", "app", "application", "logger"),
    "host": ("host", "hostname", "server"),
    "message": ("message", "msg", "text"),
    "http_method": ("http_method", "method", "request_method"),
    "endpoint": ("endpoint", "path", "url", "uri", "request_uri"),
    "status_code": ("status_code", "status", "http_status"),
    "ip_address": ("ip_address", "ip", "remote_addr", "client_ip"),
}
JSON_RESPONSE_TIME_KEYS = (
    ("response_time_ms", "ms"),
    ("duration_ms", "ms"),
    ("latency_ms", "ms"),
    ("response_time_s", "s"),
    ("request_time", "s"),
)

# Nginx "combined" / Apache "common" access log, with optional trailing rt=<seconds>.
NGINX_RE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>[A-Z]+) (?P<path>\S+)(?: [^"]*)?" '
    r'(?P<status>\d{3}) (?:\d+|-)'
    r'(?: "[^"]*" "[^"]*")?'
    r'(?: rt=(?P<rt>\d+(?:\.\d+)?))?\s*$'
)

# Simple application log: 2026-09-30 12:00:01,123 ERROR [service] (host) message
APP_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+"
    r"(?P<level>[A-Za-z]+)\s+"
    r"\[(?P<service>[^\]]+)\]\s+"
    r"(?:\((?P<host>[^)]+)\)\s+)?"
    r"(?P<message>.*)$"
)
CONTEXT_RE = re.compile(r"\b(method|path|status|duration_ms|ip)=(\S+)")


def _first(data: dict, names) -> object:
    for name in names:
        value = data.get(name)
        if value is not None and value != "":
            return value
    return None


def parse_json_line(text: str, default_service: Optional[str] = None, default_host: Optional[str] = None) -> dict:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise RecordRejected("invalid_json", str(exc)) from exc
    if not isinstance(data, dict):
        raise RecordRejected("invalid_json", "top-level JSON value is not an object")

    raw = {field: _first(data, names) for field, names in JSON_KEYS.items()}
    raw["response_time"], raw["response_time_unit"] = None, "ms"
    for key, unit in JSON_RESPONSE_TIME_KEYS:
        if data.get(key) not in (None, ""):
            raw["response_time"], raw["response_time_unit"] = data[key], unit
            break
    raw["service"] = raw["service"] or default_service
    raw["host"] = raw["host"] or default_host
    raw["source_format"] = "json"
    return raw


def parse_access_line(match: re.Match, default_service: Optional[str], default_host: Optional[str]) -> dict:
    return {
        "timestamp": match["time"],
        "level": None,  # derived from the status code in the transform stage
        "service": default_service or "nginx",
        "host": default_host or "localhost",
        "message": "",
        "http_method": match["method"],
        "endpoint": match["path"],
        "status_code": match["status"],
        "response_time": match["rt"],
        "response_time_unit": "s",
        "ip_address": match["ip"],
        "source_format": "access",
    }


def parse_app_line(match: re.Match, default_service: Optional[str], default_host: Optional[str]) -> dict:
    message = match["message"].strip()
    context = dict(CONTEXT_RE.findall(message))  # optional key=value pairs inside the message
    return {
        "timestamp": match["ts"],
        "level": match["level"],
        "service": match["service"] or default_service,
        "host": match["host"] or default_host,
        "message": message,
        "http_method": context.get("method"),
        "endpoint": context.get("path"),
        "status_code": context.get("status"),
        "response_time": context.get("duration_ms"),
        "response_time_unit": "ms",
        "ip_address": context.get("ip"),
        "source_format": "app",
    }


def parse_line(line: str, default_service: Optional[str] = None, default_host: Optional[str] = None) -> dict:
    """Detect the format of one line and return a dict of raw (unvalidated) fields."""
    text = line.strip()
    if text.startswith("{"):
        return parse_json_line(text, default_service, default_host)
    match = NGINX_RE.match(text)
    if match:
        return parse_access_line(match, default_service, default_host)
    match = APP_RE.match(text)
    if match:
        return parse_app_line(match, default_service, default_host)
    raise RecordRejected("malformed_line", text[:80])
