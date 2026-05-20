from __future__ import annotations

from enum import Enum, auto


class MessageState(Enum):
    STREAMING = auto()
    FINAL = auto()
    ERROR = auto()
