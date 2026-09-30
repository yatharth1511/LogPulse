import sys
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from pipelines.generator import FORMATS, generate_lines


class Command(BaseCommand):
    help = "Generate synthetic logs (JSON lines, nginx access logs, application logs)."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=10000, help="Number of lines (default 10000)")
        parser.add_argument("--output", default="sample_logs/generated.log", help="Output file, or '-' for stdout")
        parser.add_argument("--format", choices=FORMATS, default="mixed")
        parser.add_argument("--days", type=float, default=1.0, help="Spread events over this many days")
        parser.add_argument("--end", help="End of the time window, ISO 8601 (default: now)")
        parser.add_argument("--seed", type=int, help="Random seed for reproducible output")
        parser.add_argument("--bad-ratio", type=float, default=0.01, help="Share of malformed lines")
        parser.add_argument("--duplicate-ratio", type=float, default=0.01, help="Share of duplicated lines")

    def handle(self, *args, **opts):
        if opts["count"] < 1:
            raise CommandError("--count must be >= 1")
        end = None
        if opts["end"]:
            try:
                end = datetime.fromisoformat(opts["end"].replace("Z", "+00:00"))
            except ValueError:
                raise CommandError("--end must be an ISO 8601 datetime") from None
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)

        lines = generate_lines(
            opts["count"], fmt=opts["format"], seed=opts["seed"], end=end, days=opts["days"],
            bad_ratio=opts["bad_ratio"], duplicate_ratio=opts["duplicate_ratio"],
        )
        if opts["output"] == "-":
            for line in lines:
                sys.stdout.write(line + "\n")
            return
        path = Path(opts["output"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            for line in lines:
                handle.write(line + "\n")
        self.stdout.write(self.style.SUCCESS(f"Wrote {opts['count']} lines to {path}"))
