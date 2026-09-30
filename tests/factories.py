"""Small helpers for creating test data."""
import itertools
from datetime import datetime, timezone

from apps.logs.models import Host, LogEvent, Service

_counter = itertools.count(1)
BASE_TIME = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)


def make_event(*, service="api", host="h1", level="INFO", timestamp=None, message="hello", **kwargs):
    n = next(_counter)
    return LogEvent.objects.create(
        timestamp=timestamp or BASE_TIME,
        level=level,
        service=Service.objects.get_or_create(name=service)[0],
        host=Host.objects.get_or_create(name=host)[0],
        message=message,
        fingerprint=kwargs.pop("fingerprint", f"fp-{n:060d}"),
        **kwargs,
    )
