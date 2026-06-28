from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GuardrailAction(Enum):
    ALLOW = "allow"
    WARN = "warn"
    HALT = "halt"


@dataclass
class GuardrailObservation:
    tool_name: str
    args_hash: str
    success: bool


@dataclass
class ToolGuardrails:
    max_same_call: int = 5
    max_same_failure: int = 3
    max_no_write_reads: int = 10

    _calls: list[GuardrailObservation] = field(default_factory=list)
    _consecutive_failures: dict[str, int] = field(default_factory=dict)

    _READ_TOOLS = frozenset({
        "read", "grep", "glob", "web_search", "web_fetch",
        "list_skills", "search_memory", "list_memories", "get_state",
    })

    _last_write_index: int = 0

    @staticmethod
    def _hash_args(args: dict[str, Any]) -> str:
        raw = json.dumps(args, sort_keys=True, default=str)
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    def observe(self, tool_name: str, args: dict[str, Any], success: bool) -> GuardrailAction:
        args_hash = self._hash_args(args)
        obs = GuardrailObservation(
            tool_name=tool_name,
            args_hash=args_hash,
            success=success,
        )
        self._calls.append(obs)

        if tool_name not in self._READ_TOOLS:
            self._last_write_index = len(self._calls)

        consecutive_same = 0
        for prev in reversed(self._calls[:-1]):
            if prev.tool_name == tool_name and prev.args_hash == args_hash:
                consecutive_same += 1
            else:
                break

        if consecutive_same >= self.max_same_call:
            return GuardrailAction.HALT

        if not success:
            key = f"{tool_name}:{args_hash}"
            self._consecutive_failures[key] = self._consecutive_failures.get(key, 0) + 1
            if self._consecutive_failures[key] >= self.max_same_failure:
                return GuardrailAction.HALT
        else:
            key = f"{tool_name}:{args_hash}"
            self._consecutive_failures.pop(key, None)

        if tool_name in self._READ_TOOLS:
            recent_no_write = len(self._calls) - self._last_write_index
            if recent_no_write > self.max_no_write_reads:
                return GuardrailAction.WARN

        return GuardrailAction.ALLOW

    def reset(self) -> None:
        self._calls.clear()
        self._consecutive_failures.clear()
        self._last_write_index = 0
