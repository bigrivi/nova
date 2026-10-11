# Tool Overview

Nova ships with 26 built-in tools. The LLM decides which tools to call based on
your request. You don't need to invoke them manually -- just describe what you
want, and Nova handles the rest.

Connected MCP servers add more tools at runtime. Sub-agents receive neither MCP
tools nor `delegate_to_agent`.

## File Operations

| Tool | Description |
|------|-------------|
| [read](file-operations.md) | Read file contents |
| [write](file-operations.md) | Create or overwrite files |
| [edit](file-operations.md) | Precise string-match editing |
| [glob](file-operations.md) | Find files by name pattern |
| [grep](file-operations.md) | Search file contents by regex |

## Shell & Code

| Tool | Description |
|------|-------------|
| [shell](shell.md) | Execute shell commands |
| [code_run](code-execution.md) | Execute Python code |

## Web

| Tool | Description |
|------|-------------|
| [web_search](web.md) | Search the web |
| [web_fetch](web.md) | Fetch and extract web page content |
| [browser_use](web.md) | Full browser automation (click, type, navigate, screenshot) |

## Memory

| Tool | Description |
|------|-------------|
| [save_memory](../memory/index.md) | Save structured memories |
| [search_memory](../memory/index.md) | Search stored memories |
| [list_memories](../memory/index.md) | List memories |
| [delete_memory](../memory/index.md) | Delete memories |

## Interaction

| Tool | Description |
|------|-------------|
| [ask_user](ask-user.md) | Ask you questions |
| [todo_write](todo.md) | Manage task lists |
| `read_image` | Read images as base64 plus extracted text |

## Skills

| Tool | Description |
|------|-------------|
| [list_skills](../skills/index.md) | List available skills |
| [load_skill](../skills/index.md) | Load full skill content |
| [install_skill](../skills/index.md) | Install skills from ClawHub |

## Delegation

| Tool | Description |
|------|-------------|
| [delegate_to_agent](../advanced/multi-agent.md) | Delegate tasks to sub-agents |
| `subagent_status` | Check on a running delegated task |

## Background Tasks

| Tool | Description |
|------|-------------|
| `background_task_list` | List background tasks |
| `background_task_status` | Check a task's current state |
| `background_task_logs` | Read a task's output |
| `background_task_cancel` | Stop a task |
