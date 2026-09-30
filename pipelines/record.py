from dataclasses import dataclass
from datetime import datetime
from typing import Optional

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class RecordRejected(Exception):
    """Raised by parsing/validation. `reason` is a short machine-readable code."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass
class LogRecord:
    """Normalized log record shared by every input format."""

    timestamp: datetime  # timezone-aware, UTC
    service: str
    host: str
    message: str = ""
    level: Optional[str] = None
    http_method: str = ""
    endpoint: str = ""
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    ip_address: Optional[str] = None
    source_format: str = ""
    raw: str = ""
    fingerprint: str = ""
