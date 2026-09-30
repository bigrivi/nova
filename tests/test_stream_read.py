"""StreamPoller, and the freeze it exists to prevent.

The reported failure: a turn that had produced nothing, a process pinned at
100% CPU for hours, and a log showing the read loop had issued some fourteen
million reads while the peer sent nine lines and then nothing. The loop was
polling ``wait_for(readline(), 0.5)``, and after aiohttp's total timeout fired
that read failed instantly forever - which the loop read as "still working" and
answered with ``continue``.

These tests pin the two halves of that: the old pattern really does spin on a
stream that fails immediately, and the poller does not.
"""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import SocketTimeoutError

from nova.llm.stream_read import StreamAborted, StreamPoller, StreamTimeout
from nova.llm.stream_trace import StreamTrace

POLL = 0.01


def _trace(name: str = "test") -> StreamTrace:
    return StreamTrace(name, "m")


class _Counter:
    """A read_line whose calls and behaviour the test controls."""

    def __init__(self, behaviour) -> None:
        self.calls = 0
        self._behaviour = behaviour

    def __call__(self):
        self.calls += 1
        return self._behaviour()


class TestTheFreeze:
    @pytest.mark.asyncio
    async def test_the_replaced_pattern_reissues_the_read_for_every_timeout(self):
        """Why the poller exists: this is what the old loop did.

        A read that raises at once is how aiohttp behaves once the request's
        total timeout has fired - it raises from the entry of the wait without
        touching the socket. The old handler could not tell that from a quiet
        peer, so ``except TimeoutError: continue`` issued a fresh read each
        time, forever.

        The loop is driven a fixed number of rounds rather than run to a
        timeout on purpose. Run for real it never yields: the spin starves the
        event loop so completely that even the timer meant to stop it cannot
        fire, which is why a wedged desktop app stayed wedged for hours. A
        wall-clock assertion here would hang instead of fail.
        """

        async def fail_now() -> bytes:
            raise TimeoutError

        read = _Counter(fail_now)

        async def one_round() -> bool:
            """The old loop body: True if it would keep going."""
            try:
                await asyncio.wait_for(read(), timeout=POLL)
            except TimeoutError:
                return True
            return False

        rounds = 50
        for _ in range(rounds):
            assert await one_round() is True
        # 50 rounds, 50 reads: nothing ever stopped it.
        assert read.calls == rounds

    @pytest.mark.asyncio
    async def test_the_poller_propagates_an_instantly_failing_read(self):
        """The fix: a failure from the stream ends the turn instead of looping."""

        async def fail_now() -> bytes:
            raise TimeoutError

        read = _Counter(fail_now)
        poller = StreamPoller(read, None, _trace(), poll_seconds=POLL)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(poller.next_line(), timeout=1.0)
        # One read, not hundreds: it is never re-issued.
        assert read.calls == 1
        assert poller.pending is False

    @pytest.mark.asyncio
    async def test_a_stream_failure_carries_a_message(self):
        """aiohttp's own TimeoutError stringifies to "", which is unusable."""

        async def fail_now() -> bytes:
            raise TimeoutError

        poller = StreamPoller(_Counter(fail_now), None, _trace(), poll_seconds=POLL)
        with pytest.raises(StreamTimeout) as caught:
            await poller.next_line()
        assert "total timeout" in str(caught.value)
        # The original is still reachable for anyone debugging.
        assert isinstance(caught.value.__cause__, asyncio.TimeoutError)

    @pytest.mark.asyncio
    async def test_a_socket_read_timeout_is_described_differently(self):
        """sock_read and total are different limits; the text must say which.

        aiohttp raises ``SocketTimeoutError`` - a connection error, not a
        ``TimeoutError`` - when the socket goes quiet, so a single message for
        both would send anyone reading the log after the wrong one.
        """

        async def idle_socket() -> bytes:
            raise SocketTimeoutError("Timeout on reading data from socket")

        poller = StreamPoller(_Counter(idle_socket), None, _trace(), poll_seconds=POLL)
        with pytest.raises(StreamTimeout) as caught:
            await poller.next_line()
        assert "socket read timeout" in str(caught.value)
        assert "total timeout" not in str(caught.value)
        assert isinstance(caught.value.__cause__, SocketTimeoutError)

    @pytest.mark.asyncio
    async def test_a_read_cancelled_from_outside_ends_the_turn(self):
        """A read cancelled by the stream, while we are not, is a failure.

        aiohttp's total timer cancels the read task rather than raising into
        it. That must not be mistaken for our own cancellation, which has to
        propagate.
        """

        async def cancelled_read() -> bytes:
            raise asyncio.CancelledError

        poller = StreamPoller(
            _Counter(cancelled_read), None, _trace(), poll_seconds=POLL
        )
        # Not an outer CancelledError: our task is not being cancelled.
        with pytest.raises(StreamTimeout) as caught:
            await poller.next_line()
        assert "cancelled" in str(caught.value)


