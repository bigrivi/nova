"""Parse an agent definition Markdown file into Nova's agent model.

Two frontmatter dialects dominate the ecosystem, and both are accepted here:

- **opencode**: ``description`` (required there), ``mode: primary|subagent|all``,
  ``model: provider/model``, a ``permission:`` map (or the deprecated ``tools:``
  map). The agent's name is the file name, so the caller supplies it.
- **Claude Code / Cursor**: ``name``, ``description``, a comma-separated
  ``tools:`` allowlist, ``disallowedTools``, ``model`` aliases. Cursor reads
  ``.claude/agents`` too, so this dialect covers it.

Frontmatter is real YAML and is read with PyYAML: these files come from other
tools, and their quoting, block scalars and inline maps are not worth
re-implementing by hand. Keys Nova has no equivalent for are reported one by one
as warnings instead of being dropped silently.

Mapping into Nova:

- ``description`` / ``mode`` / ``model`` / ``provider`` map directly.
- Tool permissions collapse to ``posture``. Nova gates a sub-agent by posture
  (an allowlist preset ``read_only`` or ``full``), so the individual tool names
  are kept for display but do not narrow the runtime set. The rule is
  fail-safe: a write-capable tool must be *explicitly granted* (``tools:`` entry
  true, listed in an allowlist, or ``permission: allow``) for ``full``; anything
  unspecified is ``read_only``.
- The Markdown body becomes the agent's ``IDENTITY.md`` persona.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(?P<frontmatter>.*?)(?:\r?\n)---[ \t]*(?P<trailing>\r?\n|$)",
    re.DOTALL,
)
_SLUG_RE = re.compile(r"[^a-z0-9-]+")

#: The agent key rule every front door shares (HTTP route, CLI).
AGENT_KEY_RE = re.compile(r"^[a-z0-9-]{3,32}$")

#: Tools whose availability means "this agent can change the machine".
_WRITE_CAPABLE = frozenset(
    {
        "apply_patch",
        "bash",
        "edit",
        "multiedit",
        "notebookedit",
        "patch",
        "shell",
        "write",
    }
)

#: Frontmatter keys this module understands; everything else is a warning.
_KNOWN_KEYS = frozenset(
    {
        "name",
        "description",
        "mode",
        "model",
        "provider",
        "tools",
        "disallowedTools",
        "permission",
    }
)


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


def _names(value: object) -> list[str]:
    """Read a tool list that may be a comma string, a YAML list, or one name."""
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _base_name(name: str) -> str:
    """Strip a specifier: ``Bash(git push *)`` is still the bash tool."""
    return name.split("(", 1)[0].strip().lower()


def _value_denies(value: object) -> bool:
    """Whether one ``permission:`` entry refuses a capability."""
    if isinstance(value, bool):
        return value is False
    if isinstance(value, str):
        return value.strip().lower() == "deny"
    if isinstance(value, dict):
        # `bash: {"*": deny, "git diff": allow}` denies the command family.
        return any(
            isinstance(inner, str) and inner.strip().lower() == "deny"
            for key, inner in value.items()
            if str(key).strip() == "*"
        )
    return False


def _value_allows(value: object) -> bool:
    """Whether one ``permission:`` entry grants a capability without a prompt."""
    if isinstance(value, bool):
        return value is True
    if isinstance(value, str):
        return value.strip().lower() == "allow"
    if isinstance(value, dict):
        return any(
            isinstance(inner, str) and inner.strip().lower() == "allow"
            for key, inner in value.items()
            if str(key).strip() == "*"
        )
    return False


def _denied_tools(frontmatter: dict) -> set[str]:
    """Every write-capable capability the definition explicitly withholds."""
    denied = {_base_name(name) for name in _names(frontmatter.get("disallowedTools"))}
    tools = frontmatter.get("tools")
    if isinstance(tools, dict):
        for name, value in tools.items():
            if value is False:
                target = _base_name(str(name))
                denied |= _WRITE_CAPABLE if target == "*" else {target}
    permission = frontmatter.get("permission")
    if isinstance(permission, dict):
        for name, value in permission.items():
            target = str(name).strip().lower()
            if _value_denies(value):
                denied |= _WRITE_CAPABLE if target == "*" else {target}
    return denied


def _tools_map(frontmatter: dict) -> dict[str, bool]:
    """The tool set as a plain map, whichever dialect expressed it."""
    tools = frontmatter.get("tools")
    if isinstance(tools, dict):
        return {str(name): bool(value) for name, value in tools.items()}
    if isinstance(tools, (str, list)):
        # An allowlist: only what is listed is granted.
        return {name: True for name in _names(tools)}
    return {}


def _posture(frontmatter: dict) -> str:
    """Collapse the dialect's permissions into Nova's posture.

    Fail-safe by construction: a write-capable capability must be explicitly
    granted. An agent definition that says nothing about tools imports read-only,
    which is the same default the product uses for a sub-agent nobody configured.
    """
    denied = _denied_tools(frontmatter)
    tools = frontmatter.get("tools")
    granted: set[str] = set()
    if isinstance(tools, (str, list)):
        granted = {_base_name(name) for name in _names(tools)}
    elif isinstance(tools, dict):
        granted = {_base_name(str(name)) for name, value in tools.items() if value}
    else:
        permission = frontmatter.get("permission")
        if isinstance(permission, dict):
            granted = {
                str(name).strip().lower()
                for name, value in permission.items()
                if _value_allows(value)
            }
    return "full" if (granted - denied) & _WRITE_CAPABLE else "read_only"


def _model_and_provider(frontmatter: dict) -> tuple[str, str]:
    """Split ``provider/model``; an unresolvable alias is the caller's call."""
    raw_model = str(frontmatter.get("model") or "").strip()
    raw_provider = str(frontmatter.get("provider") or "").strip()
    if not raw_model:
        return "", raw_provider
    if "/" in raw_model:
        provider, model = raw_model.split("/", 1)
        return model.strip(), (raw_provider or provider.strip())
    # Claude's `sonnet`/`opus`/`haiku` are aliases of a provider Nova cannot
    # know; guessing would point the agent at a model that does not exist. The
    # caller supplies the pair, or the import reports the gap.
    return raw_model, (raw_provider or "")


