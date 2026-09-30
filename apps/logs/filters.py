"""Shared log filtering, used by both the web explorer and the REST API."""
from datetime import datetime, time, timedelta, timezone as dt_timezone
from typing import Optional, Tuple

from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
RANGES = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
RANGE_CHOICES = [("all", "All time"), ("1h", "Last hour"), ("24h", "Last 24 hours"),
                 ("7d", "Last 7 days"), ("30d", "Last 30 days")]


class FilterError(ValueError):
    """Invalid filter value supplied by the caller."""


def _param(params, name: str) -> str:
    return (params.get(name) or "").strip()


def _parse_dt(name: str, value: str, end_of_day: bool = False) -> datetime:
    try:
        parsed = parse_datetime(value)
        if parsed is None:
            day = parse_date(value)
            if day is None:
                raise ValueError
            parsed = datetime.combine(day, time.max if end_of_day else time.min)
    except ValueError:
        raise FilterError(f"'{name}' must be an ISO date or datetime (e.g. 2026-09-30T12:00)") from None
    if timezone.is_naive(parsed):
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


def resolve_time_window(params, now: Optional[datetime] = None) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Return (start, end) from `range` and/or explicit `start`/`end`; explicit values win."""
    now = now or timezone.now()
    start = end = None
    rng = _param(params, "range")
    if rng and rng != "all":
        if rng not in RANGES:
            raise FilterError(f"'range' must be one of: all, {', '.join(RANGES)}")
        start = now - RANGES[rng]
    if _param(params, "start"):
        start = _parse_dt("start", _param(params, "start"))
    if _param(params, "end"):
        end = _parse_dt("end", _param(params, "end"), end_of_day=True)
    if start and end and start > end:
        raise FilterError("'start' must be earlier than 'end'")
    return start, end


def _status_q(value: str) -> Q:
    v = value.lower()
    if len(v) == 3 and v[0] in "12345" and v[1:] == "xx":
        low = int(v[0]) * 100
        return Q(status_code__gte=low, status_code__lt=low + 100)
    if v.isdigit() and 100 <= int(v) <= 599:
        return Q(status_code=int(v))
    raise FilterError("'status_code' must be a code like 404 or a class like 5xx")


def filter_logs(queryset: QuerySet, params) -> QuerySet:
    """Apply time range, level, service, host, status_code, endpoint and keyword filters."""
    start, end = resolve_time_window(params)
    if start:
        queryset = queryset.filter(timestamp__gte=start)
    if end:
        queryset = queryset.filter(timestamp__lte=end)

    level = _param(params, "level")
    if level:
        levels = [item.strip().upper() for item in level.split(",") if item.strip()]
        invalid = [item for item in levels if item not in LEVELS]
        if invalid:
            raise FilterError(f"invalid level(s): {', '.join(invalid)}; choose from {', '.join(LEVELS)}")
        queryset = queryset.filter(level__in=levels)

    if _param(params, "service"):
        queryset = queryset.filter(service__name=_param(params, "service").lower())
    if _param(params, "host"):
        queryset = queryset.filter(host__name=_param(params, "host").lower())
    if _param(params, "status_code"):
        queryset = queryset.filter(_status_q(_param(params, "status_code")))
    if _param(params, "endpoint"):
        queryset = queryset.filter(endpoint__icontains=_param(params, "endpoint"))
    if _param(params, "q"):
        queryset = queryset.filter(message__icontains=_param(params, "q"))
    return queryset
