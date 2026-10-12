"""Provider-visible names for MCP tools, and the collisions they can still cause.

An MCP server names its own tools, and Nova has its own. Registering both into one
flat namespace means a server advertising a tool called ``edit`` either shadows
Nova's editor or is dropped for it -- and silently dropped is the worst outcome,
because the connection test tells the user the tool is available and the agent can
never call it. Every comparable agent resolves this by namespacing: Claude Code,
Codex, OpenCode, Cursor and the OpenAI Agents SDK all expose a server's tool as
some prefixed form rather than its bare name.

``mcp__<server>__<tool>`` is the form Nova uses, for two reasons beyond collision
avoidance. The double underscore makes the server/tool boundary unambiguous,
where a single one cannot be split when either part contains underscores. And the
``mcp__`` prefix is what models are trained to recognise, so the model treats a
server's tools as tools rather than as built-ins.

Namespacing is not sufficient on its own, which is why :func:`allocate` exists
rather than a single ``qualify``. A truncated name can collide with another
truncated name, and a provider may refuse an over-long one outright, so the
allocator also enforces the length budget and guarantees the result is unique --
an allocator that can hand out the same name twice has reintroduced the exact
bug the namespace was added to remove.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

#: Marks a tool as having come from a server, and is the prefix Nova's own
#: permission rules match on (``mcp__github__*``). Withheld per-server when
#: ``mcp_prefix_tool_names`` is off; the rest of this module's work is unaffected,
#: because none of the safety properties depend on the prefix itself.
MCP_TOOL_PREFIX = "mcp__"

#: OpenAI's tool-use API rejects a ``function.name`` longer than this, and the
#: namespace makes every name longer, so the budget has to be enforced here
#: rather than discovered as a 400 from the provider.
MAX_TOOL_NAME_LENGTH = 64

#: 12 hex characters, matching what Codex uses. Eight was chosen first and is a
#: 32-bit space, which is fine until it is not: the whole point of a hash here is
#: to be the difference between two tools that would otherwise collide.
_HASH_LENGTH = 12
_SEPARATOR = "__"

#: How many times :func:`allocate` will re-hash a name that is still taken before
#: giving up. A 32-bit suffix makes this unreachable in practice; it exists so
#: that "still colliding" is a raised error rather than an unbounded loop.
_MAX_DISAMBIGUATIONS = 8

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


class McpNamingError(RuntimeError):
    """A tool could not be given a name distinct from every other tool."""


def sanitize(part: str, fallback: str) -> str:
    """A server or tool name reduced to characters a provider accepts.

    Dots and spaces are the common offenders -- ``@modelcontextprotocol/server-filesystem``
    and ``list_services.v2`` both appear in real listings.

    Args:
        part: The raw server or tool name.
        fallback: What to use when nothing survives. A server named ``"///"`` still
            has to produce a name, because dropping it would drop a working tool
            over a naming quirk.

    Returns:
        The name, or *fallback* when *part* contained nothing usable.
    """
    cleaned = _UNSAFE.sub("_", part or "").strip("_-")
    return cleaned or fallback


def _shorten(base: str, seed: str, *, force_hash: bool) -> str:
    """*base* within budget, with a hash suffix when it cannot fit as-is.

    The hash is of *seed* rather than *base*, so two names that share a readable
    prefix still differ: the parts a user reads survive, and the parts that
    distinguish them do not.
    """
    if not force_hash and len(base) <= MAX_TOOL_NAME_LENGTH:
        return base
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:_HASH_LENGTH]
    room = MAX_TOOL_NAME_LENGTH - len(digest) - 1
    stem = base[:room].rstrip("_-") or "mcp"
    return f"{stem}_{digest}"


def qualify(server: str, tool: str, *, prefix: bool = True) -> str:
    """The namespaced name for *tool* on *server*, before collision resolution.

    Args:
        server: The server's configured name, which need not match the server's
            own ``serverInfo`` -- the spec warns that the latter is not unique
            across servers.
        tool: The name the server reported.
        prefix: Whether to namespace under *server*. Off leaves the tool under
            its own sanitized name; callers still get collision handling.

    Returns:
        The name, within the length budget, or the shape :func:`allocate` builds
        from when the caller needs to account for other tools.

    """
    base = _base_name(server, tool, prefix)
    return _shorten(base, base, force_hash=False)


def _base_name(server: str, tool: str, prefix: bool) -> str:
    sanitized_server = sanitize(server, "server")
    sanitized_tool = sanitize(tool, "tool")
    if not prefix:
        return sanitized_tool
    return f"{MCP_TOOL_PREFIX}{sanitized_server}{_SEPARATOR}{sanitized_tool}"


def allocate(
    server_tools: Iterable[tuple[str, str]],
    reserved: Iterable[str] = (),
    *,
    unprefixed: Iterable[str] = (),
) -> dict[tuple[str, str], str]:
    """Assign every ``(server, tool)`` pair a distinct name that fits the budget.

    Args:
        server_tools: The pairs to name, each tool name as the *server* reports it.
        reserved: Names already taken -- Nova's built-in tools, and anything
            registered before this call. An MCP tool is never handed one of
            these, which is what keeps a server from displacing ``edit``.
        unprefixed: Servers whose tools should keep their own names. They still
            get sanitised, length-capped and deduplicated -- only the namespace is
            withheld, so this costs the one property and keeps the rest.

    Returns:
        A mapping from each pair to the name the model will see, in a form the
        server still accepts on ``tools/call``.

    Sorting is what makes the result deterministic: two servers whose names
    sanitize to the same string must get the same assignment on every run, or a
    resumed session would call a tool that no longer exists under that name.
    """
    taken = set(reserved)
    without_prefix = set(unprefixed)
    plans: list[tuple[str, str, tuple[str, str]]] = []
    for server, tool in server_tools:
        base = _base_name(server, tool, prefix=server not in without_prefix)
        plans.append((base, f"{server}\0{tool}", (server, tool)))

    # A base shared by two servers or tools cannot serve both, so both hash even
    # when they would have fit within budget.
    totals: dict[str, int] = {}
    for base, _, _ in plans:
        totals[base] = totals.get(base, 0) + 1

    assigned: dict[tuple[str, str], str] = {}
    for base, seed, key in sorted(plans):
        name = _shorten(
            base,
            seed,
            force_hash=totals[base] > 1 or base in taken,
        )
        attempt = 0
        while name in taken:
            # The 8-hex suffix is a 32-bit space, so reaching the bound is not a
            # thing that happens; the point of the bound is that a collision
            # cannot turn into a hang. `_shorten` is the only thing that can move
            # `name` off a taken value, so a loop that trusts it to do so is one
            # edit away from spinning. Exhausting it raises instead -- a missing
            # tool the user is told about, never one that silently overwrote
            # another.
            attempt += 1
            if attempt > _MAX_DISAMBIGUATIONS:
                raise McpNamingError(
                    f"could not find a free name for MCP tool {key[1]!r} "
                    f"on server {key[0]!r} after "
                    f"{_MAX_DISAMBIGUATIONS} attempts"
                )
            name = _shorten(base, f"{seed}\0{attempt}", force_hash=True)
        taken.add(name)
        assigned[key] = name
    return assigned
