import type {
    ReadonlyJSONObject,
    ReadonlyJSONValue,
} from "assistant-stream/utils";

export type NovaJsonObject = ReadonlyJSONObject;
export type NovaJsonValue = ReadonlyJSONValue;

export type NovaSessionSummary = {
    id: string;
    title: string | null;
    updated_at: number;
    agent_key: string;
    workspace_dir: string | null;
    pinned: boolean;
    project_id: string | null;
};

export type NovaProject = {
    id: string;
    name: string;
    path: string | null;
    created_at: number;
    updated_at: number;
};

export type NovaDirectoryEntry = {
    name: string;
    path: string;
};

export type NovaDirectoryListing = {
    path: string;
    parent: string | null;
    entries: NovaDirectoryEntry[];
};

export type NovaMessageRecord = {
    id: string;
    session_id: string;
    role: "user" | "assistant" | "tool";
    content: string;
    tool_call_id: string | null;
    tool_calls: NovaJsonObject[];
    time_created: number;
    images?: string[] | null;
    reasoning_content?: string | null;
    reasoning_elapsed_ms?: number | null;
    group_id?: string | null;
    error?: string | null;
    variant?: string | null;
};

export type NovaModelRecord = {
    id: string;
    provider: string;
    provider_name: string;
    model: string;
    label: string;
    tools: boolean;
    /** Reasoning levels this model accepts; empty means it offers none. */
    efforts: string[];
};

/** The model a session runs with, restored when the session is reopened. */
export type NovaSessionRoute = {
    provider: string | null;
    model: string | null;
    reasoning_effort: string | null;
};

export type NovaProviderRecord = {
    key: string;
    name: string;
    type: string;
    base_url: string;
    has_api_key: boolean;
};

export type NovaProviderCreateRequest = {
    key: string;
    type: string;
    name: string;
    base_url: string;
    api_key: string;
};

export type NovaModelCreateRequest = {
    provider: string;
    model: string;
    label: string;
    tools: boolean;
};

/** How an MCP server is reached: a local subprocess, or a remote endpoint. */
export type McpTransportKind = "stdio" | "http";

/**
 * A configured MCP server, as the settings list shows it.
 *
 * Secret values are withheld by the server: `envKeys` / `headerKeys` carry the
 * names of what is set, never the values, so rendering the list never needs a
 * credential to cross the wire. Editing a value means re-entering it.
 *
 * `loadedTools` / `skippedTools` describe what an agent can actually call, under
 * the namespaced names the model sees. Both are null until a toolset has been
 * built — which is not the same as empty, and not something to render as a
 * problem.
 */
export type NovaMcpServerRecord = {
    name: string;
    transport: McpTransportKind;
    command: string;
    args: string[];
    url: string;
    env_keys: string[];
    header_keys: string[];
    loaded_tools: string[] | null;
    skipped_tools: { tool: string; reason: string }[] | null;
    /** Set when the server could not be connected at all. */
    error: string | null;
};

/** One env var or header: a name and a value. */
export type McpKeyValue = {
    key: string;
    value: string;
};

/** The form's payload, for add, update and test alike. */
export type NovaMcpServerInput = {
    name: string;
    command: string;
    args: string[];
    env: McpKeyValue[];
    url: string;
    headers: McpKeyValue[];
};

/** What a connection test found, or why it failed. */
export type NovaMcpTestResult = {
    ok: boolean;
    server_name: string;
    server_version: string;
    tool_count: number;
    tool_names: string[];
    error: string;
};

export type NovaProviderUpdateRequest = {
    name?: string;
    type?: string;
    base_url?: string;
    api_key?: string;
};

export type NovaModelUpdateRequest = {
    label?: string;
    tools?: boolean;
};

export type NovaAgentKind = "main" | "sub";

export type NovaAgentPosture = "read_only" | "full";

export type NovaAgentMode = "primary" | "subagent";

export type NovaAgent = {
    key: string;
    name: string;
    description: string;
    model: string;
    provider: string;
    /** Default reasoning level for new conversations on this agent. */
    reasoning_effort?: string | null;
    tools?: string | string[] | null;
    posture?: NovaAgentPosture;
    parents: string[];
    workspace_dir?: string | null;
    created_at: number;
    updated_at: number;
    kind: NovaAgentKind;
    mode: NovaAgentMode;
    editable_fields: string[];
};

export type NovaAgentCreateRequest = {
    key: string;
    name: string;
    description?: string;
    model?: string;
    provider?: string;
    tools?: string[];
    workspace_dir?: string;
    posture?: string;
    mode?: NovaAgentMode;
    parent_ids?: string[];
};

export type NovaThreadSummary = {
    id: string;
    title: string;
    status: "regular";
    workspace_dir: string | null;
    pinned: boolean;
    updated_at: number;
    project_id: string | null;
    agent_key: string;
};

export type NovaBackgroundTaskStatus =
    | "queued"
    | "running"
    | "succeeded"
    | "failed"
    | "cancelled"
    | "timed_out"
    | "interrupted";

export type NovaBackgroundTask = {
    task_id: string;
    kind: string;
    session_id: string;
    label: string;
    status: NovaBackgroundTaskStatus;
    background: boolean;
    created_at_ms: number;
    started_at_ms: number | null;
    finished_at_ms: number | null;
    timeout_seconds: number;
    exit_code: number | null;
    output_bytes: number;
    output_truncated: boolean;
    output_preview?: string;
    output_tail?: string;
    result: string;
    error: string | null;
    progress: number | null;
    progress_message: string | null;
    last_activity_at_ms: number | null;
};

export type NovaMemoryRecord = {
    id: string;
    key: string;
    scope: "user" | "project" | "session";
    memory_type: "fact" | "preference" | "decision" | "context";
    summary: string;
    content: string;
    tags: string[];
    session_id: string | null;
    created_at: number;
    updated_at: number;
};

export type NovaAttachmentContent = {
    type: string;
    [key: string]: NovaJsonValue | undefined;
};

export type NovaAttachmentData = {
    id: string;
    type: string;
    name: string;
    contentType?: string;
    content: NovaAttachmentContent[];
};

export type NovaStreamEvent = {
    type: string;
    /** SSE `id:` sequence assigned by the backend stream buffer. Absent when
     * the backend did not frame the chunk (e.g. older servers). Used for
     * refresh-resume (`resume_from_seq`) and replay dedup. */
    sequence?: number;
    data?: NovaJsonObject;
    delta?: string;
    errorText?: string;
    toolCallId?: string;
    toolName?: string;
    input?: NovaJsonObject;
    output?: NovaJsonValue;
    elapsedMs?: number;
};
