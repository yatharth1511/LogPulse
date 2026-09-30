"""Load stage: writes validated records to PostgreSQL in one transaction per batch."""
from typing import Dict, List, Optional

from django.db import transaction

from apps.logs.models import Host, LogEvent, PipelineRun, Service
from pipelines.record import LogRecord


class PostgresLoader:
    def __init__(self, pipeline_run: Optional[PipelineRun] = None):
        self.pipeline_run = pipeline_run
        self._services: Dict[str, Service] = {}
        self._hosts: Dict[str, Host] = {}

    def _service(self, name: str) -> Service:
        if name not in self._services:
            self._services[name] = Service.objects.get_or_create(name=name)[0]
        return self._services[name]

    def _host(self, name: str) -> Host:
        if name not in self._hosts:
            self._hosts[name] = Host.objects.get_or_create(name=name)[0]
        return self._hosts[name]

    def __call__(self, records: List[LogRecord]) -> int:
        """Insert a batch; returns how many rows were new (already-stored fingerprints are skipped)."""
        fingerprints = [r.fingerprint for r in records]
        existing = set(
            LogEvent.objects.filter(fingerprint__in=fingerprints).values_list("fingerprint", flat=True)
        )
        fresh = [r for r in records if r.fingerprint not in existing]
        events = [
            LogEvent(
                timestamp=r.timestamp,
                level=r.level,
                service=self._service(r.service),
                host=self._host(r.host),
                message=r.message,
                http_method=r.http_method,
                endpoint=r.endpoint,
                status_code=r.status_code,
                response_time_ms=r.response_time_ms,
                ip_address=r.ip_address,
                source_format=r.source_format,
                raw=r.raw,
                fingerprint=r.fingerprint,
                pipeline_run=self.pipeline_run,
            )
            for r in fresh
        ]
        with transaction.atomic():
            # ignore_conflicts makes concurrent runs safe: the UNIQUE(fingerprint) index is the last line of defence.
            LogEvent.objects.bulk_create(events, batch_size=1000, ignore_conflicts=True)
        return len(events)
