import unittest
from datetime import datetime, timezone

from pipelines.dedupe import Deduplicator, compute_fingerprint
from pipelines.record import LogRecord


def rec(message="m", second=0, **kw):
    return LogRecord(timestamp=datetime(2026, 9, 30, 10, 0, second, tzinfo=timezone.utc),
                     service="svc", host="h", message=message, level="INFO", **kw)


class DedupeTests(unittest.TestCase):
    def test_fingerprint_is_stable_and_sensitive_to_content(self):
        self.assertEqual(compute_fingerprint(rec()), compute_fingerprint(rec()))
        self.assertEqual(len(compute_fingerprint(rec())), 64)
        self.assertNotEqual(compute_fingerprint(rec()), compute_fingerprint(rec(message="other")))
        self.assertNotEqual(compute_fingerprint(rec()), compute_fingerprint(rec(second=1)))
        self.assertNotEqual(compute_fingerprint(rec()), compute_fingerprint(rec(status_code=500)))

    def test_duplicates_within_a_batch_are_removed(self):
        unique, dups = Deduplicator().filter([rec(), rec(), rec(message="b"), rec()])
        self.assertEqual((len(unique), dups), (2, 2))
        self.assertTrue(all(r.fingerprint for r in unique))

    def test_cross_batch_duplicate_counted(self):
        dedupe = Deduplicator()
        dedupe.filter([rec()])
        unique, dups = dedupe.filter([rec(), rec(message="new")])
        self.assertEqual((len(unique), dups), (1, 1))

    def test_window_is_bounded_so_memory_is_constant(self):
        dedupe = Deduplicator(window=3)
        dedupe.filter([rec(message=str(i)) for i in range(10)])
        self.assertEqual(len(dedupe._seen), 3)
        unique, dups = dedupe.filter([rec(message="0")])  # evicted long ago: passes (the DB constraint catches it)
        self.assertEqual((len(unique), dups), (1, 0))


if __name__ == "__main__":
    unittest.main()
