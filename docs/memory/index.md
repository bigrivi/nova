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

## Configuration

Memory review frequency is configurable via `memory_review_interval` in settings.