def parse_agent_markdown(content: str) -> ParsedAgent:
    """Parse an agent Markdown definition into Nova's fields.

    Args:
        content: Full file text: ``---`` frontmatter block then a Markdown body.

    Returns:
        The parsed agent with fields mapped onto Nova's model.

    Raises:
        AgentImportError: If the file has no leading ``---`` frontmatter block,
            or the frontmatter is not valid YAML.
    """
    match = _FRONTMATTER_RE.match(content)
    if match is None:
        raise AgentImportError(
            "Agent Markdown must start with a '---' frontmatter block."
        )
    try:
        loaded = yaml.safe_load(match.group("frontmatter")) or {}
    except yaml.YAMLError as error:
        raise AgentImportError(f"Frontmatter is not valid YAML: {error}") from error
    if not isinstance(loaded, dict):
        raise AgentImportError("Frontmatter must be a mapping of keys to values.")

    frontmatter = {str(key): value for key, value in loaded.items()}
    body = content[match.end() :].strip()

    warnings: list[str] = []
    mode = str(frontmatter.get("mode") or "primary").strip().lower()
    if mode not in {"primary", "subagent"}:
        # `all` means "usable both ways" in opencode; a parent decides the rest.
        if mode != "all":
            warnings.append(f"Unknown mode '{mode}'; treated as primary.")
        mode = "primary"

    model, provider = _model_and_provider(frontmatter)
    for key in sorted(set(frontmatter) - _KNOWN_KEYS):
        warnings.append(f"Ignored frontmatter key '{key}': Nova has no equivalent.")

    return ParsedAgent(
        name=str(frontmatter.get("name") or "").strip(),
        description=str(frontmatter.get("description") or "").strip(),
        mode=mode,
        model=model,
        provider=provider,
        posture=_posture(frontmatter),
        tools=_tools_map(frontmatter),
        body=body,
        warnings=warnings,
    )


def slugify_key(name: str) -> str:
    """Reduce a display name to an agent key (``UI Designer`` -> ``ui-designer``)."""
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug
