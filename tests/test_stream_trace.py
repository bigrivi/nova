"""The stream tracer is the instrument for a turn that never ends, so it has to
report faithfully: a missed beat hides the hang, and a wrong count sends the
diagnosis in the wrong direction."""

from __future__ import annotations

import logging

import pytest

from nova.llm import stream_trace as module
from nova.llm.stream_trace import StreamTrace


class _Clock:
    """A hand-advanced monotonic clock, so beat timing is exact not timed."""

    def __init__(self) -> None:
        self.now = 1000.0

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(module.time, "monotonic", lambda: fake.now)
    return fake


def _lines(records) -> list[str]:
    return [r.getMessage() for r in records]


class TestLineAccounting:
    def test_it_counts_reads_and_records_the_head(self, caplog):
        trace = StreamTrace("p", "m")
        with caplog.at_level(logging.INFO, logger=module.__name__):
            trace.opened()
            for i in range(3):
                trace.line(b'data: {"i":%d}\n' % i)
        assert trace.reads == 3
        assert trace._head == ['data: {"i":0}', 'data: {"i":1}', 'data: {"i":2}']

    def test_the_head_stops_at_the_log_cap_but_reads_keep_counting(self, caplog):
        trace = StreamTrace("p", "m")
        with caplog.at_level(logging.INFO, logger=module.__name__):
            for _ in range(module._HEAD_LINES * 4):
                trace.line(b"data: x\n")
        assert trace.reads == module._HEAD_LINES * 4
        assert len(trace._head) == module._HEAD_LINES
        # One log line per head entry, plus the open: no per-line spam.
        assert len(_lines(caplog.records)) == module._HEAD_LINES

    def test_the_tail_keeps_the_last_lines(self, caplog):
        trace = StreamTrace("p", "m")
        with caplog.at_level(logging.INFO, logger=module.__name__):
            for i in range(module._TAIL_LINES * 3):
                trace.line(f"line-{i}\n".encode())
        assert list(trace._tail) == [
            f"line-{i}"
            for i in range(
                module._TAIL_LINES * 3 - module._TAIL_LINES, module._TAIL_LINES * 3
            )
        ]

    def test_a_long_line_is_truncated_in_the_log(self, caplog):
        trace = StreamTrace("p", "m")
        with caplog.at_level(logging.INFO, logger=module.__name__):
            trace.line(b"x" * (module._MAX_LINE_CHARS * 3))
        assert len(trace._head[0]) == module._MAX_LINE_CHARS

    def test_it_accepts_bytes_and_str_alike(self, caplog):
        trace = StreamTrace("p", "m")
        with caplog.at_level(logging.INFO, logger=module.__name__):
            trace.line(b"a\n")
            trace.line("b\n")
        assert trace._head == ["a", "b"]


class TestHeartbeat:
    def test_a_silent_peer_reports_rising_idle_and_no_reads(self, caplog, clock):
        trace = StreamTrace("p", "m")
        with caplog.at_level(logging.INFO, logger=module.__name__):
            for _ in range(25):
                trace.idle_read()
                clock.advance(1.0)
        beats = [m for m in _lines(caplog.records) if m.startswith("Stream beat")]
        # One beat per completed interval, and the first lands at 10s.
        assert len(beats) == 2, beats
        assert "reads=0" in beats[0]
        # The read that crosses the interval is the one that reports it.
        assert "idle=11" in beats[0]
        assert "idle=21" in beats[1]

    def test_a_flooding_peer_reports_rising_reads(self, caplog, clock):
        trace = StreamTrace("p", "m")
        with caplog.at_level(logging.INFO, logger=module.__name__):
            # A fast flood inside one interval produces no log line of its own;
            # the next beat is what makes the volume visible.
            for _ in range(2000):
                trace.line(b"data: x\n")
            clock.advance(module._BEAT_SECONDS)
            trace.line(b"data: x\n")
        beats = [m for m in _lines(caplog.records) if m.startswith("Stream beat")]
        assert len(beats) == 1, beats
        assert "reads=2001" in beats[0]
        assert "idle=0" in beats[0]

    def test_no_beat_before_the_interval_elapses(self, caplog, clock):
        trace = StreamTrace("p", "m")
        with caplog.at_level(logging.INFO, logger=module.__name__):
            # 10 lines at half a beat each: well inside one interval.
            for _ in range(10):
                trace.line(b"data: x\n")
                clock.advance(module._BEAT_SECONDS / 20)
        beats = [m for m in _lines(caplog.records) if m.startswith("Stream beat")]
        assert not beats, beats


class TestTermination:
    def test_end_reports_the_reason_counts_and_both_ends(self, caplog, clock):
        trace = StreamTrace("openai-responses", "muse")
        with caplog.at_level(logging.INFO, logger=module.__name__):
            for i in range(module._HEAD_LINES + 2):
                trace.line(f"line-{i}\n".encode())
            trace.idle_read()
            clock.advance(2.5)
            trace.end("peer closed", content=42)
        end = [m for m in _lines(caplog.records) if m.startswith("Stream end")]
        assert len(end) == 1, end
        assert "reason=peer closed" in end[0]
        assert f"reads={module._HEAD_LINES + 2}" in end[0]
        assert "idle=1" in end[0]
        assert "2.5s" in end[0]
        assert "content=42" in end[0]
        head = [m for m in _lines(caplog.records) if m.startswith("Stream head")]
        assert "line-0" in head[0]
        tail = [m for m in _lines(caplog.records) if m.startswith("Stream tail")]
        assert f"line-{module._HEAD_LINES + 1}" in tail[0]

    def test_mark_names_an_event_with_the_read_count(self, caplog):
        trace = StreamTrace("p", "m")
        with caplog.at_level(logging.INFO, logger=module.__name__):
            trace.line(b"data: [DONE]\n")
            trace.mark("[DONE] read past, loop continues")
        marks = [m for m in _lines(caplog.records) if m.startswith("Stream mark")]
        assert len(marks) == 1, marks
        assert "after 1 lines" in marks[0]
        assert "[DONE] read past" in marks[0]
