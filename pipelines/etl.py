"""ETL orchestration: parse -> validate -> deduplicate -> transform -> load, in batches."""
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional

from .dedupe import Deduplicator
from .parsers import parse_line
from .reader import batched
from .record import LogRecord, RecordRejected
from .transform import transform_record
from .validation import validate_record

Loader = Callable[[List[LogRecord]], int]


@dataclass
class PipelineStats:
    read: int = 0  # non-blank lines seen
    loaded: int = 0
    rejected: int = 0
    duplicates: int = 0
    batches: int = 0
    reject_reasons: Counter = field(default_factory=Counter)


class Pipeline:
    """Processes an iterable of lines in fixed-size batches, so memory use is O(batch_size).

    `loader(records) -> int` persists a batch and returns how many rows were newly inserted;
    anything it skips (already in the database) is counted as a duplicate.
    """

    def __init__(
        self,
        loader: Loader,
        *,
        batch_size: int = 1000,
        default_service: Optional[str] = None,
        default_host: Optional[str] = None,
        dedupe_window: int = 100_000,
        on_reject: Optional[Callable[[int, str, str], None]] = None,
        on_batch: Optional[Callable[[PipelineStats], None]] = None,
    ):
        self.loader = loader
        self.batch_size = batch_size
        self.default_service = default_service
        self.default_host = default_host
        self.deduplicator = Deduplicator(dedupe_window)
        self.on_reject = on_reject
        self.on_batch = on_batch
        self.stats = PipelineStats()

    def _reject(self, lineno: int, line: str, reason: str) -> None:
        self.stats.rejected += 1
        self.stats.reject_reasons[reason] += 1
        if self.on_reject:
            self.on_reject(lineno, line, reason)

    def _parse_batch(self, numbered_lines) -> List[LogRecord]:
        valid: List[LogRecord] = []
        for lineno, line in numbered_lines:
            if not line.strip():
                continue
            self.stats.read += 1
            try:
                raw = parse_line(line, self.default_service, self.default_host)
                valid.append(validate_record(raw, raw_line=line.strip()))
            except RecordRejected as exc:
                self._reject(lineno, line, exc.reason)
        return valid

    def run(self, lines: Iterable[str]) -> PipelineStats:
        for chunk in batched(enumerate(lines, start=1), self.batch_size):
            valid = self._parse_batch(chunk)
            unique, duplicates = self.deduplicator.filter(valid)
            self.stats.duplicates += duplicates
            records = [transform_record(record) for record in unique]
            if records:
                inserted = self.loader(records)
                self.stats.loaded += inserted
                self.stats.duplicates += len(records) - inserted
            self.stats.batches += 1
            if self.on_batch:
                self.on_batch(self.stats)
        return self.stats
