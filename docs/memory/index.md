# Memory System

Nova remembers across sessions. It stores structured memories in a local SQLite
database and uses them to provide context in future conversations.

## Scopes

Memories are scoped to control where they apply:

- **`user`** -- personal preferences, facts about you. Available across all
  projects and sessions.
- **`project`** -- project-specific context. Available when working on the same
  project.
- **`session`** -- single-session context. Only available during the current
  session.
- **`agent`** -- tied to one agent's own workspace, so a delegated sub-agent
  does not read the parent's private context.

## Memory Types

- `fact` -- factual information
- `preference` -- your preferences and habits
- `decision` -- decisions made and their rationale
- `context` -- situational context

## How It Works

The agent decides when to save or recall memories based on the conversation.
You can also ask Nova to remember or forget things explicitly:

```text
Remember that I prefer using VS Code for Python development
What do you know about me?
```

## Automatic Memory Review

Every N turns, Nova reviews the conversation and automatically extracts
important information as memories. This happens in the background without
interrupting your workflow.

## Learning Loop (opt-in)

Nova can optionally learn from experience across sessions. When enabled
(`learning.enabled: true` in `config.json`), it runs a background loop that:

- **Indexes sessions** for full-text search (FTS5), so Nova can recall what
  was discussed in past conversations.
- **Nudges** the agent to persist durable facts every N turns.
- **Extracts skills** after sufficiently complex tasks, reusing or improving
  existing skills rather than creating duplicates.
- **Builds a user model** that deepens across sessions and is injected into
  the system prompt.

The loop is off by default except session search. It never blocks the main
turn: all work runs in the background and failures are isolated.

## Configuration

Memory review frequency is configurable via `memory_review_interval` in settings.
The learning loop is configured via the `learning` block in `config.json`
(see [Settings](../configuration/settings.md)).
