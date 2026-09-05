"""
Anthropic LLM Provider
"""

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

import aiohttp

from nova.llm.provider import ChatStreamEvent, LLMProvider, TextDelta, ReasoningDelta, ToolCall, Done, Error
from nova.llm.tokenizer import normalise_model_id

log = logging.getLogger(__name__)

_RETRY_STATUS_CODES = {429, 500, 502, 503, 504, 529}
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0
# Guard against a model that streams deltas forever without finish_reason
# (observed incident: Qwen3.8-27B-FP8 repetition loop grew RSS to 4-7 GB).
# Exceeding the ceiling aborts the stream with Error (not Done) so the
# agent does not ingest multi-megabyte garbage into message history.
_MAX_STREAM_CONTENT_CHARS = 2_000_000
_MAX_STREAM_TOOL_ARG_CHARS = 1_000_000
# Always bound stalled upstream reads; total is still caller-controlled
# (total=timeout when set, total=None otherwise) so long legitimate
# generations are not capped by an overall deadline.
_STREAM_SOCK_READ_TIMEOUT = 180
_MAX_TOOL_CALLS = 64

# Ordered longest-prefix-first so substring matching resolves correctly
# (claude-3-5-sonnet must not be caught by claude-3-sonnet).
_MODEL_MAX_OUTPUT_TOKENS = (
    ("claude-3-5-haiku", 8192),
    ("claude-3-5-sonnet", 8192),
    ("claude-3-7-sonnet", 64000),
    ("claude-3-opus", 4096),
    ("claude-3-sonnet", 4096),
    ("claude-3-haiku", 4096),
    ("claude-opus-4", 32000),
    ("claude-sonnet-4", 64000),
    ("claude-haiku-4", 64000),
)
_DEFAULT_MAX_OUTPUT_TOKENS = 8192


def _default_max_output_tokens(model: str) -> int:
    normalised = normalise_model_id(model)
    for model_prefix, max_output_tokens in _MODEL_MAX_OUTPUT_TOKENS:
        if model_prefix in normalised:
            return max_output_tokens
    return _DEFAULT_MAX_OUTPUT_TOKENS


def _tool_call_parts(tool_call: object) -> Optional[tuple[str, str, str]]:
    """Return (id, name, arguments) for either the OpenAI-nested or Nova-flat tool call shape."""
    if not isinstance(tool_call, dict):
        # ToolCall.model_dump() is what the agent persists into message history.
        model_dump = getattr(tool_call, "model_dump", None)
        if not callable(model_dump):
            return None
        try:
            tool_call = model_dump()
        except Exception:
            log.debug("Tool call model_dump() failed", exc_info=True)
            return None
        if not isinstance(tool_call, dict):
            return None

    function_payload = tool_call.get("function")
    if isinstance(function_payload, dict):
        tool_name = function_payload.get("name", "")
        arguments = function_payload.get("arguments", "")
    else:
        tool_name = tool_call.get("name", "")
        arguments = tool_call.get("arguments", "")

    tool_call_id = str(tool_call.get("id", "") or "")
    tool_name = str(tool_name or "")
    if not tool_call_id and not tool_name:
        return None
    # Nova persists arguments as a JSON string, but Ollama-shaped history keeps a dict.
    if isinstance(arguments, dict):
        arguments = json.dumps(arguments, ensure_ascii=False)
    return tool_call_id, tool_name, str(arguments or "")


def _content_block_index(event: dict) -> int:
    try:
        return int(event.get("index", 0))
    except Exception:
        return 0


def _state_to_tool_call(state: dict) -> ToolCall:
    arguments = state.get("arguments") or state.get("initial_input") or "{}"
    return ToolCall(id=str(state.get("id", "")), name=str(state.get("name", "")), arguments=str(arguments))


