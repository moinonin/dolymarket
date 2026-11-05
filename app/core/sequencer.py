"""Deterministic, monotonically increasing sequence numbers.

Every matched fill and order-book mutation receives a sequence id. Streaming
clients use these ids to detect dropped WebSocket packets and request a fresh
snapshot when a gap is observed.
"""
from __future__ import annotations

import threading


class SequenceGenerator:
    """Thread-safe process-wide monotonic counter (starts at 1)."""

    def __init__(self) -> None:
        self._value = 0
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            self._value += 1
            return self._value

    def current(self) -> int:
        with self._lock:
            return self._value

    def reset(self) -> None:
        with self._lock:
            self._value = 0


sequencer = SequenceGenerator()


def next_sequence_id() -> int:
    return sequencer.next()
