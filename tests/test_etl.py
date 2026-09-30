import gzip
import os
import tempfile
import unittest
from datetime import datetime, timezone

from pipelines.etl import Pipeline
from pipelines.generator import generate_lines
from pipelines.reader import batched, read_lines

GOOD_JSON = '{"timestamp":"2026-09-30T10:00:00Z","level":"ERROR","service":"a","host":"h","message":"boom"}'
GOOD_APP = "2026-09-30 10:00:01,000 INFO     [b] (h) fine"
GOOD_NGINX = '10.0.0.1 - - [30/Sep/2026:10:00:02 +0000] "GET /x HTTP/1.1" 500 12 "-" "curl" rt=0.100'


class MemoryLoader:
    """In-memory sink that mimics the database UNIQUE(fingerprint) behaviour."""

    def __init__(self):
        self.rows, self.batch_sizes = {}, []

    def __call__(self, records):
        self.batch_sizes.append(len(records))
        inserted = 0
        for r in records:
            if r.fingerprint not in self.rows:
                self.rows[r.fingerprint] = r
                inserted += 1
        return inserted


class EtlTests(unittest.TestCase):
    def test_end_to_end_counts_and_reasons(self):
        lines = [GOOD_JSON, GOOD_APP, GOOD_NGINX, "", "garbage", '{"level":"INFO","message":"no ts"}',
                 GOOD_JSON,  # duplicate
                 '{"timestamp":"nope","level":"INFO","message":"x"}']
        loader, rejected = MemoryLoader(), []
        stats = Pipeline(loader, batch_size=3, on_reject=lambda n, l, r: rejected.append((n, r))).run(lines)
        self.assertEqual((stats.read, stats.loaded, stats.rejected, stats.duplicates), (7, 3, 3, 1))
        self.assertEqual(dict(stats.reject_reasons),
                         {"malformed_line": 1, "missing_timestamp": 1, "invalid_timestamp": 1})
        self.assertEqual(rejected[0], (5, "malformed_line"))  # line numbers refer to the original file (blank counted)
        levels = {r.source_format: r.level for r in loader.rows.values()}
        self.assertEqual(levels, {"json": "ERROR", "app": "INFO", "access": "ERROR"})  # 500 -> ERROR derived

    def test_processing_is_batched(self):
        loader = MemoryLoader()
        lines = generate_lines(2500, seed=1, bad_ratio=0, duplicate_ratio=0)
        stats = Pipeline(loader, batch_size=1000).run(lines)
        self.assertEqual(stats.batches, 3)
        self.assertLessEqual(max(loader.batch_sizes), 1000)
        self.assertEqual(stats.loaded, 2500)

    def test_input_is_consumed_lazily(self):
        consumed = []

        def source():
            for i in range(50):
                consumed.append(i)
                yield GOOD_APP.replace("10:00:01", f"10:00:{i:02d}")

        seen_at_first_load = []

        def loader(records):
            seen_at_first_load.append(len(consumed))
            return len(records)

        Pipeline(loader, batch_size=10).run(source())
        self.assertEqual(seen_at_first_load[0], 10)  # only one batch had been read when loading started

    def test_reloading_same_data_is_idempotent(self):
        loader = MemoryLoader()
        lines = [GOOD_JSON, GOOD_APP, GOOD_NGINX]
        Pipeline(loader).run(lines)
        stats = Pipeline(loader).run(lines)
        self.assertEqual((stats.loaded, stats.duplicates), (0, 3))
        self.assertEqual(len(loader.rows), 3)

    def test_default_service_and_host_apply_to_access_logs(self):
        loader = MemoryLoader()
        Pipeline(loader, default_service="Shop", default_host="Web-1").run([GOOD_NGINX])
        record = next(iter(loader.rows.values()))
        self.assertEqual((record.service, record.host, record.response_time_ms), ("shop", "web-1", 100.0))

    def test_reader_handles_plain_and_gzip_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain, packed = os.path.join(tmp, "a.log"), os.path.join(tmp, "a.log.gz")
            with open(plain, "w", newline= "") as f:
                f.write(GOOD_APP + "\r\n" + GOOD_JSON + "\n")
            with gzip.open(packed, "wt", newline="") as f:
                f.write(GOOD_APP + "\n" + GOOD_JSON + "\n")
            self.assertEqual(list(read_lines(plain)), [GOOD_APP, GOOD_JSON])
            self.assertEqual(list(read_lines(packed)), [GOOD_APP, GOOD_JSON])

    def test_batched_helper(self):
        self.assertEqual(list(batched(range(5), 2)), [[0, 1], [2, 3], [4]])
        with self.assertRaises(ValueError):
            list(batched([], 0))


class GeneratorTests(unittest.TestCase):
    END = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)

    def test_deterministic_with_seed(self):
        a = list(generate_lines(200, seed=7, end=self.END))
        b = list(generate_lines(200, seed=7, end=self.END))
        self.assertEqual(a, b)
        self.assertEqual(len(a), 200)

    def test_every_format_is_parseable_and_quality_issues_are_injected(self):
        for fmt in ("mixed", "json", "nginx", "app"):
            loader = MemoryLoader()
            stats = Pipeline(loader).run(generate_lines(1000, fmt=fmt, seed=5, end=self.END,
                                                        bad_ratio=0.05, duplicate_ratio=0.05))
            self.assertGreater(stats.rejected, 0, fmt)
            self.assertGreater(stats.duplicates, 0, fmt)
            self.assertEqual(stats.read, 1000)
            self.assertEqual(stats.loaded + stats.duplicates + stats.rejected, 1000, fmt)

    def test_clean_output_has_no_rejects(self):
        stats = Pipeline(MemoryLoader()).run(generate_lines(500, seed=2, end=self.END, bad_ratio=0, duplicate_ratio=0))
        self.assertEqual((stats.rejected, stats.duplicates, stats.loaded), (0, 0, 500))

    def test_invalid_format_raises(self):
        with self.assertRaises(ValueError):
            list(generate_lines(1, fmt="xml"))


if __name__ == "__main__":
    unittest.main()