class TestQuietPeer:
    @pytest.mark.asyncio
    async def test_a_quiet_peer_polls_without_restarting_the_read(self):
        """The read stays in flight; polling must not cancel and re-issue it."""
        reads = _Counter(lambda: asyncio.Event().wait())
        poller = StreamPoller(reads, None, _trace(), poll_seconds=POLL)

        task = asyncio.ensure_future(poller.next_line())
        await asyncio.sleep(POLL * 8)
        assert poller.pending is True
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # One read for the whole wait, however many polls happened.
        assert reads.calls == 1
        # ...and the polls were recorded as idle, so the hang stays visible.
        assert poller.pending is False

    @pytest.mark.asyncio
    async def test_lines_are_returned_in_order(self):
        script = [b"one\n", b"two\n", b""]

        async def read_line() -> bytes:
            return script.pop(0)

        poller = StreamPoller(read_line, None, _trace(), poll_seconds=POLL)
        assert await poller.next_line() == b"one\n"
        assert await poller.next_line() == b"two\n"
        # End of stream is a falsey line, not an exception.
        assert not await poller.next_line()
        assert poller.pending is False

    @pytest.mark.asyncio
    async def test_an_iterator_read_line_passes_stop_async_iteration_through(self):
        """The Chat Completions provider reads via ``it.__anext__``.

        There, end of stream is ``StopAsyncIteration`` rather than an empty
        line. The poller must hand it through untouched so the provider can
        treat it as a clean close - and must not mistake it for a failure and
        leave the read running.
        """

        async def exhausted() -> bytes:
            raise StopAsyncIteration

        read = _Counter(exhausted)
        poller = StreamPoller(read, None, _trace(), poll_seconds=POLL)

        with pytest.raises(StopAsyncIteration):
            await poller.next_line()
        assert read.calls == 1
        assert poller.pending is False


class TestAbort:
    @pytest.mark.asyncio
    async def test_abort_while_a_read_is_pending_raises_and_leaves_nothing(self):
        abort = asyncio.Event()
        reads = _Counter(lambda: asyncio.Event().wait())
        poller = StreamPoller(reads, abort, _trace(), poll_seconds=POLL)

        task = asyncio.ensure_future(poller.next_line())
        await asyncio.sleep(POLL * 3)
        assert poller.pending is True

        abort.set()
        with pytest.raises(StreamAborted):
            await asyncio.wait_for(task, timeout=1.0)
        assert poller.pending is False
        assert reads.calls == 1

    @pytest.mark.asyncio
    async def test_abort_before_any_read_never_starts_one(self):
        abort = asyncio.Event()
        abort.set()
        reads = _Counter(lambda: asyncio.Event().wait())
        poller = StreamPoller(reads, abort, _trace(), poll_seconds=POLL)

        with pytest.raises(StreamAborted):
            await poller.next_line()
        assert reads.calls == 0

    @pytest.mark.asyncio
    async def test_no_abort_event_means_no_abort(self):
        script = [b"line\n"]

        async def read_line() -> bytes:
            return script.pop(0)

        poller = StreamPoller(read_line, None, _trace(), poll_seconds=POLL)
        assert await poller.next_line() == b"line\n"

    @pytest.mark.asyncio
    async def test_abort_is_acted_on_at_once_not_at_the_poll_boundary(self):
        """The abort is raced against the read, so a long poll cannot delay it.

        The poll interval only governs the idle trace; if abort were noticed
        only when a poll expired, a five second interval would mean five
        seconds of unresponsive ESC.
        """
        abort = asyncio.Event()
        reads = _Counter(lambda: asyncio.Event().wait())
        poller = StreamPoller(reads, abort, _trace(), poll_seconds=5.0)

        task = asyncio.ensure_future(poller.next_line())
        await asyncio.sleep(0.02)
        started = asyncio.get_running_loop().time()
        abort.set()
        with pytest.raises(StreamAborted):
            await asyncio.wait_for(task, timeout=1.0)
        elapsed = asyncio.get_running_loop().time() - started

        assert elapsed < 0.5, f"abort waited for the poll interval ({elapsed:.2f}s)"
        assert poller.pending is False

    @pytest.mark.asyncio
    async def test_outer_cancellation_propagates_and_leaves_no_tasks(self):
        """Cancelling the turn must cancel the read and leave nothing behind."""
        reads = _Counter(lambda: asyncio.Event().wait())
        poller = StreamPoller(reads, None, _trace(), poll_seconds=POLL)
        before = asyncio.all_tasks()

        task = asyncio.ensure_future(poller.next_line())
        await asyncio.sleep(POLL * 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Let the cancelled read and abort waiter settle.
        await asyncio.sleep(0)

        leftover = asyncio.all_tasks() - before
        assert not leftover, [t.get_name() for t in leftover]
        assert poller.pending is False


class TestCleanup:
    @pytest.mark.asyncio
    async def test_no_unretrieved_task_warning_after_a_failed_read(self, caplog):
        """A failed read has to be settled, not left to the garbage collector."""

        async def fail_now() -> bytes:
            raise ValueError("boom")

        poller = StreamPoller(_Counter(fail_now), None, _trace(), poll_seconds=POLL)
        with pytest.raises(ValueError):
            await poller.next_line()
        await poller.aclose()
        await asyncio.sleep(0)

        complaints = [
            r.getMessage()
            for r in caplog.records
            if "never retrieved" in r.getMessage()
        ]
        assert not complaints, complaints
        assert poller.pending is False

    @pytest.mark.asyncio
    async def test_aclose_is_safe_when_nothing_is_pending(self):
        poller = StreamPoller(lambda: asyncio.Event().wait(), None, _trace())
        await poller.aclose()
        assert poller.pending is False

    @pytest.mark.asyncio
    async def test_a_cancelled_next_line_cancels_the_read(self):
        """A cancelled turn must not leave a read alive on a closing response."""
        started = asyncio.Event()
        finished = asyncio.Event()

        async def read_line() -> bytes:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()
            return b""

        poller = StreamPoller(read_line, None, _trace(), poll_seconds=POLL)
        task = asyncio.ensure_future(poller.next_line())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
        assert poller.pending is False
