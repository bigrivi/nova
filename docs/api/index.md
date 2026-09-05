# Server API

The Nova server is a FastAPI app created in `nova/server/app.py` and started with `nova serve`. It listens on `127.0.0.1:8765` by default and shares the same Python runtime as the TUI, frontend, and desktop shell. All paths below are relative to that host.

Base URL in development:

```text
http://127.0.0.1:8765
```

## Conventions

* JSON request and response bodies unless noted otherwise.
* Errors use standard HTTP status codes with a `{"detail": "..."}` payload.
* Paginated or list responses wrap items in an `items` array.
* Session, agent, and memory identifiers are opaque strings.

## Health and Frontend

### `GET /health`

Liveness check. Always available.

```json
{
  "status": "ok",
  "service": "nova",
  "mode": "server"
}
```

### `GET /`

Serves the built frontend when `NOVA_FRONTEND_DIST` points at an existing directory. In that case the route is mounted as a static file handler with HTML fallback. When no frontend build is present, it returns a JSON stub:

```json
{
  "service": "nova",
  "mode": "server"
}
```

## Sessions

### `GET /api/sessions`

List sessions. Optional query parameter `agent_key` filters to a single agent.

Response (`SessionListResponse`):

```json
{
  "items": [
    {
      "id": "01H...",
      "title": "Fix login bug",
      "updated_at": 1715000000000,
      "agent_key": "main",
      "workspace_dir": "/Users/you/project"
    }
  ]
}
```

### `GET /api/sessions/{session_id}/messages`

Returns the user-visible history for a session (`MessageListResponse`). Compacted or hidden messages are excluded.

Each `MessageRecord`:

```json
{
  "id": "msg_...",
  "session_id": "01H...",
  "role": "user | assistant | tool",
  "content": "hello",
  "tool_call_id": null,
  "tool_calls": [],
  "time_created": 1715000000000,
  "images": null,
  "reasoning_content": null,
  "reasoning_elapsed_ms": null,
  "group_id": null
}
```

### `GET /api/sessions/{session_id}/context`

Returns token usage for a session. This is the same estimate the compaction system uses, anchored on the provider's `tokens_input` accounting when available.

Optional query parameters: `provider`, `model`. If omitted, the server resolves them from the session's agent, then falls back to the first configured provider and model.

Response:

```json
{
  "used": 48210,
  "limit": 102400,
  "percent": 47,
  "message_count": 64
}
```

* `used`: estimated tokens in the current context.
* `limit`: model context limit after the 20 percent safety margin.
* `percent`: `used / limit * 100`.
* `message_count`: raw message count in the session.

### `PATCH /api/sessions/{session_id}`

Rename a session.

Request (`RenameSessionRequest`):

```json
{
  "title": "New title"
}
```

Constraints: `1 <= title.length <= 200`. Returns `SessionActionResponse`:

```json
{
  "status": "renamed",
  "session_id": "01H..."
}
```

404 if the session does not exist.

### `PUT /api/sessions/{session_id}/workspace`

Set or clear the per-session workspace directory. Pass `null` or an empty string to clear it.

Request (`UpdateSessionWorkspaceRequest`):

```json
{
  "workspace_dir": "/Users/you/project-a"
}
```

The server normalizes the path (expands `~`, resolves symlinks). Response:

```json
{
  "status": "workspace_updated",
  "session_id": "01H..."
}
```

404 if the session does not exist.

### `DELETE /api/sessions/{session_id}`

Delete a session. Optional query parameter `delete_memories` (boolean, default `false`) also removes memories linked to that session.

Response:

```json
{
  "status": "deleted",
  "session_id": "01H..."
}
```

404 if the session does not exist.

## Filesystem

### `GET /api/fs/list`

Browse the local filesystem for the workspace picker. Optional query parameter `path`; when omitted, the server lists a sensible default.

Response (`DirectoryListing`):

```json
{
  "path": "/Users/you/project",
  "parent": "/Users/you",
  "entries": [
    { "name": "src", "path": "/Users/you/project/src" }
  ]
}
```

Errors: `404` for missing or non-directory paths, `403` for permission errors.

## Models and Providers

### `GET /api/models`

List every model across all configured providers.

Response (`ModelListResponse`):

```json
{
  "items": [
    {
      "id": "ollama:my-model",
      "provider": "ollama",
      "provider_name": "Ollama (local)",
      "model": "my-model",
      "label": "my-model",
      "tools": true
    }
  ]
}
```

