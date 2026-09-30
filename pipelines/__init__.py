"""LogPulse ETL package: pure Python, no Django imports.

Stages: read -> parse -> validate/normalize -> deduplicate -> transform -> load.
The loader is injected, so the same pipeline works with PostgreSQL or an in-memory sink.
"""
from .etl import Pipeline, PipelineStats  # noqa: F401
from .record import LogRecord, RecordRejected  # noqa: F401
