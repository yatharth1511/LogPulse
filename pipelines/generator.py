"""Synthetic log generator (JSON lines, nginx access logs and application logs).

Emits a small share of malformed and duplicated lines on purpose, so the ETL data-quality
handling can be demonstrated without external data.
"""
import json
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

from .transform import level_from_status

FORMATS = ("mixed", "json", "nginx", "app")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

SERVICE_HOSTS = {
    "api-gateway": ["gw-01", "gw-02"],
    "auth-service": ["auth-01", "auth-02"],
    "payment-service": ["pay-01", "pay-02"],
    "order-service": ["ord-01", "ord-02", "ord-03"],
    "notification-service": ["notif-01"],
}
# (method, path, weight, owning service)
ENDPOINTS = [
    ("GET", "/api/products", 26, "api-gateway"),
    ("GET", "/api/products/101", 12, "api-gateway"),
    ("GET", "/api/products/102", 9, "api-gateway"),
    ("GET", "/api/search", 8, "api-gateway"),
    ("GET", "/api/health", 14, "api-gateway"),
    ("GET", "/static/app.js", 8, "api-gateway"),
    ("POST", "/api/login", 9, "auth-service"),
    ("POST", "/api/logout", 3, "auth-service"),
    ("POST", "/api/orders", 7, "order-service"),
    ("GET", "/api/orders", 8, "order-service"),
    ("POST", "/api/payments", 5, "payment-service"),
    ("POST", "/api/notifications", 3, "notification-service"),
]
APP_MESSAGES = {
    "DEBUG": ["Cache lookup completed", "Loaded configuration from environment"],
    "INFO": ["Order created", "Payment authorized", "User login succeeded", "Email queued", "Cache warmed"],
    "WARNING": ["Slow query detected", "Retrying upstream request", "Cache miss ratio above threshold",
                "Disk usage above 80%"],
    "ERROR": ["Database connection timeout", "Payment gateway returned 502", "Failed to publish message to queue",
              "Unhandled exception in request handler", "Upstream service unavailable"],
    "CRITICAL": ["Out of memory: killing worker", "Database primary unreachable"],
}
LEVEL_WEIGHTS = [("DEBUG", 4), ("INFO", 68), ("WARNING", 18), ("ERROR", 8), ("CRITICAL", 2)]
USER_AGENTS = ["Mozilla/5.0 (X11; Linux x86_64)", "curl/8.5.0", "python-requests/2.32", "Mozilla/5.0 (iPhone)"]


def _ip_pool() -> list:
    rnd = random.Random(1234)
    return [f"{rnd.choice([10, 172, 192, 203])}.{rnd.randint(0, 255)}.{rnd.randint(0, 255)}.{rnd.randint(1, 254)}"
            for _ in range(200)]


IP_POOL = _ip_pool()


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def _make_http_event(rnd: random.Random, ts: datetime) -> dict:
    method, path, _, service = rnd.choices(ENDPOINTS, weights=[e[2] for e in ENDPOINTS])[0]
    fail_boost = 3.0 if service == "payment-service" else 1.0
    roll = rnd.random()
    if roll < 0.025 * fail_boost:
        status = rnd.choice([500, 500, 502, 503, 504])
    elif roll < 0.08 + 0.025 * fail_boost:
        status = rnd.choice([400, 401, 403, 404, 404, 429])
    elif method == "POST" and path != "/api/login":
        status = 201
    else:
        status = rnd.choice([200] * 9 + [304])
    rt = rnd.lognormvariate(math.log(90), 0.6) * (3 if status >= 500 else 1)
    return {
        "kind": "http", "ts": ts, "service": service, "host": rnd.choice(SERVICE_HOSTS[service]),
        "method": method, "path": path, "status": status, "rt_ms": round(rt, 2),
        "ip": rnd.choice(IP_POOL), "level": level_from_status(status),
    }


def _make_app_event(rnd: random.Random, ts: datetime) -> dict:
    level = rnd.choices([l for l, _ in LEVEL_WEIGHTS], weights=[w for _, w in LEVEL_WEIGHTS])[0]
    service = rnd.choice(list(SERVICE_HOSTS))
    return {
        "kind": "app", "ts": ts, "service": service, "host": rnd.choice(SERVICE_HOSTS[service]),
        "level": level, "message": rnd.choice(APP_MESSAGES[level]),
    }


