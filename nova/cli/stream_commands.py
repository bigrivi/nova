from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True)
class ShowInfo:
    message: str


@dataclass(frozen=True)
class ShowError:
    message: str


@dataclass(frozen=True)
class SetIdle:
    pass


@dataclass(frozen=True)
class SetGenerating:
    pass


@dataclass(frozen=True)
class ShowThinkingSpinner:
    pass


@dataclass(frozen=True)
class ShowCompactionSpinner:
    pass


@dataclass(frozen=True)
class HideCompactionSpinner:
    pass


@dataclass(frozen=True)
class FinalizeAssistant:
    pass


@dataclass(frozen=True)
class StartText:
    pass


@dataclass(frozen=True)
class AppendText:
    chunk: str


@dataclass(frozen=True)
class EndText:
    pass


@dataclass(frozen=True)
class StartReasoning:
    pass


@dataclass(frozen=True)
class AppendReasoning:
    chunk: str


@dataclass(frozen=True)
class EndReasoning:
    pass


@dataclass(frozen=True)
class SetPendingInput:
    content: str


@dataclass(frozen=True)
class ShowToolCall:
    call_id: str
    tool_name: str
    description: str
    params: list[tuple[str, str]]


@dataclass(frozen=True)
class FinishToolCall:
    call_id: str
    tool_name: str
    content: str
    rendered: str


@dataclass(frozen=True)
class FailToolCall:
    call_id: str
    message: str


RenderCommand: TypeAlias = (
    ShowInfo
    | ShowError
    | SetIdle
    | SetGenerating
    | ShowThinkingSpinner
    | ShowCompactionSpinner
    | HideCompactionSpinner
    | FinalizeAssistant
    | StartText
    | AppendText
    | EndText
    | StartReasoning
    | AppendReasoning
    | EndReasoning
    | SetPendingInput
    | ShowToolCall
    | FinishToolCall
    | FailToolCall
)
