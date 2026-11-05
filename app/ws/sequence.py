"""Public stream sequence counter.

Distinct from the engine's fill/book sequence: this counter advances only for
messages actually delivered to public sockets. That makes it usable for gap
detection on the client without false positives caused by private-only events.
"""
from app.core.sequencer import SequenceGenerator

stream_sequencer = SequenceGenerator()


def next_stream_sequence() -> int:
    return stream_sequencer.next()
