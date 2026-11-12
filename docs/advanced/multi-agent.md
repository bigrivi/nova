# Multi-Agent

Nova supports sub-agents through the `delegate_to_agent` tool. The main agent
can delegate tasks to specialized sub-agents, each with their own configuration,
skills, and memory.

## How It Works

1. The main agent identifies a task that would benefit from a specialist agent
2. It calls `delegate_to_agent` with the task description
3. A sub-agent is spawned with its own agent configuration
4. The sub-agent works on the task independently
5. Results are returned to the main agent

## Agent Configuration

Agents are stored in the database and configured with:

- `agent_key` -- unique identifier
- `provider` -- which LLM provider to use
- `model` -- which model to use
- `instructions` -- system prompt / identity

Leave the provider or the model empty and the agent follows the route the
session is already running on, and failing that the first provider you
configured. A route naming a provider that is no longer configured is treated
as no route at all, so a deleted provider cannot strand a conversation.

## Agent Workspace Files

Each agent can have its own workspace files at
`~/.nova/agents/<agent-key>/`:

- `IDENTITY.md` -- agent identity
- `SOUL.md` -- agent personality
- `USER.md` -- user profile
- `MEMORY.md` -- long-term memory

## The Plan Agent

Nova ships with a `plan` agent: a primary agent that can read the project but
not change it. Switch to it and Nova investigates the code and lays out a
plan; switch back to `main` and the work gets done.

It is an ordinary agent, not a special mode:

- `mode` is `primary`, so it is selected like any other agent
- `posture` is `read_only`, so the tools that change things (`write`, `edit`,
  `shell`, `code_run`) are never offered to the model at all
- its persona lives in `~/.nova/agents/plan/IDENTITY.md`

The persona is written into your Nova home the first time Nova starts. Edit it
and Nova will not take it back: a plan agent you tuned is yours.

The plan agent names no model of its own, so it runs on whichever model the
session already uses.

## Session Hierarchy

Sub-agent sessions are linked to their parent session, creating a session tree.
This allows context sharing and traceability.