def _thinking_provider_meta(thinking_blocks: list[dict]) -> Optional[dict]:
    """Reduce a turn's thinking blocks to the state that cannot be reconstructed later.

    The thinking text is already persisted as the message's reasoning_content, so
    only the signature (which is a signature over that text) and the encrypted
    payload of redacted blocks need carrying. Returns None when there is nothing
    to persist, because the message store keeps NULL rather than an empty object.
    """
    signature: Optional[str] = None
    redacted_entries: list[str] = []
    for block in thinking_blocks:
        block_type = block.get("type")
        if block_type == "thinking":
            block_signature = block.get("signature")
            if signature is None and isinstance(block_signature, str) and block_signature:
                signature = block_signature
        elif block_type == "redacted_thinking" and block.get("data"):
            redacted_entries.append(str(block["data"]))

    if not signature and not redacted_entries:
        return None
    provider_meta: dict = {}
    if signature:
        provider_meta["thinking_signature"] = signature
    if redacted_entries:
        provider_meta["redacted_thinking"] = redacted_entries
    return provider_meta


class AnthropicProvider(LLMProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        request_options: Optional[dict] = None,
        timeout: int = 120,
        user_agent: Optional[str] = None,
        anthropic_version: str = "2023-06-01",
        betas: Optional[list[str]] = None,
        max_tokens: Optional[int] = None,
    ):
        self.api_key = api_key or ""
        self.base_url = (base_url or "").rstrip("/")
        self.request_options = dict(request_options or {})
        self.timeout = timeout
        self._user_agent = user_agent
        self._anthropic_version = anthropic_version
        self._betas = list(betas) if betas else None
        self._max_tokens_override = max_tokens

    def _endpoint(self) -> str:
        resolved_base_url = self.base_url or "https://api.anthropic.com"
        if resolved_base_url.endswith("/v1"):
            return f"{resolved_base_url}/messages"
        return f"{resolved_base_url}/v1/messages"

    def _make_connector(self) -> aiohttp.TCPConnector:
        return aiohttp.TCPConnector(
            limit=10,
            limit_per_host=5,
            ttl_dns_cache=300,
        )

    @staticmethod
    def _build_http_error_message(url: str, status: int, text: str) -> str:
        detail = (text or "").strip() or "<empty response>"
        return f"HTTP {status} from {url}: {detail}"

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": self._anthropic_version,
        }
        if self._user_agent:
            headers["User-Agent"] = self._user_agent
        if self.api_key:
            headers["x-api-key"] = self.api_key
        if self._betas:
            headers["anthropic-beta"] = ",".join(self._betas)
        return headers

    def _format_tools(self, tools: list[dict] | None) -> list[dict]:
        if not tools:
            return []
        anthropic_tools: list[dict] = []
        for tool_schema in tools:
            if not isinstance(tool_schema, dict):
                continue
            # Accept nested {"type":"function","function":{...}} and flat {...}
            function_payload = tool_schema.get("function") if isinstance(tool_schema.get("function"), dict) else tool_schema
            tool_name = function_payload.get("name", "") if isinstance(function_payload, dict) else ""
            if not tool_name:
                continue
            description = function_payload.get("description", "") if isinstance(function_payload, dict) else ""
            input_schema = None
            if isinstance(function_payload, dict):
                if "input_schema" in function_payload:
                    input_schema = function_payload["input_schema"]
                elif "parameters" in function_payload:
                    input_schema = function_payload["parameters"]
            if not isinstance(input_schema, dict):
                input_schema = {"type": "object", "properties": {}}
            anthropic_tools.append({
                "name": tool_name,
                "description": description,
                "input_schema": input_schema,
            })
        return anthropic_tools

    def _replay_thinking_blocks(self, get_attr, message: object, model: Optional[str]) -> list[dict]:
        message_model = get_attr(message, "model")
        if message_model and model and str(message_model) != str(model):
            log.debug("Skipping thinking replay: message model %s differs from request model %s",
                      message_model, model)
            return []

        provider_meta = get_attr(message, "provider_meta")
        if not isinstance(provider_meta, dict):
            return []

        blocks: list[dict] = []
        signature = provider_meta.get("thinking_signature")
        if isinstance(signature, str) and signature:
            # The signature is over the thinking text, which lives in reasoning_content.
            # An empty text is still a valid signed block, so the signature - not the
            # text - decides whether the block is sent.
            reasoning_content = get_attr(message, "reasoning_content")
            blocks.append({
                "type": "thinking",
                "thinking": reasoning_content or "",
                "signature": signature,
            })

        redacted_entries = provider_meta.get("redacted_thinking")
        if isinstance(redacted_entries, list):
            for redacted_entry in redacted_entries:
                if redacted_entry:
                    blocks.append({"type": "redacted_thinking", "data": str(redacted_entry)})
        return blocks

    def _format_messages(self, messages: list, include_thinking: bool = False, model: Optional[str] = None) -> tuple[list[dict], str]:
        def get_attr(message: object, key: str):
            if isinstance(message, dict):
                return message.get(key)
            return getattr(message, key, None)

        # Pre-pass: collect ids for pair integrity
        resolved_ids: set[str] = set()
        declared_ids: set[str] = set()
        for message in messages:
            role = get_attr(message, "role")
            if role == "tool":
                tool_use_id = get_attr(message, "tool_call_id")
                if tool_use_id:
                    resolved_ids.add(str(tool_use_id))
            elif role == "assistant":
                message_tool_calls = get_attr(message, "tool_calls")
                if isinstance(message_tool_calls, list):
                    for tool_call in message_tool_calls:
                        tool_call_fields = _tool_call_parts(tool_call)
                        if tool_call_fields and tool_call_fields[0]:
                            declared_ids.add(tool_call_fields[0])

        # Identify the last assistant message by position for thinking replay
        last_assistant_index: Optional[int] = None
        for message_index, message in enumerate(messages):
            if get_attr(message, "role") == "assistant":
                last_assistant_index = message_index

        system_parts: list[str] = []
        converted_messages: list[dict] = []

        for message_index, message in enumerate(messages):
            role = get_attr(message, "role")
            content = get_attr(message, "content")
            images = get_attr(message, "images")
            tool_calls = get_attr(message, "tool_calls")
            tool_call_id = get_attr(message, "tool_call_id")
            if role is None:
                continue

            if role == "system":
                text = content or ""
                if text:
                    system_parts.append(str(text))
                continue

            if role == "user":
                blocks: list[dict] = []
                if content:
                    blocks.append({"type": "text", "text": str(content)})
                if images:
                    for image_base64 in images:
                        blocks.append({
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": image_base64},
                        })
                if blocks:
                    converted_messages.append({"role": "user", "content": blocks})
                continue

            if role == "assistant":
                blocks = []
                # Anthropic only requires the latest assistant turn's thinking blocks,
                # and on models that retain earlier turns every extra one is billed as input.
                if include_thinking and message_index == last_assistant_index:
                    blocks.extend(self._replay_thinking_blocks(get_attr, message, model))

                if content:
                    blocks.append({"type": "text", "text": str(content)})

                if isinstance(tool_calls, list):
                    for tool_call in tool_calls:
                        tool_call_fields = _tool_call_parts(tool_call)
                        if tool_call_fields is None:
                            continue
                        tool_use_id, tool_name, tool_arguments = tool_call_fields
                        if not tool_name:
                            continue
                        if tool_use_id not in resolved_ids:
                            log.debug("Dropping tool_use %s not in resolved_ids", tool_use_id)
                            continue
                        # tool_use.input must be an object; Nova carries arguments as a JSON string
                        tool_input: dict = {}
                        if tool_arguments:
                            try:
                                parsed = json.loads(tool_arguments)
                            except json.JSONDecodeError:
                                log.warning("Tool %s arguments is not valid JSON, using {}", tool_name)
                            else:
                                if isinstance(parsed, dict):
                                    tool_input = parsed
                                else:
                                    log.warning("Tool %s arguments is not an object, using {}", tool_name)
                        blocks.append({
                            "type": "tool_use",
                            "id": str(tool_use_id),
                            "name": str(tool_name),
                            "input": tool_input,
                        })
                if blocks:
                    converted_messages.append({"role": "assistant", "content": blocks})
                continue

            if role == "tool":
                tool_use_id = str(tool_call_id) if tool_call_id else ""
                if not tool_use_id:
                    continue
                if tool_use_id not in declared_ids:
                    log.debug("Dropping tool_result %s not in declared_ids", tool_use_id)
                    continue
                tool_result_content: list[dict] = []
                text = content if content else "(no output)"
                tool_result_content.append({"type": "text", "text": str(text)})
                if images:
                    for image_base64 in images:
                        tool_result_content.append({
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": image_base64},
                        })
                converted_messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": tool_result_content}],
                })
                continue

            # Unknown role: treat as user text
            blocks = []
            if content:
                blocks.append({"type": "text", "text": str(content)})
            if blocks:
                converted_messages.append({"role": "user", "content": blocks})

        # Anthropic requires the first message to have role user, but Nova's
        # Layer-2 compaction writes its summary as an assistant message so
        # after compaction the history starts with assistant. Convert that
        # leading assistant into a user message instead of dropping it.
        dropped_tool_use_ids: set[str] = set()
        while converted_messages and converted_messages[0]["role"] == "assistant":
            leading_message = converted_messages[0]
            content_blocks = leading_message.get("content", [])
            content_blocks = [
                block for block in content_blocks
                if block.get("type") not in ("thinking", "redacted_thinking")
            ]
            leading_message["content"] = content_blocks
            if not content_blocks:
                converted_messages.pop(0)
                continue
            has_tool_use = any(block.get("type") == "tool_use" for block in content_blocks)
            if has_tool_use:
                for block in content_blocks:
                    if block.get("type") == "tool_use" and block.get("id"):
                        dropped_tool_use_ids.add(str(block["id"]))
                converted_messages.pop(0)
                continue
            leading_message["role"] = "user"
            break

        if dropped_tool_use_ids:
            for converted in converted_messages:
                content_blocks = converted.get("content", [])
                filtered_blocks = [
                    block for block in content_blocks
                    if not (block.get("type") == "tool_result" and str(block.get("tool_use_id", "")) in dropped_tool_use_ids)
                ]
                converted["content"] = filtered_blocks
            converted_messages = [converted for converted in converted_messages if converted["content"]]

        # Merge consecutive same-role messages by concatenating block lists.
        # Mandatory: Anthropic requires strictly alternating user/assistant roles.
        merged_messages: list[dict] = []
        for converted in converted_messages:
            if merged_messages and merged_messages[-1]["role"] == converted["role"]:
                merged_messages[-1]["content"].extend(converted["content"])
            else:
                merged_messages.append({"role": converted["role"], "content": list(converted["content"])})

        # Anthropic requires tool_result blocks at the beginning of a user message
        for converted in merged_messages:
            if converted["role"] == "user":
                leading_tool_results = [block for block in converted["content"] if block.get("type") == "tool_result"]
                trailing_blocks = [block for block in converted["content"] if block.get("type") != "tool_result"]
                if leading_tool_results and trailing_blocks:
                    converted["content"] = leading_tool_results + trailing_blocks

        # Drop messages whose block list ended up empty
        merged_messages = [converted for converted in merged_messages if converted["content"]]

        # On the final message, if it is assistant, right-strip trailing whitespace
        if merged_messages and merged_messages[-1]["role"] == "assistant":
            content_blocks = merged_messages[-1]["content"]
            # Find last text block
            for block_position in range(len(content_blocks) - 1, -1, -1):
                block = content_blocks[block_position]
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    stripped = block["text"].rstrip()
                    if stripped:
                        block["text"] = stripped
                    else:
                        content_blocks.pop(block_position)
                    break

        system_text = "\n\n".join(system_parts)
        return merged_messages, system_text

    def _build_body(self, messages: list, model: str, stream: bool = False, tools: list[dict] | None = None) -> dict:
        options = dict(self.request_options)
        tools_enabled = options.pop("tools", True)
        max_tokens_from_options = options.pop("max_tokens", None)
        # System in options is handled after formatting: message-derived wins when non-empty
        system_from_options = options.pop("system", None)

        # Thinking flag determines whether to replay persisted thinking blocks
        include_thinking = "thinking" in options

        formatted_messages, system_text = self._format_messages(messages, include_thinking=include_thinking, model=model)

        # Resolve max_tokens: request_options -> override -> default table
        if max_tokens_from_options is not None:
            try:
                resolved_max_tokens = int(max_tokens_from_options)
            except Exception:
                resolved_max_tokens = _default_max_output_tokens(model)
        elif self._max_tokens_override is not None:
            resolved_max_tokens = int(self._max_tokens_override)
        else:
            resolved_max_tokens = _default_max_output_tokens(model)

        body: dict = {}
        if model:
            body["model"] = model
        body["max_tokens"] = resolved_max_tokens
        body["messages"] = formatted_messages

        # System: message-derived wins when non-empty
        if system_text:
            body["system"] = system_text
        elif isinstance(system_from_options, str) and system_from_options:
            body["system"] = system_from_options
        elif isinstance(system_from_options, list) and system_from_options:
            body["system"] = system_from_options

        if stream:
            body["stream"] = True

        # Flatten remaining options (including thinking, etc.)
        body.update(options)

        if tools_enabled:
            formatted_tools = self._format_tools(tools)
            # Anthropic rejects "tools": [], so omit the key entirely rather than sending an empty list
            if formatted_tools:
                body["tools"] = formatted_tools
        # when tools_enabled is falsy, send NO tools at all

        return body

    async def _post_with_retry(
        self,
        session: aiohttp.ClientSession,
        url: str,
        headers: dict,
        body: dict,
        abort_event: Optional[asyncio.Event],
        timeout: Optional[aiohttp.ClientTimeout] = None,
    ) -> Optional[aiohttp.ClientResponse]:
        delay = _RETRY_BASE_DELAY
        for attempt in range(_MAX_RETRIES):
            post_task = asyncio.create_task(
                session.post(
                    url,
                    headers=headers,
                    json=body,
                    timeout=timeout if timeout is not None else aiohttp.ClientTimeout(total=self.timeout),
                ),
                name=f"anthropic_post_attempt_{attempt}",
            )
            abort_task = (
                asyncio.create_task(abort_event.wait(), name="abort_watcher") if abort_event else None
            )
            wait_targets = [post_task] + ([abort_task] if abort_task else [])
            completed, _ = await asyncio.wait(wait_targets, return_when=asyncio.FIRST_COMPLETED)

            if abort_task and abort_task in completed:
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
                response = post_task.result()
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as exception:
                if attempt < _MAX_RETRIES - 1:
                    log.warning("Connection error (attempt %d/%d): %s, retrying in %.1fs", attempt + 1, _MAX_RETRIES, exception, delay)
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                log.error("Connection error after %d attempts: %s", _MAX_RETRIES, exception)
                raise
            except Exception as exception:
                log.error("Unexpected error in post_task: %s", exception)
                raise

            if response.status in _RETRY_STATUS_CODES and attempt < _MAX_RETRIES - 1:
                retry_after = response.headers.get("retry-after") or response.headers.get("Retry-After")
                if retry_after is not None:
                    try:
                        retry_delay = float(retry_after)
                        retry_delay = min(max(retry_delay, 0), 60)
                        await response.release()
                        log.warning("Got %d (attempt %d/%d), retrying in %.1fs (retry-after)", response.status, attempt + 1, _MAX_RETRIES, retry_delay)
                        await asyncio.sleep(retry_delay)
                        delay *= 2
                        continue
                    except Exception:
                        pass
                await response.release()
                log.warning("Got %d (attempt %d/%d), retrying in %.1fs", response.status, attempt + 1, _MAX_RETRIES, delay)
                await asyncio.sleep(delay)
                delay *= 2
                continue

            return response

        raise RuntimeError(f"Failed after {_MAX_RETRIES} attempts")

    async def chat(
        self,
        messages: list,
        model: str,
        stream: bool = False,
        tools: list[dict] = None,
        abort_event: Optional[asyncio.Event] = None,
        **kwargs,
    ) -> Done:
        headers = self._build_headers()
        body = self._build_body(messages=messages, model=model, stream=stream, tools=tools)
        url = self._endpoint()
        connector = self._make_connector()
        session = aiohttp.ClientSession(connector=connector, trust_env=True)
        try:
            response = await self._post_with_retry(session=session, url=url, headers=headers, body=body, abort_event=abort_event)
            if response is None:
                return Done(content="", tool_calls=[], aborted=True)
            async with response:
                if response.status != 200:
                    text = await response.text()
                    error_message = self._build_http_error_message(url=url, status=response.status, text=text)
                    log.error("Anthropic provider request failed: %s", error_message)
                    return Error(message=error_message)
                try:
                    data = await response.json()
                except Exception:
                    text = await response.text()
                    log.error("Anthropic provider response was not valid JSON (content-type=%s): %.200s", response.content_type, text)
                    return Error(message="unexpected response from API")

                content_blocks = data.get("content", [])
                text_parts: list[str] = []
                tool_calls: list[ToolCall] = []
                thinking_blocks: list[dict] = []
                if isinstance(content_blocks, list):
                    for block in content_blocks:
                        if not isinstance(block, dict):
                            continue
                        block_type = block.get("type")
                        if block_type == "text":
                            text_parts.append(block.get("text", ""))
                        elif block_type == "thinking":
                            thinking_blocks.append({"type": "thinking", "thinking": block.get("thinking", ""), "signature": block.get("signature", "")})
                        elif block_type == "redacted_thinking":
                            thinking_blocks.append({"type": "redacted_thinking", "data": block.get("data", "")})
                        elif block_type == "tool_use":
                            tool_use_id = block.get("id", "")
                            tool_name = block.get("name", "")
                            tool_input = block.get("input", {})
                            if not isinstance(tool_input, dict):
                                tool_input = {}
                            tool_calls.append(ToolCall(id=str(tool_use_id), name=str(tool_name), arguments=json.dumps(tool_input, ensure_ascii=False)))

                provider_meta = _thinking_provider_meta(thinking_blocks)

                usage = data.get("usage") if isinstance(data, dict) else None
                tokens_input: Optional[int] = None
                tokens_output: Optional[int] = None
                if isinstance(usage, dict):
                    # tokens_input is sum of the three input fields (true prompt cost)
                    prompt_tokens = int(usage.get("input_tokens", 0) or 0)
                    cache_read_tokens = int(usage.get("cache_read_input_tokens", 0) or 0)
                    cache_creation_tokens = int(usage.get("cache_creation_input_tokens", 0) or 0)
                    tokens_input = prompt_tokens + cache_read_tokens + cache_creation_tokens
                    if usage.get("output_tokens") is not None:
                        tokens_output = int(usage["output_tokens"])

                return Done(
                    content="".join(text_parts),
                    tool_calls=tool_calls,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    provider_meta=provider_meta,
                )
        except Exception as exception:
            log.exception("Anthropic provider chat request raised an exception")
            return Error(message=str(exception))
        finally:
            await session.close()
            if not connector.closed:
                await connector.close()

    async def chat_stream(
        self,
        messages: list,
        model: str,
        tools: list[dict] = None,
        abort_event: Optional[asyncio.Event] = None,
        timeout: Optional[int] = None,
        **kwargs,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        headers = self._build_headers()
        headers["Accept"] = "text/event-stream"
        body = self._build_body(messages=messages, model=model, stream=True, tools=tools)
        url = self._endpoint()
        connector = self._make_connector()
        session = aiohttp.ClientSession(connector=connector, trust_env=True)
        effective_timeout = aiohttp.ClientTimeout(total=timeout, sock_read=_STREAM_SOCK_READ_TIMEOUT) if timeout is not None else aiohttp.ClientTimeout(total=None, sock_read=_STREAM_SOCK_READ_TIMEOUT)
        try:
            response = await self._post_with_retry(session=session, url=url, headers=headers, body=body, abort_event=abort_event, timeout=effective_timeout)
            if response is None:
                yield Done(content="", tool_calls=[], aborted=True)
                return
            async with response:
                if response.status != 200:
                    text = await response.text()
                    error_message = self._build_http_error_message(url=url, status=response.status, text=text)
                    log.error("Anthropic provider stream request failed: %s", error_message)
                    yield Error(message=error_message)
                    return

                accumulated_content = ""
                accumulated_tool_calls: dict[int, dict] = {}
                thinking_state: dict[int, dict] = {}
                final_thinking_blocks: list[dict] = []
                tokens_input: Optional[int] = None
                tokens_output: Optional[int] = None

                stream_lines = response.content.__aiter__()
                while True:
                    if abort_event and abort_event.is_set():
                        response.close()
                        yield Done(content=accumulated_content, tool_calls=[], aborted=True)
                        return
                    try:
                        line = await asyncio.wait_for(stream_lines.__anext__(), timeout=0.5)
                    except asyncio.TimeoutError:
                        continue
                    except StopAsyncIteration:
                        break

                    line = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else str(line)
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("event:"):
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if not line or line == "[DONE]":
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        log.debug("Anthropic provider received non-JSON stream chunk", exc_info=True)
                        continue

                    event_type = data.get("type", "")

                    if event_type == "message_start":
                        start_message = data.get("message", {})
                        usage = start_message.get("usage", {}) if isinstance(start_message, dict) else {}
                        if isinstance(usage, dict):
                            prompt_tokens = int(usage.get("input_tokens", 0) or 0)
                            cache_read_tokens = int(usage.get("cache_read_input_tokens", 0) or 0)
                            cache_creation_tokens = int(usage.get("cache_creation_input_tokens", 0) or 0)
                            tokens_input = prompt_tokens + cache_read_tokens + cache_creation_tokens
                            if usage.get("output_tokens") is not None:
                                try:
                                    tokens_output = int(usage["output_tokens"])
                                except Exception:
                                    pass
                        continue

                    if event_type == "content_block_start":
                        block_index = _content_block_index(data)
                        content_block = data.get("content_block", {})
                        if not isinstance(content_block, dict):
                            continue
                        content_block_type = content_block.get("type")
                        if content_block_type == "text":
                            text = content_block.get("text", "")
                            if text:
                                if len(accumulated_content) + len(text) > _MAX_STREAM_CONTENT_CHARS:
                                    log.error("Anthropic stream runaway content: model=%s size=%s exceeds %s", model, len(accumulated_content) + len(text), _MAX_STREAM_CONTENT_CHARS)
                                    response.close()
                                    yield Error(message=f"model {model} produced runaway/unbounded output (>{_MAX_STREAM_CONTENT_CHARS} chars), stream aborted")
                                    return
                                accumulated_content += text
                                yield TextDelta(content=text)
                        elif content_block_type == "thinking":
                            thinking_state[block_index] = {"thinking": content_block.get("thinking", "") or "", "signature": content_block.get("signature", "") or "", "type": "thinking"}
                        elif content_block_type == "redacted_thinking":
                            thinking_state[block_index] = {"type": "redacted_thinking", "data": content_block.get("data", "") or ""}
                        elif content_block_type == "tool_use":
                            if len(accumulated_tool_calls) >= _MAX_TOOL_CALLS and block_index not in accumulated_tool_calls:
                                continue
                            accumulated_tool_calls[block_index] = {
                                "id": content_block.get("id", f"call_{block_index}"),
                                "name": content_block.get("name", ""),
                                "arguments": "",
                                "yielded": False,
                            }
                            initial_tool_input = content_block.get("input")
                            if isinstance(initial_tool_input, dict) and initial_tool_input:
                                try:
                                    initial_input_json = json.dumps(initial_tool_input, ensure_ascii=False)
                                    if initial_input_json != "{}":
                                        accumulated_tool_calls[block_index]["initial_input"] = initial_input_json
                                except Exception:
                                    pass
                        continue

                    if event_type == "content_block_delta":
                        block_index = _content_block_index(data)
                        delta = data.get("delta", {})
                        if not isinstance(delta, dict):
                            continue
                        delta_type = delta.get("type")
                        if delta_type == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                if len(accumulated_content) + len(text) > _MAX_STREAM_CONTENT_CHARS:
                                    log.error("Anthropic stream runaway content: model=%s size=%s exceeds %s", model, len(accumulated_content) + len(text), _MAX_STREAM_CONTENT_CHARS)
                                    response.close()
                                    yield Error(message=f"model {model} produced runaway/unbounded output (>{_MAX_STREAM_CONTENT_CHARS} chars), stream aborted")
                                    return
                                accumulated_content += text
                                yield TextDelta(content=text)
                        elif delta_type == "thinking_delta":
                            thinking_text = delta.get("thinking", "")
                            if thinking_text:
                                if block_index not in thinking_state:
                                    thinking_state[block_index] = {"thinking": "", "signature": "", "type": "thinking"}
                                thinking_state[block_index]["thinking"] = thinking_state[block_index].get("thinking", "") + thinking_text
                                yield ReasoningDelta(content=thinking_text)
                        elif delta_type == "signature_delta":
                            signature_chunk = delta.get("signature", "")
                            if signature_chunk:
                                if block_index not in thinking_state:
                                    thinking_state[block_index] = {"thinking": "", "signature": "", "type": "thinking"}
                                thinking_state[block_index]["signature"] = thinking_state[block_index].get("signature", "") + signature_chunk
                        elif delta_type == "input_json_delta":
                            partial_json = delta.get("partial_json", "")
                            if partial_json:
                                if block_index not in accumulated_tool_calls:
                                    if len(accumulated_tool_calls) >= _MAX_TOOL_CALLS:
                                        continue
                                    accumulated_tool_calls[block_index] = {"id": f"call_{block_index}", "name": "", "arguments": "", "yielded": False}
                                accumulated_tool_calls[block_index]["arguments"] += partial_json
                                if len(str(accumulated_tool_calls[block_index]["arguments"])) > _MAX_STREAM_TOOL_ARG_CHARS:
                                    log.error("Anthropic stream runaway tool args: model=%s size=%s exceeds %s", model, len(str(accumulated_tool_calls[block_index]["arguments"])), _MAX_STREAM_TOOL_ARG_CHARS)
                                    response.close()
                                    yield Error(message=f"model {model} produced runaway/unbounded tool arguments output (>{_MAX_STREAM_TOOL_ARG_CHARS} chars), stream aborted")
                                    return
                        continue

                    if event_type == "content_block_stop":
                        block_index = _content_block_index(data)
                        tool_call_state = accumulated_tool_calls.get(block_index)
                        if tool_call_state is not None and tool_call_state.get("name") and not tool_call_state.get("yielded"):
                            tool_call_state["yielded"] = True
                            yield _state_to_tool_call(tool_call_state)
                        thinking_block = thinking_state.get(block_index)
                        if thinking_block is not None:
                            if thinking_block.get("type") == "thinking":
                                final_thinking_blocks.append({"type": "thinking", "thinking": thinking_block.get("thinking", ""), "signature": thinking_block.get("signature", "")})
                            elif thinking_block.get("type") == "redacted_thinking":
                                final_thinking_blocks.append({"type": "redacted_thinking", "data": thinking_block.get("data", "")})
                        continue

                    if event_type == "message_delta":
                        usage = data.get("usage", {}) if isinstance(data.get("usage"), dict) else {}
                        if isinstance(usage, dict) and usage.get("output_tokens") is not None:
                            try:
                                tokens_output = int(usage["output_tokens"])
                            except Exception:
                                pass
                        continue

                    if event_type == "message_stop":
                        break

                    if event_type == "error":
                        error_payload = data.get("error", {}) if isinstance(data.get("error"), dict) else {}
                        error_type = error_payload.get("type", "error") if isinstance(error_payload, dict) else "error"
                        error_text = error_payload.get("message", "") if isinstance(error_payload, dict) else ""
                        error_detail = f"{error_type}: {error_text}" if error_text else str(error_type)
                        log.error("Anthropic stream error event: %s", error_detail)
                        yield Error(message=error_detail)
                        return

                    if event_type == "ping":
                        continue
                    # unknown -> ignore
                    continue

                provider_meta = _thinking_provider_meta(final_thinking_blocks)

                final_tool_calls = [
                    _state_to_tool_call(tool_call_state)
                    for _index, tool_call_state in sorted(accumulated_tool_calls.items())
                    if tool_call_state.get("name")
                ]
                yield Done(content=accumulated_content, tool_calls=final_tool_calls, tokens_input=tokens_input, tokens_output=tokens_output, provider_meta=provider_meta)

        except asyncio.CancelledError:
            yield Done(content="", tool_calls=[], aborted=True)
            return
        except Exception as exception:
            log.exception("Anthropic provider chat_stream raised an exception")
            yield Error(message=str(exception))
        finally:
            await session.close()
            if not connector.closed:
                await connector.close()

    async def count_tokens(self, text: str, model: str = None) -> int:
        chinese_chars = sum(1 for character in text if '\u4e00' <= character <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 2 + other_chars / 4)

    def get_max_tokens(self, model: str) -> int:
        model_id = (model or "").strip().lower()
        if "[1m]" in model_id or model_id.endswith("-1m"):
            return 1000000
        return 200000
