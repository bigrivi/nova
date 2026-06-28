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

## Agent Workspace Files

Each agent can have its own workspace files at
`~/.nova/agents/<agent-key>/`:

- `IDENTITY.md` -- agent identity
- `SOUL.md` -- agent personality
- `USER.md` -- user profile
- `MEMORY.md` -- long-term memory

## Session Hierarchy

Sub-agent sessions are linked to their parent session, creating a session tree.
This allows context sharing and traceability.
