"""Shared HTTP transport and streaming template for the aiohttp providers.

``HttpProvider`` carries the parts that were copied across the OpenAI Chat,
OpenAI Responses, Anthropic and Ollama providers: connector and session
lifecycle, the abort-aware retrying POST, the non-streaming ``chat`` skeleton,
and the streaming ``chat_stream`` skeleton. Each provider subclass keeps only
its protocol translation - endpoint, headers, request body, non-stream response
parsing, and a :class:`~nova.llm.stream_driver.StreamParser` for the stream -
and declares its :class:`~nova.llm.policy.StreamPolicy` and
:class:`~nova.llm.policy.TransportPolicy` so behaviour that still differs
between providers stays explicit.
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import abstractmethod
from collections.abc import AsyncGenerator, Callable, Coroutine
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import aiohttp

from nova.llm.accumulator import StreamAccumulator
from nova.llm.framing import NDJSONFramer, SSEFramer
from nova.llm.policy import StreamPolicy, TransportPolicy
from nova.llm.provider import (
    MAX_RETRIES,
    RETRY_429_MAX_ATTEMPTS,
    RETRY_429_MAX_WAIT,
    RETRY_429_TOTAL_BUDGET,
    RETRY_BASE_DELAY,
    RETRY_STATUS_CODES,
    STREAM_IDLE_TIMEOUT_SECONDS,
    ChatStreamEvent,
    Done,
    Error,
    LLMProvider,
    RetryNotice,
    is_terminal_429,
)
from nova.llm.stream_driver import StreamParser, drive_stream
from nova.llm.stream_trace import StreamTrace

log = logging.getLogger(__name__)


async def sleep_unless_aborted(
    seconds: float, abort_event: asyncio.Event | None
) -> bool:
    """Wait out a retry delay, returning True when an abort arrives first.

    A backoff honours ``Retry-After``, which can name tens of seconds, so a
    sleep that ignores the abort event is a window where the user's cancel
    button does nothing -- the same silent hang the retry notice exists to
    explain.

    Args:
        seconds: How long to wait.
        abort_event: Set to cut the wait short; None waits the full time.

    Returns:
        True when the abort fired first, False when the wait was served.
    """
    if abort_event is None:
        await asyncio.sleep(seconds)
        return False
    if seconds <= 0:
        return abort_event.is_set()
    try:
        await asyncio.wait_for(abort_event.wait(), timeout=seconds)
    except TimeoutError:
        return False
    return True


class HttpProvider(LLMProvider):
    """Base class for the aiohttp-backed providers.

    Subclasses set the class attributes and implement the hooks below. The
    transport and stream skeletons here call them; nothing provider-specific
    lives in this class.

    Class attributes:
        framer: Turns a raw stream line into an event dict or None.
        stream_policy: Streaming behaviour switches.
        transport_policy: HTTP behaviour switches.
        trace_label: Provider name used in stream trace log lines.
    """

    framer: SSEFramer | NDJSONFramer = SSEFramer()
    stream_policy: StreamPolicy
    transport_policy: TransportPolicy
    trace_label: str = "http"

    # -- Hooks a subclass implements -------------------------------------

    @abstractmethod
    def _prepare_request(
        self,
        messages: list,
        model: str,
        stream: bool,
        tools: list[dict] | None,
        session_id: str | None,
        reasoning_effort: str | None,
    ) -> tuple[str, dict[str, str], dict]:
        """Return ``(url, headers, body)`` for one request.

        Args:
            messages: Caller messages, still in Nova's shape.
            model: Model id to run with.
            stream: Whether this is the streaming request.
            tools: Tool schemas, or None.
            session_id: Session the call belongs to, for per-session hooks and
                prompt-cache keying.
            reasoning_effort: Per-turn reasoning level, or None.
        """

    @abstractmethod
    def _parse_response(self, data: dict) -> Done:
        """Turn a non-streaming JSON body into a ``Done``."""

    @abstractmethod
    def _new_parser(self, model: str) -> StreamParser:
        """Create a fresh stream parser for one streaming turn."""

    # -- Shared transport pieces -----------------------------------------

    def _make_connector(self) -> aiohttp.TCPConnector:
        return aiohttp.TCPConnector(**self.transport_policy.connector_kwargs)

    @staticmethod
    def _build_http_error_message(url: str, status: int, text: str) -> str:
        detail = (text or "").strip() or "<empty response>"
        return f"HTTP {status} from {url}: {detail}"

    @staticmethod
    def _post_kwargs(headers: dict, body: dict) -> dict:
        # Every provider now sends at least its User-Agent, so this is a guard
        # rather than the normal path: a caller with no headers must not be
        # handed an empty ``headers`` kwarg it never used to receive.
        kwargs: dict = {"json": body}
        if headers:
            kwargs["headers"] = headers
        return kwargs

    @staticmethod
    def _retry_after_seconds(resp: aiohttp.ClientResponse, fallback: float) -> float:
        """The ``Retry-After`` header as seconds, capped, or *fallback*.

        RFC 7231 section 7.1.3 allows the header in two forms and servers use
        both: a count of seconds (``Retry-After: 120``) and an absolute date
        (``Retry-After: Wed, 21 Oct 2015 07:28:00 GMT``). Only the first is
        parseable as a float, so reading it that way alone silently ignores every
        server that names a time instead of a delay -- and those are exactly the
        ones whose answer is worth having, since an absolute date is what a
        shared cache or a gateway in front of the model emits.

        Read on both the 429 and the 5xx paths. An endpoint that says when it
        will be back is being told to be waited for, which is better information
        than any backoff this class could invent.

        Args:
            resp: The response carrying the header. ``headers`` is a
                ``CIMultiDict``, so the lookup is case-insensitive and one
                spelling is enough.
            fallback: Seconds to use when the header is absent or unusable.

        Returns:
            Seconds to wait, never negative and never above
            ``RETRY_429_MAX_WAIT``.
        """
        raw = resp.headers.get("retry-after")
        if raw is None:
            return fallback
        raw = raw.strip()

        try:
            return min(max(float(raw), 0.0), RETRY_429_MAX_WAIT)
        except ValueError:
            pass

        try:
            when = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return fallback
        # A date without a zone is read as UTC rather than local time: the spec
        # requires GMT, and treating a malformed date as local would shift the
        # wait by the machine's offset.
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        remaining = (when - datetime.now(UTC)).total_seconds()
        return min(max(remaining, 0.0), RETRY_429_MAX_WAIT)

    @staticmethod
    def _retry_reason(body: str) -> str:
        """The upstream's own words for a refusal, unwrapped and shortened.

        A one-line notice has room for the reason and not for the envelope
        around it. Providers put the readable part inside JSON -- ``{"error":
        {"message": "Upstream request failed: Endpoint is unavailable."}}`` --
        so pull the message out when the body is shaped that way and fall back
        to the raw text when it is not.

        Paraphrasing would be worse than either: the reason is what tells a user
        whether to wait (an endpoint that is down) or stop (an account out of
        credit), and only the upstream knows which it is.

        Args:
            body: The response body as text, or an exception's text.

        Returns:
            A single line, at most 200 characters, or an empty string when there
            is nothing to say.
        """
        text = (body or "").strip()
        if not text:
            return ""
        try:
            data = json.loads(text)
        except ValueError:
            return text.splitlines()[0][:200]
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                return error["message"].splitlines()[0][:200]
            if isinstance(error, str):
                return error.splitlines()[0][:200]
            if isinstance(data.get("message"), str):
                return data["message"].splitlines()[0][:200]
        return text.splitlines()[0][:200]

    async def _post_with_retry(
        self,
        session: aiohttp.ClientSession,
        url: str,
        headers: dict,
        body: dict,
        abort_event: asyncio.Event | None,
        timeout: aiohttp.ClientTimeout | None = None,
    ) -> AsyncGenerator[RetryNotice | aiohttp.ClientResponse | None, None]:
        """POST the body, racing an abort and retrying per the transport policy.

        An async generator rather than a coroutine, so a retry can be reported
        *before* it is waited out. The notice is yielded first and the sleep runs
        only when the caller asks for the next item, so a client sees "retrying"
        while it is still waiting instead of after the fact -- the difference
        between a turn that looks hung and one that explains itself.

        Yields:
            One ``RetryNotice`` per retry, then exactly one final item: the
            response, or None when the abort fired. The caller loops until it
            sees the non-notice item, so a bare ``return`` here would strand it.

        Raises:
            RuntimeError: All retry attempts were exhausted without a response.
        """
        use_retry = self.transport_policy.use_retry
        # Two budgets, because a 429 and a 5xx are different questions: the
        # first is the endpoint asking to be come back to, the second a request
        # that could not be served. The loop runs long enough for whichever one
        # is being spent and each branch checks its own counter, so a 429 can
        # outlast the general budget without a 503 inheriting it.
        general_attempts = MAX_RETRIES if use_retry else 1
        rate_attempts = (
            RETRY_429_MAX_ATTEMPTS
            if use_retry and self.transport_policy.retry_429
            else 1
        )
        total_attempts = max(general_attempts, rate_attempts)

        delay = RETRY_BASE_DELAY
        rate_delay = RETRY_BASE_DELAY
        rate_waited = 0.0
        general_used = 0
        rate_used = 0

        for attempt in range(total_attempts):
            post_task = asyncio.create_task(
                session.post(
                    url,
                    timeout=timeout
                    if timeout is not None
                    else aiohttp.ClientTimeout(total=self.timeout_seconds),
                    **self._post_kwargs(headers, body),
                ),
                name=f"{self.trace_label}_post_attempt_{attempt}",
            )
            abort_task = (
                asyncio.create_task(abort_event.wait(), name="abort_watcher")
                if abort_event
                else None
            )
            wait_targets = [post_task] + ([abort_task] if abort_task else [])
            done, _ = await asyncio.wait(
                wait_targets, return_when=asyncio.FIRST_COMPLETED
            )

            if abort_task and abort_task in done:
                post_task.cancel()
                try:
                    await post_task
                except Exception:
                    pass
                yield None
                return

            if abort_task:
                abort_task.cancel()
                try:
                    await abort_task
                except (asyncio.CancelledError, Exception):
                    pass

            try:
                resp = post_task.result()
            except (TimeoutError, aiohttp.ClientConnectionError) as e:
                if general_used < general_attempts - 1:
                    general_used += 1
                    reason = str(e) or type(e).__name__
                    log.warning(
                        "Connection error (attempt %d/%d): %s, retrying in %.1fs",
                        general_used,
                        general_attempts,
                        e,
                        delay,
                    )
                    yield RetryNotice(
                        attempt=general_used,
                        total=general_attempts,
                        wait_seconds=delay,
                        reason=reason,
                    )
                    if await sleep_unless_aborted(delay, abort_event):
                        yield None
                        return
                    delay *= 2
                    continue
                log.error("Connection error after %d attempts: %s", general_attempts, e)
                raise
            except Exception as e:
                log.error("Unexpected error in post_task: %s", e)
                raise

            if (
                resp.status in RETRY_STATUS_CODES
                and general_used < general_attempts - 1
            ):
                general_used += 1
                wait = (
                    self._retry_after_seconds(resp, delay)
                    if self.transport_policy.honor_retry_after
                    else delay
                )
                reason = self._retry_reason(await resp.text())
                await resp.release()
                log.warning(
                    "Got %d (attempt %d/%d), retrying in %.1fs",
                    resp.status,
                    general_used,
                    general_attempts,
                    wait,
                )
                yield RetryNotice(
                    attempt=general_used,
                    total=general_attempts,
                    wait_seconds=wait,
                    reason=reason or f"HTTP {resp.status}",
                )
                if await sleep_unless_aborted(wait, abort_event):
                    yield None
                    return
                delay *= 2
                continue

            if resp.status == 429 and rate_used < rate_attempts - 1:
                # The text is read here and only here, and only for this
                # branch. aiohttp caches what ``text()`` returns, so the
                # caller's own ``await resp.text()`` on the non-retry path
                # produces exactly the error message it produced before this
                # existed -- which matters, because that message is the only
                # upstream detail the user ever sees.
                response_text = await resp.text()
                # 429 is "Too Many Requests". Only a body that names a spent
                # quota is worth refusing to wait out; every other 429 is a rate
                # limit or an endpoint asking to be come back to, and retrying
                # those is what the status code means.
                if not is_terminal_429(resp.status, response_text):
                    wait = self._retry_after_seconds(resp, rate_delay)
                    if rate_waited + wait > RETRY_429_TOTAL_BUDGET:
                        # The wall-clock budget is spent. Hand the response back
                        # rather than sleep past the ceiling that budget exists
                        # to set; the body is already cached, so the caller still
                        # builds its message from it.
                        yield resp
                        return
                    rate_used += 1
                    rate_waited += wait
                    await resp.release()
                    log.warning(
                        "Got 429 (attempt %d/%d), retrying in %.1fs",
                        rate_used,
                        rate_attempts,
                        wait,
                    )
                    yield RetryNotice(
                        attempt=rate_used,
                        total=rate_attempts,
                        wait_seconds=wait,
                        reason=self._retry_reason(response_text) or "HTTP 429",
                    )
                    if await sleep_unless_aborted(wait, abort_event):
                        yield None
                        return
                    rate_delay *= 2
                    continue

            yield resp
            return

        raise RuntimeError(f"Failed after {total_attempts} attempts")

    def _open_session(self) -> tuple[aiohttp.TCPConnector, aiohttp.ClientSession]:
        connector = self._make_connector()
        session = aiohttp.ClientSession(
            connector=connector, trust_env=self.transport_policy.trust_env
        )
        return connector, session

    def _stream_timeout(
        self, total_timeout_seconds: int | None
    ) -> aiohttp.ClientTimeout:
        """Build the streaming request's timeout.

        A stream is bounded by its socket-idle timeout (``sock_read``) plus the
        abort and runaway guards, not by a wall-clock deadline on the whole
        response: a reasoning model may legitimately think, or a long answer
        legitimately stream, for minutes, so capping the total would cut a
        healthy turn mid-flight. The overall deadline is therefore left unset;
        a caller that genuinely wants one passes ``total_timeout_seconds``.
        """
        return aiohttp.ClientTimeout(
            total=total_timeout_seconds,
            sock_connect=STREAM_IDLE_TIMEOUT_SECONDS,
            sock_read=STREAM_IDLE_TIMEOUT_SECONDS,
        )

    def _read_line_factory(
        self, resp: aiohttp.ClientResponse
    ) -> Callable[[], Coroutine[object, object, bytes]]:
        """Return the next-line reader for the response.

        A line limit reads with ``readline(max_line_length=...)``; None reads
        through the content iterator, which carries no explicit cap (OpenAI
        Chat today).
        """
        limit = self.stream_policy.line_limit
        if limit is None:
            iterator = resp.content.__aiter__()
            return iterator.__anext__
        return lambda: resp.content.readline(max_line_length=limit)

    # -- Templates -------------------------------------------------------

    async def chat(
        self,
        messages: list,
        model: str,
        stream: bool = False,
        tools: list[dict] | None = None,
        abort_event: asyncio.Event | None = None,
        session_id: str | None = None,
        reasoning_effort: str | None = None,
        **kwargs: object,
    ) -> Done:
        url, headers, body = self._prepare_request(
            messages, model, stream, tools, session_id, reasoning_effort
        )
        connector, session = self._open_session()
        try:
            resp = None
            # Retry notices are dropped here: this path has no channel to a
            # client, so there is nobody to tell. The loop still has to run to
            # completion or the response is never yielded.
            async for item in self._post_with_retry(
                session, url, headers, body, abort_event
            ):
                if not isinstance(item, RetryNotice):
                    resp = item
            if resp is None:
                return Done(content="", tool_calls=[], aborted=True)
            async with resp:
                if resp.status != 200:
                    text = await resp.text()
                    error_message = self._build_http_error_message(
                        url, resp.status, text
                    )
                    log.error("%s request failed: %s", self.trace_label, error_message)
                    return Error(message=error_message)
                if self.transport_policy.guard_non_json:
                    try:
                        data = await resp.json()
                    except Exception:
                        text = await resp.text()
                        log.error(
                            "%s response was not valid JSON (content-type=%s): %.200s",
                            self.trace_label,
                            resp.content_type,
                            text,
                        )
                        return Error(message="unexpected response from API")
                else:
                    data = await resp.json()
                return self._parse_response(data)
        except Exception as exc:
            log.exception("%s chat request raised an exception", self.trace_label)
            return Error(message=str(exc))
        finally:
            await session.close()
            if not connector.closed:
                await connector.close()

    async def chat_stream(
        self,
        messages: list,
        model: str,
        tools: list[dict] | None = None,
        abort_event: asyncio.Event | None = None,
        total_timeout_seconds: int | None = None,
        session_id: str | None = None,
        reasoning_effort: str | None = None,
        **kwargs: object,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        url, headers, body = self._prepare_request(
            messages, model, True, tools, session_id, reasoning_effort
        )
        connector, session = self._open_session()
        timeout = self._stream_timeout(total_timeout_seconds)
        # Bound before the request so a failure anywhere below can still hand
        # back whatever the turn had produced.
        accumulator = StreamAccumulator(
            model,
            self.stream_policy.max_content_chars,
            self.stream_policy.max_tool_arg_chars,
        )
        parser = self._new_parser(model)
        try:
            resp = None
            # Each RetryNotice is forwarded as it arrives, before the wait it
            # describes -- that ordering is the whole reason this is a generator
            # and not a coroutine.
            async for item in self._post_with_retry(
                session, url, headers, body, abort_event, timeout=timeout
            ):
                if isinstance(item, RetryNotice):
                    yield item
                else:
                    resp = item
            if resp is None:
                yield Done(content="", tool_calls=[], aborted=True)
                return
            async with resp:
                if resp.status != 200:
                    text = await resp.text()
                    error_message = self._build_http_error_message(
                        url, resp.status, text
                    )
                    log.error(
                        "%s stream request failed: %s", self.trace_label, error_message
                    )
                    yield Error(message=error_message)
                    return
                trace = StreamTrace(self.trace_label, model)
                trace.opened()
                async for out in drive_stream(
                    resp=resp,
                    read_line=self._read_line_factory(resp),
                    abort_event=abort_event,
                    trace=trace,
                    accumulator=accumulator,
                    parser=parser,
                    framer=self.framer,
                ):
                    yield out
        except asyncio.CancelledError:
            if self.stream_policy.swallow_cancel:
                content = (
                    accumulator.content
                    if self.stream_policy.cancel_keeps_content
                    else ""
                )
                yield Done(content=content, tool_calls=[], aborted=True)
                return
            raise
        except Exception as exc:
            log.exception("%s chat_stream raised an exception", self.trace_label)
            yield parser.on_exception(exc, accumulator)
        finally:
            await session.close()
            if not connector.closed:
                await connector.close()


__all__ = ["HttpProvider"]