`id` is `provider_key:model_key`. `tools` is true when `tools` or `toolCalling` is set in the model config.

### `GET /api/providers`

List configured providers.

Response (`ProviderListResponse`):

```json
{
  "items": [
    { "key": "ollama", "name": "Ollama (local)", "type": "ollama" }
  ]
}
```

### `POST /api/config/providers`

Add a new provider and persist it to `~/.nova/config.json`.

Request (`ProviderCreateRequest`):

```json
{
  "key": "openai",
  "type": "openai-compatible",
  "name": "OpenAI",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-..."
}
```

* `key`: alias you will use in `agent_key:provider` references.
* `type`: one of `ollama`, `openai-compatible`, `openai-response`, `anthropic`.
* `name`, `base_url`, `api_key`: optional, empty string is allowed.

Returns the refreshed `ModelListResponse` on success. `400` on validation error.

### `POST /api/config/models`

Add a model to an existing provider.

Request (`ModelCreateRequest`):

```json
{
  "provider": "ollama",
  "model": "my-model",
  "label": "My Model",
  "tools": true
}
```

* `label`: display name, defaults to the model key.
* `tools`: whether the model can call tools (default `true`).

Returns the refreshed `ModelListResponse`. `400` on validation error (unknown provider, invalid shape).

## Chat

### `POST /api/chat`

Non-streaming chat. Sends a message, runs the agent loop to completion, and returns the final response.

Request (`ChatRequest`):

```json
{
  "session_id": "01H...",
  "message": "hello",
  "provider": "ollama",
  "model": "my-model",
  "agent_key": "main",
  "workspace_dir": "/Users/you/project",
  "metadata": {},
  "attachments": []
}
```

* `session_id`: omit or pass `null` to create a new session. The response will contain the new id.
* `provider`, `model`: optional overrides, otherwise the agent's configured model is used.
* `agent_key`: defaults to `main`.
* `workspace_dir`: per-request workspace override, normalized like the workspace endpoint.
* `attachments`: array of `AttachmentData` objects with `id`, `type` (`image` or `document`), `name`, `content_type`, and `content` parts. Images are sent as base64 data URLs, documents as text parts prepended to the prompt.

Response (`ChatResponse`):

```json
{
  "session_id": "01H...",
  "status": "completed",
  "message": "Done."
}
```

`status` is one of `completed`, `cancelled`, `input_required`, `error`.

### `POST /api/chat/stream`

Streaming chat over Server-Sent Events, compatible with the Vercel AI SDK UI message stream.

Headers on the response:

```text
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
x-vercel-ai-ui-message-stream: v1
```

Each event is an SSE `data:` line with a JSON payload and a blank line terminator. The stream ends with `data: [DONE]`.

Example framing:

```text
data: {"type":"start","messageId":"msg_abc"}\n
\n
data: {"type":"start-step"}\n
\n
data: {"type":"text-start","id":"text_xyz"}\n
\n
data: {"type":"text-delta","id":"text_xyz","delta":"hello"}\n
\n
data: {"type":"text-end","id":"text_xyz"}\n
\n
data: {"type":"finish-step"}\n
\n
data: {"type":"finish"}\n
\n
data: [DONE]\n
\n
```

Request body is the same `ChatRequest` as `POST /api/chat`.

AI SDK UI message parts emitted by the server (from `nova/server/ai_sdk_stream.py`):

| `type` | Purpose |
|--------|---------|
| `start` | New assistant message, carries `messageId` |
| `start-step` / `finish-step` | Turn boundaries inside a multi-turn run |
| `text-start` / `text-delta` / `text-end` | Streaming text, grouped by `id` |
| `reasoning-start` / `reasoning-delta` / `reasoning-end` | Model reasoning / thinking. `reasoning-end` may include `elapsedMs` |
| `tool-input-start` / `tool-input-available` | Tool call announced, with `toolCallId`, `toolName`, and parsed `input` |
| `tool-output-available` | Tool result, with `toolCallId` and `output` |
| `data-nova-session` | Session id for a newly created session, `{"sessionId": "..."}` |
| `data-nova-approval-required` | Shell approval needed, carries `sessionId`, `requestId`, `command`, `description`, `toolCallId`, `toolName` |
| `data-nova-heartbeat` | Keepalive while waiting for approval |
| `data-nova-tool-error` | Tool failure detail, `{"toolName","toolCallId","message"}` |
| `data-nova-context` | Context usage `{"used","limit","percent"}` |
| `data-nova-compaction-start` / `data-nova-compaction-end` | Compaction lifecycle, start carries `message_count` and `token_count` |
| `data-nova-input-required` | Agent asked the user a question via `ask_user` |
| `error` | Terminal error, `{"errorText": "..."}` |
| `abort` | Run was interrupted |
| `finish` | Normal completion |
| `[DONE]` | Stream terminator |

