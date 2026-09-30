"""Streaming file access: lines are read lazily, never the whole file."""
import gzip
from itertools import islice
from typing import Iterable, Iterator, List


def open_log(path):
    path = str(path)
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "r", encoding="utf-8", errors="replace")


def read_lines(path) -> Iterator[str]:
    with open_log(path) as handle:
        for line in handle:
            yield line.rstrip("\r\n")


def batched(iterable: Iterable, size: int) -> Iterator[List]:
    if size < 1:
        raise ValueError("batch size must be >= 1")
    iterator = iter(iterable)
    while True:
        chunk = list(islice(iterator, size))
        if not chunk:
            return
        yield chunk
