import os
import tempfile

from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.logs.models import LogEvent


class Command(BaseCommand):
    help = "Generate and load demo data, but only when the database has no logs yet."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=10000)

    def handle(self, *args, **opts):
        if LogEvent.objects.exists():
            self.stdout.write("Logs already present; skipping demo seed.")
            return
        handle, path = tempfile.mkstemp(prefix="logpulse_demo_", suffix=".log")
        os.close(handle)
        try:
            call_command("generate_logs", count=opts["count"], output=path, days=1.0, seed=42, stdout=self.stdout)
            call_command("process_logs", path, stdout=self.stdout)
        finally:
            os.unlink(path)
