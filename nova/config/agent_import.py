"""Parse an opencode-style agent Markdown file into Nova's agent model.

The file is a small YAML-ish frontmatter block delimited by ``---`` followed by
a Markdown body that is the agent's persona/instructions. Nova ships no YAML
dependency (the skill loader parses frontmatter by hand for the same reason), so
this uses a focused line reader that handles exactly what the agent format uses:
top-level scalars, wrapped (folded) scalar values, and the one nested block we
care about, ``tools:``.

Field mapping into Nova:
- ``description``/``mode``/``model``/``provider`` map directly.
- ``tools`` (a map of tool -> bool) drives ``posture``: any write-capable tool
  (write/edit/bash/patch) means ``full``, otherwise ``read_only``. Nova gates
  tool access by posture, so the concrete list is left to the posture default.
- ``temperature``/``steps`` have no Nova equivalent and are reported as warnings.
- The Markdown body becomes the agent's ``IDENTITY.md`` persona.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(?P<frontmatter>.*?)(?:\r?\n)---[ \t]*(?P<trailing>\r?\n|$)",
    re.DOTALL,
)
_SCALAR_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9_-]*)\s*:\s*(?P<value>.*?)\s*$")
_INDENTED_RE = re.compile(
    r"^\s+(?P<key>[A-Za-z][A-Za-z0-9_-]*)\s*:\s*(?P<value>.*?)\s*$"
)
_SLUG_RE = re.compile(r"[^a-z0-9-]+")

_TRUE = {"true", "yes", "on", "1"}
_FALSE = {"false", "no", "off", "0"}
_WRITE_CAPABLE_TOOLS = ("write", "edit", "bash", "patch")


class AgentImportError(ValueError):
    """Raised when agent Markdown cannot be parsed into a valid agent."""


@dataclass
class ParsedAgent:
    """An agent definition parsed from Markdown, mapped to Nova's fields."""

    name: str
    description: str
    mode: str
    model: str
    provider: str
    posture: str
    tools: dict[str, bool]
    body: str
    warnings: list[str] = field(default_factory=list)


def _strip_quotes(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _as_bool(value: str) -> bool | None:
    low = value.strip().lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    return None


def parse_agent_markdown(content: str) -> ParsedAgent:
    """Parse agent Markdown into a :class:`ParsedAgent`.

    Args:
        content: Full file text: ``---`` frontmatter block then a Markdown body.

    Returns:
        The parsed agent with fields mapped onto Nova's model.

    Raises:
        AgentImportError: If the file has no leading ``---`` frontmatter block.
    """
    match = _FRONTMATTER_RE.match(content)
    if match is None:
        raise AgentImportError(
            "Agent Markdown must start with a '---' frontmatter block."
        )
    body = content[match.end():].lstrip("\r\n")

    scalars: dict[str, str] = {}
    tools: dict[str, bool] = {}
    in_tools = False
    last_key: str | None = None

    for raw_line in match.group("frontmatter").splitlines():
        if not raw_line.strip():
            continue
        if raw_line[:1].isspace():
            if in_tools:
                item = _INDENTED_RE.match(raw_line)
                if item is not None:
                    flag = _as_bool(item.group("value"))
                    if flag is not None:
                        tools[item.group("key").strip().lower()] = flag
            elif last_key is not None:
                # A wrapped (folded) scalar value, e.g. a multi-line description.
                scalars[last_key] = f"{scalars[last_key]} {raw_line.strip()}".strip()
            continue

        in_tools = False
        scalar = _SCALAR_RE.match(raw_line)
        if scalar is None:
            last_key = None
            continue
        key = scalar.group("key").strip().lower()
        value = scalar.group("value").strip()
        if key == "tools" and value == "":
            in_tools = True
            last_key = None
            continue
        scalars[key] = _strip_quotes(value)
        last_key = key

    mode = scalars.get("mode", "primary").strip().lower()
    if mode not in {"primary", "subagent"}:
        mode = "primary"

    warnings = [
        f"'{key}' is not supported by Nova agents and was ignored."
        for key in ("temperature", "steps")
        if key in scalars
    ]

    posture = (
        "full"
        if any(tools.get(name) for name in _WRITE_CAPABLE_TOOLS)
        else "read_only"
    )

    return ParsedAgent(
        name=scalars.get("name", "").strip(),
        description=scalars.get("description", "").strip(),
        mode=mode,
        model=scalars.get("model", "").strip(),
        provider=scalars.get("provider", "").strip(),
        posture=posture,
        tools=tools,
        body=body,
        warnings=warnings,
    )


def slugify_key(text: str) -> str:
    """Derive a candidate agent key ([a-z0-9-]) from free text.

    The caller is responsible for validating the result against the agent key
    pattern; an over-short or empty slug should be rejected with a clear error.
    """
    slug = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:32]
