"""Deduplication using a content fingerprint and a bounded LRU window (constant memory)."""
import hashlib
from collections import OrderedDict
from typing import Iterable, List, Tuple

from .record import LogRecord


def compute_fingerprint(record: LogRecord) -> str:
    parts = (
        record.timestamp.isoformat(),
        record.service,
        record.host,
        record.level or "",
        record.http_method,
        record.endpoint,
        "" if record.status_code is None else str(record.status_code),
        "" if record.response_time_ms is None else repr(record.response_time_ms),
        record.ip_address or "",
        record.message,
    )
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


class Deduplicator:
    """Drops records whose fingerprint was seen in the last `window` unique records.

    Duplicates that fall outside the window are still caught by the database's UNIQUE
    constraint on `fingerprint`, so correctness never depends on the window size.
    """

    def __init__(self, window: int = 100_000):
        self.window = max(1, window)
        self._seen: "OrderedDict[str, None]" = OrderedDict()

    def filter(self, records: Iterable[LogRecord]) -> Tuple[List[LogRecord], int]:
        unique: List[LogRecord] = []
        duplicates = 0
        for record in records:
            record.fingerprint = compute_fingerprint(record)
            if record.fingerprint in self._seen:
                self._seen.move_to_end(record.fingerprint)
                duplicates += 1
                continue
            self._seen[record.fingerprint] = None
            if len(self._seen) > self.window:
                self._seen.popitem(last=False)
            unique.append(record)
        return unique, duplicates
