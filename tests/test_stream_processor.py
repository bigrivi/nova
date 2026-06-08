from nova.cli.stream_commands import (
    AppendReasoning,
    AppendText,
    EndReasoning,
    EndText,
    FailToolCall,
    FinalizeAssistant,
    FinishToolCall,
    HideCompactionSpinner,
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
from nova.cli.stream_processor import StreamEventProcessor


class _ToolResult:
    def __init__(self, content: object, requires_input: bool = False, success: bool = True) -> None:
        self.content = content
        self.requires_input = requires_input
        self.success = success


class _ToolCall:
    id = "call_1"
    name = "read"
    arguments = '{"filePath":"README.md"}'


def test_start_resets_state_and_returns_generating_command():
    processor = StreamEventProcessor()
    processor.mark_text_output_seen()
    processor.mark_tool_call_seen()

    processed = processor.handle_start()

    assert processed.commands == (SetGenerating(),)
    assert processor.text_output_seen is False
    assert processor.tool_calls_seen == 0


def test_turn_start_returns_thinking_spinner_command():
    processor = StreamEventProcessor()

    processed = processor.handle_turn_start()

    assert processed.commands == (ShowThinkingSpinner(),)


def test_compaction_start_returns_compaction_spinner_command():
    processor = StreamEventProcessor()

    processed = processor.handle_compaction_start()

    assert processed.commands == (ShowCompactionSpinner(),)


def test_compaction_end_returns_hide_spinner_command():
    processor = StreamEventProcessor()

    processed = processor.handle_compaction_end()

    assert processed.commands == (HideCompactionSpinner(),)


def test_noop_returns_no_commands():
    processor = StreamEventProcessor()

    processed = processor.handle_noop()

    assert processed.commands == ()
    assert processed.stop is False


def test_done_stopped_returns_cancelled_info_and_finalize():
    processor = StreamEventProcessor()

    processed = processor.handle_done({"reason": "stopped", "content": "Stopped by user"})

    assert processed.stop is True
    assert processed.commands == (FinalizeAssistant(), ShowInfo("User Cancelled."), SetIdle())


def test_done_tool_failed_returns_error():
    processor = StreamEventProcessor()

    processed = processor.handle_done({"reason": "tool_failed", "content": "tool failed"})

    assert processed.stop is True
    assert processed.commands == (ShowError("tool failed"), SetIdle())


def test_done_error_content_returns_error():
    processor = StreamEventProcessor()

    processed = processor.handle_done({"reason": "completed", "content": "Error: bad request"})

    assert processed.stop is True
    assert processed.commands == (ShowError("Error: bad request"), SetIdle())


def test_done_tool_only_content_returns_info_when_no_text_seen():
    processor = StreamEventProcessor()
    processor.mark_tool_call_seen()

    processed = processor.handle_done({"reason": "completed", "content": "tool summary"})

    assert processed.stop is True
    assert processed.commands == (ShowInfo("tool summary"), SetIdle())


def test_done_tool_content_is_silent_after_text_seen():
    processor = StreamEventProcessor()
    processor.mark_tool_call_seen()
    processor.mark_text_output_seen()

    processed = processor.handle_done({"reason": "completed", "content": "already streamed"})

    assert processed.stop is True
    assert processed.commands == (SetIdle(),)


def test_error_payload_returns_error():
    processor = StreamEventProcessor()

    processed = processor.handle_error({"reason": "llm_error", "message": "provider down"})

    assert processed.stop is True
    assert processed.commands == (ShowError("provider down"), SetIdle())


def test_text_start_returns_start_text_command():
    processor = StreamEventProcessor()

    processed = processor.handle_text_start()

    assert processed.commands == (StartText(),)
    assert processed.stop is False


def test_text_delta_returns_append_text_and_marks_text_seen():
    processor = StreamEventProcessor()

    processed = processor.handle_text_delta("hello")

    assert processed.commands == (AppendText("hello"),)
    assert processor.text_output_seen is True


def test_non_string_text_delta_is_noop():
    processor = StreamEventProcessor()

    processed = processor.handle_text_delta(None)

    assert processed.commands == ()
    assert processor.text_output_seen is False


def test_text_end_returns_end_text_command():
    processor = StreamEventProcessor()

    processed = processor.handle_text_end()

    assert processed.commands == (EndText(),)


def test_reasoning_start_returns_start_reasoning_command():
    processor = StreamEventProcessor()

    processed = processor.handle_reasoning_start()

    assert processed.commands == (StartReasoning(),)


def test_reasoning_delta_returns_append_reasoning_command():
    processor = StreamEventProcessor()

    processed = processor.handle_reasoning_delta("thinking")

    assert processed.commands == (AppendReasoning("thinking"),)


def test_non_string_reasoning_delta_is_noop():
    processor = StreamEventProcessor()

    processed = processor.handle_reasoning_delta(None)

    assert processed.commands == ()


def test_reasoning_end_returns_end_reasoning_command():
    processor = StreamEventProcessor()

    processed = processor.handle_reasoning_end()

    assert processed.commands == (EndReasoning(),)


def test_tool_result_requires_input_returns_pending_input_content():
    processor = StreamEventProcessor()

    processed = processor.handle_tool_result({"result": _ToolResult("choose one", requires_input=True)})

    assert processed.commands == (SetPendingInput("choose one"), FinishToolCall("", "choose one"))
    assert processed.stop is False


def test_tool_result_without_required_input_is_noop():
    processor = StreamEventProcessor()

    processed = processor.handle_tool_result({"result": _ToolResult("done")})

    assert processed.commands == (FinishToolCall("", "done"),)
    assert processed.stop is False


def test_tool_call_returns_show_tool_call_command():
    processor = StreamEventProcessor()

    processed = processor.handle_tool_call(_ToolCall())

    assert processed.commands == (
        FinalizeAssistant(),
        ShowToolCall("call_1", "read", {"filePath": "README.md"}),
    )
    assert processor.tool_calls_seen == 1


def test_failed_tool_result_returns_fail_tool_call_command():
    processor = StreamEventProcessor()

    processed = processor.handle_tool_result({
        "tool": "read",
        "tool_call_id": "call_1",
        "result": _ToolResult("bad", success=False),
    })

    assert processed.commands == (FailToolCall("call_1", "bad"),)


def test_successful_tool_result_returns_finish_tool_call_command():
    processor = StreamEventProcessor()

    processed = processor.handle_tool_result({
        "tool": "read",
        "tool_call_id": "call_1",
        "result": _ToolResult("ok"),
    })

    assert processed.commands == (
        FinishToolCall("call_1", "ok"),
    )