def _render_json(e: dict) -> str:
    doc = {"timestamp": _iso(e["ts"]), "level": e["level"], "service": e["service"], "host": e["host"]}
    if e["kind"] == "http":
        doc.update(message=f"{e['method']} {e['path']} {e['status']}", method=e["method"], path=e["path"],
                   status=e["status"], response_time_ms=e["rt_ms"], ip=e["ip"])
    else:
        doc["message"] = e["message"]
    return json.dumps(doc, separators=(",", ":"))


def _render_nginx(rnd: random.Random, e: dict) -> str:
    ts = e["ts"]
    stamp = f"{ts.day:02d}/{MONTHS[ts.month - 1]}/{ts.year}:{ts:%H:%M:%S} +0000"
    size = rnd.randint(120, 48_000)
    return (f'{e["ip"]} - - [{stamp}] "{e["method"]} {e["path"]} HTTP/1.1" {e["status"]} {size} '
            f'"-" "{rnd.choice(USER_AGENTS)}" rt={e["rt_ms"] / 1000:.3f}')


def _render_app(e: dict) -> str:
    ts = e["ts"]
    head = f"{ts:%Y-%m-%d %H:%M:%S},{ts.microsecond // 1000:03d} {e['level']:<8} [{e['service']}] ({e['host']}) "
    if e["kind"] == "http":
        return head + (f"request completed method={e['method']} path={e['path']} status={e['status']} "
                       f"duration_ms={e['rt_ms']} ip={e['ip']}")
    return head + e["message"]


def _bad_line(rnd: random.Random, ts: datetime) -> str:
    choices = [
        "this is not a log line",
        '{"timestamp": "%s", "level": "INFO", "message": ' % _iso(ts),  # truncated JSON
        '{"level": "INFO", "service": "auth-service", "message": "missing timestamp"}',
        '{"timestamp": "yesterday-ish", "level": "INFO", "message": "bad timestamp"}',
        "2026-13-45 99:99:99,000 ERROR   [order-service] (ord-01) impossible timestamp",
        '999.1.1.1 - - [30/Sep/2026:10:00:00 +0000] "GET /api/x HTTP/1.1" 200 12 "-" "curl/8"',
        '10.0.0.1 - - [30/Sep/2026:10:00:00 +0000] "GET /api/x HTTP/1.1" 999 12 "-" "curl/8"',
        '{"timestamp": "%s", "level": "LOUD", "message": "unknown level"}' % _iso(ts),
    ]
    return rnd.choice(choices)


def generate_lines(
    count: int,
    *,
    fmt: str = "mixed",
    seed: Optional[int] = None,
    end: Optional[datetime] = None,
    days: float = 1.0,
    bad_ratio: float = 0.01,
    duplicate_ratio: float = 0.01,
) -> Iterator[str]:
    """Yield `count` log lines spread evenly over the `days` before `end`."""
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}")
    rnd = random.Random(seed)
    end = end or datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    span = (end - start).total_seconds()
    previous: Optional[str] = None

    for i in range(count):
        roll = rnd.random()
        ts = start + timedelta(seconds=span * (i + rnd.random()) / count)
        if roll < bad_ratio:
            yield _bad_line(rnd, ts)
            continue
        if previous is not None and roll < bad_ratio + duplicate_ratio:
            yield previous
            continue

        http = fmt == "nginx" or rnd.random() < 0.65
        event = _make_http_event(rnd, ts) if http else _make_app_event(rnd, ts)
        if fmt == "mixed":
            style = rnd.choices(["json", "nginx", "app"], weights=[35, 45, 20])[0] if http \
                else rnd.choices(["json", "app"], weights=[40, 60])[0]
        else:
            style = fmt
        if style == "nginx":
            line = _render_nginx(rnd, event)
        elif style == "json":
            line = _render_json(event)
        else:
            line = _render_app(event)
        previous = line
        yield line
