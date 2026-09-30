"""Business logic for running the ETL pipeline and recording each run in PostgreSQL."""
import os
import tempfile
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.utils import timezone

from apps.logs.models import PipelineRun
from pipelines.etl import Pipeline, PipelineStats
from pipelines.reader import read_lines

from .loader import PostgresLoader


def _save_progress(run: PipelineRun, stats: PipelineStats) -> None:
    run.records_processed = stats.read
    run.records_loaded = stats.loaded
    run.records_rejected = stats.rejected
    run.records_duplicate = stats.duplicates
    run.reject_reasons = dict(stats.reject_reasons)


def run_pipeline(
    path,
    *,
    source_name: Optional[str] = None,
    service: Optional[str] = None,
    host: Optional[str] = None,
    batch_size: Optional[int] = None,
    rejects_path: Optional[str] = None,
) -> PipelineRun:
    """Process one log file and return the finished PipelineRun row."""
    run = PipelineRun.objects.create(source_file=(source_name or str(path))[:500])
    rejects_file = open(rejects_path, "a", encoding="utf-8") if rejects_path else None

    def on_reject(lineno: int, line: str, reason: str) -> None:
        if rejects_file:
            rejects_file.write(f"{lineno}\t{reason}\t{line}\n")

    pipeline = Pipeline(
        PostgresLoader(run),
        batch_size=batch_size or settings.LOGPULSE_BATCH_SIZE,
        default_service=service.lower() if service else None,
        default_host=host.lower() if host else None,
        dedupe_window=settings.LOGPULSE_DEDUPE_WINDOW,
        on_reject=on_reject,
    )
    try:
        stats = pipeline.run(read_lines(path))
    except Exception as exc:
        _save_progress(run, pipeline.stats)
        run.status = PipelineRun.Status.FAILED
        run.error_message = f"{type(exc).__name__}: {exc}"
        run.finished_at = timezone.now()
        run.save()
        raise
    finally:
        if rejects_file:
            rejects_file.close()

    _save_progress(run, stats)
    if stats.read > 0 and stats.rejected == stats.read:
        run.status = PipelineRun.Status.FAILED
        run.error_message = "Every record in the file was rejected."
    elif stats.rejected > 0:
        run.status = PipelineRun.Status.PARTIAL
    else:
        run.status = PipelineRun.Status.SUCCESS
    run.finished_at = timezone.now()
    run.save()
    return run


def run_pipeline_for_upload(upload, *, service: Optional[str] = None, host: Optional[str] = None) -> PipelineRun:
    """Persist an uploaded file to a temp path, run the pipeline, then delete the temp file."""
    suffix = Path(upload.name).suffix or ".log"
    handle, temp_path = tempfile.mkstemp(prefix="logpulse_upload_", suffix=suffix)
    try:
        with os.fdopen(handle, "wb") as out:
            for chunk in upload.chunks():
                out.write(chunk)
        return run_pipeline(temp_path, source_name=f"upload:{upload.name}", service=service, host=host)
    finally:
        os.unlink(temp_path)
