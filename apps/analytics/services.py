"""Analytics queries. Aggregations use the ORM; the trend / ranking queries use raw SQL window functions."""
from datetime import timedelta
from typing import Optional

from django.db import connection
from django.db.models import Avg, Count, F, Max, Min, Q, QuerySet
from django.db.models.functions import TruncDay, TruncHour, TruncMinute

from apps.logs.models import LogEvent

ERROR_LEVELS = ("ERROR", "CRITICAL")


def _iso(value):
    return value.isoformat() if value else None


def _rows(cursor):
    columns = [col.name for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _clean(row: dict) -> dict:
    """Convert Decimal/datetime values from raw SQL into JSON-friendly types."""
    out = {}
    for key, value in row.items():
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        elif value is not None and value.__class__.__name__ == "Decimal":
            value = float(value)
        out[key] = value
    return out


def summary(queryset: QuerySet) -> dict:
    """Total logs, errors, warnings, error rate (%) and average response time."""
    agg = queryset.aggregate(
        total=Count("id"),
        errors=Count("id", filter=Q(level__in=ERROR_LEVELS)),
        warnings=Count("id", filter=Q(level="WARNING")),
        avg_response=Avg("response_time_ms"),
        first_event=Min("timestamp"),
        last_event=Max("timestamp"),
    )
    total = agg["total"]
    return {
        "total_logs": total,
        "error_count": agg["errors"],
        "warning_count": agg["warnings"],
        "error_rate": round(agg["errors"] * 100.0 / total, 2) if total else 0.0,
        "avg_response_time_ms": round(agg["avg_response"], 2) if agg["avg_response"] is not None else None,
        "first_event": _iso(agg["first_event"]),
        "last_event": _iso(agg["last_event"]),
        "_first": agg["first_event"],
        "_last": agg["last_event"],
    }


def requests_per_minute(queryset: QuerySet) -> dict:
    """Average HTTP requests per minute over the observed span, plus the busiest minute."""
    http = queryset.exclude(http_method="")
    agg = http.aggregate(total=Count("id"), first=Min("timestamp"), last=Max("timestamp"))
    if not agg["total"]:
        return {"total_requests": 0, "avg_per_minute": 0.0, "peak_per_minute": 0, "peak_minute": None}
    minutes = max((agg["last"] - agg["first"]).total_seconds() / 60.0, 1.0)
    peak = (
        http.annotate(minute=TruncMinute("timestamp"))
        .values("minute").annotate(n=Count("id")).order_by("-n", "minute").first()
    )
    return {
        "total_requests": agg["total"],
        "avg_per_minute": round(agg["total"] / minutes, 2),
        "peak_per_minute": peak["n"],
        "peak_minute": _iso(peak["minute"]),
    }


def logs_over_time(queryset: QuerySet, first=None, last=None) -> dict:
    """Log volume per time bucket; bucket size adapts to the span (minute / hour / day)."""
    span = (last - first) if first and last else timedelta(0)
    if span <= timedelta(hours=3):
        name, trunc = "minute", TruncMinute
    elif span <= timedelta(days=3):
        name, trunc = "hour", TruncHour
    else:
        name, trunc = "day", TruncDay
    rows = (
        queryset.annotate(bucket=trunc("timestamp")).values("bucket")
        .annotate(total=Count("id"), errors=Count("id", filter=Q(level__in=ERROR_LEVELS)))
        .order_by("bucket")
    )
    return {"bucket": name, "points": [
        {"t": _iso(r["bucket"]), "total": r["total"], "errors": r["errors"]} for r in rows]}


def by_level(queryset: QuerySet) -> list:
    return list(queryset.values("level").annotate(count=Count("id")).order_by("-count", "level"))


def by_service(queryset: QuerySet) -> list:
    rows = (
        queryset.values(service_name=F("service__name")).annotate(
            total=Count("id"), errors=Count("id", filter=Q(level__in=ERROR_LEVELS)))
        .order_by("-total", "service_name")
    )
    return [{"service": r["service_name"], "total": r["total"], "errors": r["errors"]} for r in rows]


def status_distribution(queryset: QuerySet) -> dict:
    rows = list(
        queryset.exclude(status_code__isnull=True).values("status_code")
        .annotate(count=Count("id")).order_by("status_code")
    )
    classes = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
    for row in rows:
        key = f"{row['status_code'] // 100}xx"
        if key in classes:
            classes[key] += row["count"]
    return {"codes": rows, "classes": [{"class": k, "count": v} for k, v in classes.items()]}


def top_endpoints(queryset: QuerySet, limit: int = 10) -> list:
    return list(
        queryset.exclude(endpoint="").values("endpoint")
        .annotate(hits=Count("id"), avg_response_ms=Avg("response_time_ms"),
                  errors=Count("id", filter=Q(level__in=ERROR_LEVELS)))
        .order_by("-hits", "endpoint")[:limit]
    )


def most_common_errors(queryset: QuerySet, limit: int = 10) -> list:
    rows = (
        queryset.filter(level__in=ERROR_LEVELS).values("message", service_name=F("service__name"))
        .annotate(occurrences=Count("id")).order_by("-occurrences", "message")[:limit]
    )
    return [{"message": r["message"], "service": r["service_name"], "occurrences": r["occurrences"]} for r in rows]


def recent_errors(queryset: QuerySet, limit: int = 10):
    return list(
        queryset.filter(level__in=ERROR_LEVELS).select_related("service", "host")
        .order_by("-timestamp", "-id")[:limit]
    )


# ---------------------------------------------------------------------------
# Raw SQL with window functions
# ---------------------------------------------------------------------------
_TABLE = LogEvent._meta.db_table
_TIME_FILTER = "(%s::timestamptz IS NULL OR {col} >= %s) AND (%s::timestamptz IS NULL OR {col} <= %s)"


def _time_params(start, end):
    return [start, start, end, end]


def request_rate_trend(start=None, end=None, limit: int = 30) -> list:
    """Requests per minute with a 5-minute moving average and minute-over-minute change.

    Window functions: AVG() OVER (ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) and LAG().
    Returns the most recent `limit` minutes in chronological order.
    """
    sql = f"""
        WITH per_minute AS (
            SELECT date_trunc('minute', timestamp) AS minute,
                   COUNT(*) AS requests,
                   COUNT(*) FILTER (WHERE status_code >= 500) AS server_errors,
                   AVG(response_time_ms) AS avg_response_ms
            FROM {_TABLE}
            WHERE http_method <> '' AND {_TIME_FILTER.format(col='timestamp')}
            GROUP BY 1
        )
        SELECT minute,
               requests,
               server_errors,
               ROUND((avg_response_ms)::numeric, 2) AS avg_response_ms,
               ROUND((AVG(requests) OVER (ORDER BY minute ROWS BETWEEN 4 PRECEDING AND CURRENT ROW))::numeric, 2)
                   AS moving_avg_5m,
               requests - LAG(requests) OVER (ORDER BY minute) AS change_vs_prev_minute
        FROM per_minute
        ORDER BY minute DESC
        LIMIT %s
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, _time_params(start, end) + [limit])
        rows = [_clean(r) for r in _rows(cursor)]
    return list(reversed(rows))


def top_errors_per_service(start=None, end=None, per_service: int = 3) -> list:
    """Top-N most frequent error messages for every service.

    Window function: ROW_NUMBER() OVER (PARTITION BY service ORDER BY COUNT(*) DESC).
    """
    sql = f"""
        SELECT service, message, occurrences, rank_in_service FROM (
            SELECT s.name AS service,
                   e.message,
                   COUNT(*) AS occurrences,
                   ROW_NUMBER() OVER (PARTITION BY s.name ORDER BY COUNT(*) DESC, e.message) AS rank_in_service
            FROM {_TABLE} e
            JOIN logs_service s ON s.id = e.service_id
            WHERE e.level IN ('ERROR', 'CRITICAL') AND {_TIME_FILTER.format(col='e.timestamp')}
            GROUP BY s.name, e.message
        ) ranked
        WHERE rank_in_service <= %s
        ORDER BY service, rank_in_service
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, _time_params(start, end) + [per_service])
        return [_clean(r) for r in _rows(cursor)]


def build_report(queryset: QuerySet, start=None, end=None, top_n: int = 10) -> dict:
    """Everything the dashboard and GET /api/analytics/ need, computed from one filtered queryset."""
    overview = summary(queryset)
    first, last = overview.pop("_first"), overview.pop("_last")
    return {
        "summary": overview,
        "requests": requests_per_minute(queryset),
        "logs_over_time": logs_over_time(queryset, first, last),
        "by_level": by_level(queryset),
        "by_service": by_service(queryset),
        "status_distribution": status_distribution(queryset),
        "top_endpoints": top_endpoints(queryset, top_n),
        "most_common_errors": most_common_errors(queryset, top_n),
        "top_errors_per_service": top_errors_per_service(start, end),
        "request_rate_trend": request_rate_trend(start, end),
    }