The frontend and TUI consume this stream directly. If you build a custom client, handle `data-nova-approval-required` by calling `POST /api/chat/approve`, and treat `data: [DONE]` as the end of the stream.

### `POST /api/chat/interrupt`

Interrupt the active run for a session.

Request (`InterruptRequest`):

```json
{
  "session_id": "01H..."
}
```

Response (`InterruptResponse`):

```json
{
  "session_id": "01H...",
  "interrupted": true
}
```

`interrupted` is `false` if no active run was found for that session.

### `POST /api/chat/approve`

Resolve a pending shell approval. This endpoint is currently undocumented elsewhere in the API surface and is the counterpart to the `data-nova-approval-required` SSE event.

* Query parameter: `session_id` (required, string).
* Body (`ApproveRequest`):

```json
{
  "request_id": "apr_...",
  "approved": true,
  "remember": false
}
```

* `request_id`: the `requestId` from the approval SSE event.
* `approved`: whether the command may run.
* `remember`: when `true`, the decision is kept for the session so identical commands do not prompt again.

Responses:

```json
{
  "status": "resolved",
  "approved": true
}
```

Errors: `400` if `session_id` is missing, `404` if no active agent is found for the session or the approval request id is unknown.

Flow:

```text
client -> POST /api/chat/stream  (starts a turn that needs approval)
server -> data: {"type":"data-nova-approval-required","data":{"requestId":"apr_...","command":"rm -rf /tmp/..."}}
client -> POST /api/chat/approve?session_id=01H...  {"request_id":"apr_...","approved":true}
server -> resumes tool execution, stream continues with tool-output-available / text-delta / finish
```

## Agents

### `GET /api/agents`

List all agents.

Response:

```json
{
  "items": [
    {
      "key": "main",
      "name": "Nova",
      "description": "...",
      "model": "my-model",
      "provider": "ollama",
      "tools": null,
      "workspace_dir": null,
      "parent_ids": null
    }
  ]
}
```

### `GET /api/agents/{key}`

Fetch a single agent. `404` if the key does not exist.

### `POST /api/agents`

Create a new agent.

Request (`AgentCreateRequest`):

```json
{
  "key": "researcher",
  "name": "Researcher",
  "description": "Helps with research",
  "model": "my-model",
  "provider": "ollama",
  "tools": null,
  "workspace_dir": null,
  "parent_ids": null
}
```

* `key`: `3-32` chars, lowercase letters, digits, and hyphens only (`^[a-z0-9-]{3,32}$`).
* `name`, `model`, `provider`: required.
* `tools`, `workspace_dir`, `parent_ids`: optional.

The server creates `~/.nova/agents/<key>/` on success. `400` on bad key shape, `409` if the key already exists.

### `DELETE /api/agents/{key}`

Delete an agent. The `main` agent cannot be deleted (`400`). `404` if the key does not exist.

Response:

```json
{
  "status": "deleted",
  "key": "researcher"
}
```

### `PATCH /api/agents/{key}`

Update the model and provider for an agent.

Request:

```json
{
  "model": "my-model",
  "provider": "ollama"
}
```

Both fields are required. `404` if the agent does not exist. Returns the updated agent object.

## Memories

### `GET /api/memories`

List memories. Optional query parameter `session_id`: when provided, returns memories linked to that session. When omitted, returns up to 50 memories across all scopes.

Response (`MemoryListResponse`):

```json
{
  "items": [
    {
      "id": "mem_...",
      "key": "project-conventions",
      "scope": "project",
      "memory_type": "fact",
      "summary": "Uses Bun for the TUI",
      "content": "The TUI uses Bun and OpenTUI...",
      "tags": ["tui"],
      "session_id": null,
      "created_at": 1715000000000,
      "updated_at": 1715000000000
    }
  ]
}
```

`scope` is one of `user`, `project`, `session`, `all` (filter only). `memory_type` is one of `fact`, `preference`, `decision`, `context`.

### `DELETE /api/memories/{memory_id}`

Delete a memory by id.

Response (`MemoryActionResponse`):

```json
{
  "status": "deleted",
  "memory_id": "mem_..."
}
```

`404` if the memory does not exist.
