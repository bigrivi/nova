from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass(frozen=True)
class CommandSpec:
    id: str
    label: str
    description: str
    aliases: tuple[str, ...] = ()
    usage: str | None = None


@dataclass(frozen=True)
class ParsedCommand:
    spec: CommandSpec
    name: str
    args: str = ""
    raw_input: str = ""


CommandHandler = Callable[[ParsedCommand], Awaitable[bool]]


DEFAULT_COMMAND_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec(
        id="new",
        label="New Session",
        description="Start a new conversation",
        aliases=("n",),
        usage="/new",
    ),
    CommandSpec(
        id="sessions",
        label="Sessions",
        description="Show all sessions",
        aliases=("ls",),
        usage="/sessions",
    ),
    CommandSpec(
        id="load",
        label="Load Session",
        description="Load a session by index",
        usage="/load <n>",
    ),
    CommandSpec(
        id="clear",
        label="Clear",
        description="Clear the screen",
        usage="/clear",
    ),
    CommandSpec(
        id="quit",
        label="Quit",
        description="Exit the application",
        aliases=("q", "exit"),
        usage="/quit",
    ),
)


class CommandRegistry:
    def __init__(self, specs: tuple[CommandSpec, ...] = DEFAULT_COMMAND_SPECS):
        self._specs = specs
        self._lookup: dict[str, CommandSpec] = {}
        for spec in specs:
            self._lookup[spec.id] = spec
            for alias in spec.aliases:
                self._lookup[alias] = spec

    @property
    def specs(self) -> tuple[CommandSpec, ...]:
        return self._specs

    def parse(self, user_input: str) -> ParsedCommand | None:
        stripped = user_input.strip()
        if not stripped:
            return None

        is_slash_command = stripped.startswith("/")
        if not is_slash_command and " " in stripped:
            return None

        body = stripped[1:] if is_slash_command else stripped
        if not body:
            return None

        name, _, remainder = body.partition(" ")
        spec = self._lookup.get(name)
        if spec is None:
            return None
        return ParsedCommand(
            spec=spec,
            name=name,
            args=remainder.strip(),
            raw_input=user_input,
        )

    def banner_text(self) -> str:
        usages = [spec.usage for spec in self._specs if spec.usage]
        return "Use " + ", ".join(usages[:-1]) + f", or {usages[-1]} for commands."


class CommandDispatcher:
    def __init__(self, registry: CommandRegistry, handlers: dict[str, CommandHandler]):
        self._registry = registry
        self._handlers = handlers

    async def dispatch(self, user_input: str) -> bool:
        parsed = self._registry.parse(user_input)
        if parsed is None:
            return False

        handler = self._handlers.get(parsed.spec.id)
        if handler is None:
            return True
        return await handler(parsed)
