from __future__ import annotations

from dataclasses import dataclass

from nova.cli.stream_commands import (
    AppendReasoning,
    AppendText,
    EndReasoning,
    EndText,
    FailToolCall,
    FinalizeAssistant,
    FinishToolCall,
    HideCompactionSpinner,
    RenderCommand,
    SetGenerating,
    SetIdle,
    SetPendingInput,
    ShowCompactionSpinner,
    ShowError,
    ShowInfo,
    ShowThinkingSpinner,
    ShowToolCall,
    StartReasoning,
    StartText,
)
from nova.cli.tool_rendering import parse_tool_arguments
from nova.cli.utils import (
    looks_like_error_message,
    parse_done_payload,
    parse_error_payload,
)


@dataclass(frozen=True)
class ProcessedStreamEvent:
    commands: tuple[RenderCommand, ...] = ()
    stop: bool = False


class StreamEventProcessor:
    def __init__(self) -> None:
        self.text_output_seen = False
        self.tool_calls_seen = 0

    def reset_run_state(self) -> None:
        self.text_output_seen = False
        self.tool_calls_seen = 0

    def mark_text_output_seen(self) -> None:
        self.text_output_seen = True

    def mark_tool_call_seen(self) -> None:
        self.tool_calls_seen += 1

    def handle_start(self, data: object = None) -> ProcessedStreamEvent:
        self.reset_run_state()
        return ProcessedStreamEvent(commands=(SetGenerating(),))

    def handle_turn_start(self, data: object = None) -> ProcessedStreamEvent:
        return ProcessedStreamEvent(commands=(ShowThinkingSpinner(),))

    def handle_compaction_start(self, data: object = None) -> ProcessedStreamEvent:
        return ProcessedStreamEvent(commands=(ShowCompactionSpinner(),))

    def handle_compaction_end(self, data: object = None) -> ProcessedStreamEvent:
        return ProcessedStreamEvent(commands=(HideCompactionSpinner(),))

    def handle_noop(self, data: object = None) -> ProcessedStreamEvent:
        return ProcessedStreamEvent()

    def handle_text_start(self, data: object = None) -> ProcessedStreamEvent:
        return ProcessedStreamEvent(commands=(StartText(),))

    def handle_text_delta(self, data: object) -> ProcessedStreamEvent:
        if not isinstance(data, str):
            return ProcessedStreamEvent()
        self.mark_text_output_seen()
        return ProcessedStreamEvent(commands=(AppendText(data),))

    def handle_text_end(self, data: object = None) -> ProcessedStreamEvent:
        return ProcessedStreamEvent(commands=(EndText(),))

    def handle_reasoning_start(self, data: object = None) -> ProcessedStreamEvent:
        return ProcessedStreamEvent(commands=(StartReasoning(),))

    def handle_reasoning_delta(self, data: object) -> ProcessedStreamEvent:
        if not isinstance(data, str):
            return ProcessedStreamEvent()
        return ProcessedStreamEvent(commands=(AppendReasoning(data),))

    def handle_reasoning_end(self, data: object = None) -> ProcessedStreamEvent:
        elapsed_ms = data if isinstance(data, int) else None
        return ProcessedStreamEvent(commands=(EndReasoning(elapsed_ms=elapsed_ms),))

    def handle_tool_call(self, data: object) -> ProcessedStreamEvent:
        self.mark_tool_call_seen()
        tool_name = getattr(data, "name", str(data))
        name = str(tool_name).strip().lower()
        call_id = getattr(data, "id", None) or str(self.tool_calls_seen)
        raw_args = getattr(data, "arguments", "")
        arguments = parse_tool_arguments(raw_args)

        return ProcessedStreamEvent(
            commands=(
                FinalizeAssistant(),
                ShowToolCall(str(call_id), name, arguments),
            ),
        )

    def handle_done(self, data: object) -> ProcessedStreamEvent:
        reason, done_content = parse_done_payload(data)

        if reason == "stopped" or done_content == "Stopped by user":
            return ProcessedStreamEvent(
                commands=(FinalizeAssistant(), ShowInfo("User Cancelled."), SetIdle()),
                stop=True,
            )

        if reason == "tool_failed":
            commands: tuple[RenderCommand, ...] = (SetIdle(),)
            if done_content:
                commands = (ShowError(done_content), *commands)
            return ProcessedStreamEvent(
                commands=commands,
                stop=True,
            )

        if looks_like_error_message(done_content):
            return ProcessedStreamEvent(
                commands=(ShowError(done_content), SetIdle()),
                stop=True,
            )

        if done_content and self.tool_calls_seen and not self.text_output_seen:
            return ProcessedStreamEvent(
                commands=(ShowInfo(done_content), SetIdle()),
                stop=True,
            )

        return ProcessedStreamEvent(commands=(SetIdle(),), stop=True)

    def handle_error(self, data: object) -> ProcessedStreamEvent:
        _, msg = parse_error_payload(data)
        commands: tuple[RenderCommand, ...] = (SetIdle(),)
        if msg:
            commands = (ShowError(msg), *commands)
        return ProcessedStreamEvent(commands=commands, stop=True)

    def handle_tool_result(self, data: object) -> ProcessedStreamEvent:
        if not isinstance(data, dict):
            return ProcessedStreamEvent()

        result = data.get("result")
        if result is None:
            return ProcessedStreamEvent()

        call_id = str(data.get("tool_call_id", "") or "")
        content = getattr(result, "content", "")
        content_str = content if isinstance(content, str) else ""

        commands: list[RenderCommand] = []
        if getattr(result, "requires_input", False):
            commands.append(SetPendingInput(content_str))

        if not getattr(result, "success", True) and content_str:
            commands.append(FailToolCall(call_id, content_str))
            return ProcessedStreamEvent(commands=tuple(commands))

        commands.append(FinishToolCall(call_id, content_str))
        return ProcessedStreamEvent(commands=tuple(commands))
