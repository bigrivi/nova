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
import logging
from abc import abstractmethod
from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Optional

import aiohttp

from nova.llm.accumulator import StreamAccumulator
from nova.llm.framing import SSEFramer
from nova.llm.policy import StreamPolicy, TransportPolicy
from nova.llm.provider import (
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    RETRY_STATUS_CODES,
    STREAM_IDLE_TIMEOUT_SECONDS,
    ChatStreamEvent,
    Done,
    Error,
    LLMProvider,
)
from nova.llm.stream_driver import StreamParser, drive_stream
from nova.llm.stream_trace import StreamTrace

log = logging.getLogger(__name__)


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

    framer: object = SSEFramer()
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
        tools: Optional[list[dict]],
        session_id: Optional[str],
        reasoning_effort: Optional[str],
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
        # Ollama sends no headers and its transport never received a ``headers``
        # kwarg; omit it entirely when empty so that stays true.
        kwargs: dict = {"json": body}
        if headers:
            kwargs["headers"] = headers
        return kwargs

    async def _post_with_retry(
        self,
        session: aiohttp.ClientSession,
        url: str,
        headers: dict,
        body: dict,
        abort_event: Optional[asyncio.Event],
        timeout: Optional[aiohttp.ClientTimeout] = None,
    ) -> Optional[aiohttp.ClientResponse]:
        """POST the body, racing an abort and retrying per the transport policy.

        Returns:
            The response, or None when the abort fired before it arrived.

        Raises:
            RuntimeError: All retry attempts were exhausted without a response.
        """
        delay = RETRY_BASE_DELAY
        attempts = MAX_RETRIES if self.transport_policy.use_retry else 1
        for attempt in range(attempts):
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
                return None

            if abort_task:
                abort_task.cancel()
                try:
                    await abort_task
                except (asyncio.CancelledError, Exception):
                    pass

            try:
                resp = post_task.result()
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
                if self.transport_policy.use_retry and attempt < attempts - 1:
                    log.warning(
                        "Connection error (attempt %d/%d): %s, retrying in %.1fs",
                        attempt + 1,
                        attempts,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                log.error("Connection error after %d attempts: %s", attempts, e)
                raise
            except Exception as e:
                log.error("Unexpected error in post_task: %s", e)
                raise

            if (
                self.transport_policy.use_retry
                and resp.status in RETRY_STATUS_CODES
                and attempt < attempts - 1
            ):
                if self.transport_policy.honor_retry_after:
                    retry_after = resp.headers.get("retry-after") or resp.headers.get(
                        "Retry-After"
                    )
                    if retry_after is not None:
                        try:
                            retry_delay = min(max(float(retry_after), 0), 60)
                            await resp.release()
                            log.warning(
                                "Got %d (attempt %d/%d), retrying in %.1fs (retry-after)",
                                resp.status,
                                attempt + 1,
                                attempts,
                                retry_delay,
                            )
                            await asyncio.sleep(retry_delay)
                            delay *= 2
                            continue
                        except Exception:
                            pass
                await resp.release()
                log.warning(
                    "Got %d (attempt %d/%d), retrying in %.1fs",
                    resp.status,
                    attempt + 1,
                    attempts,
                    delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
                continue

            return resp

        raise RuntimeError(f"Failed after {MAX_RETRIES} attempts")

    def _open_session(self) -> tuple[aiohttp.TCPConnector, aiohttp.ClientSession]:
        connector = self._make_connector()
        session = aiohttp.ClientSession(
            connector=connector, trust_env=self.transport_policy.trust_env
        )
        return connector, session

    def _stream_timeout(
        self, total_timeout_seconds: Optional[int]
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
        tools: Optional[list[dict]] = None,
        abort_event: Optional[asyncio.Event] = None,
        session_id: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        **kwargs,
    ) -> Done:
        url, headers, body = self._prepare_request(
            messages, model, stream, tools, session_id, reasoning_effort
        )
        connector, session = self._open_session()
        try:
            resp = await self._post_with_retry(
                session, url, headers, body, abort_event
            )
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
        tools: Optional[list[dict]] = None,
        abort_event: Optional[asyncio.Event] = None,
        total_timeout_seconds: Optional[int] = None,
        session_id: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        **kwargs,
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
            resp = await self._post_with_retry(
                session, url, headers, body, abort_event, timeout=timeout
            )
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
