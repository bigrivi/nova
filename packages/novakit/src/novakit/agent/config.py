"""Agent configuration shared by Nova and standalone novakit users.

The core only reads ``model``/``provider``/``max_iterations``/``reasoning_effort``;
the remaining fields are Nova tool-layer options the core ignores.
``shortcut: carries Nova compatibility fields; split into a narrow CoreConfig
once the SDK stabilises, which needs a migration.``
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AgentConfig:
    """Tunable inputs for one agent run."""

    # Model key as defined in config.json (e.g., "my-gemma")
    model: str = "gpt-4o"
    provider: str = "ollama"
    max_iterations: int = 100
    max_tokens: int = 8192
    temperature: float = 0.7
    tools: list | None = None
    memory_review_interval: int = 10
    # Reasoning level for this run. None means "whatever the model config
    # declares", which is also what a provider that has no such concept gets.
    reasoning_effort: str | None = None
    # Ask a model to review actions the rules flagged, instead of interrupting
    # the user for every one. Off by default: a review costs a model call, and a
    # reviewer that waves through something the user would have refused is a worse
    # failure than a prompt. Set from the ``approval_review`` block in config.json.
    shell_review: bool = False
    # What a command that needs approval gets when the rules say so and no grant
    # covers it. ``ask`` waits for a human; ``dontAsk`` refuses instead, for runs
    # with nobody at the keyboard. Read from ``mode`` in permissions.json -- the
    # security-policy file, next to the rules whose answer it changes.
    permission_mode: str = "ask"
    # When True, the shell tool refuses anything it cannot prove only reads.
    # Used by read-only agents that still get shell for inspection.
    shell_read_only: bool = False


__all__ = ["AgentConfig"]
