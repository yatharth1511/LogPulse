from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.logs.models import PipelineRun

from ...services import run_pipeline


class Command(BaseCommand):
    help = "Run the ETL pipeline (parse, validate, dedupe, transform, load) on one or more log files."

    def add_arguments(self, parser):
        parser.add_argument("files", nargs="+", help="Log file(s); .gz is supported")
        parser.add_argument("--batch-size", type=int, help="Records per batch (default: LOGPULSE_BATCH_SIZE)")
        parser.add_argument("--service", help="Default service name for lines that do not carry one")
        parser.add_argument("--host", help="Default host name for lines that do not carry one")
        parser.add_argument("--rejects-file", help="Append rejected lines (lineno, reason, raw) to this file")

    def handle(self, *args, **opts):
        failed = False
        for name in opts["files"]:
            path = Path(name)
            if not path.is_file():
                raise CommandError(f"File not found: {path}")
            if opts["rejects_file"]:
                Path(opts["rejects_file"]).parent.mkdir(parents=True, exist_ok=True)
            run = run_pipeline(
                path, service=opts["service"], host=opts["host"], batch_size=opts["batch_size"],
                rejects_path=opts["rejects_file"],
            )
            self.stdout.write(
                f"[run #{run.id}] {path.name}: {run.status} | read={run.records_processed} "
                f"loaded={run.records_loaded} rejected={run.records_rejected} "
                f"duplicates={run.records_duplicate} in {run.duration_seconds}s"
            )
            for reason, count in sorted(run.reject_reasons.items(), key=lambda kv: -kv[1]):
                self.stdout.write(f"    rejected {count:>6}  {reason}")
            failed = failed or run.status == PipelineRun.Status.FAILED
        if failed:
            raise CommandError("At least one file failed: every record was rejected.")
