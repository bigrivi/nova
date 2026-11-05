/** Wire types for the subset of the Nova HTTP API the mobile client uses. */

export type JsonObject = Record<string, unknown>;

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

export type NovaMessageRecord = {
    id: string;
    session_id: string;
    role: "user" | "assistant" | "tool";
    content: string;
    display_text?: string | null;
    tool_call_id: string | null;
    tool_calls: JsonObject[];
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
    efforts: string[];
    context?: number | null;
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

export type NovaAgent = {
    key: string;
    name: string;
    description: string;
    model: string;
    provider: string;
    reasoning_effort?: string | null;
    parents: string[];
    kind: string;
    mode: string;
};

export type NovaAttachmentData = {
    id: string;
    type: string;
    name: string;
    content_type?: string;
    content: Array<
        { type: "image"; image: string } | { type: "text"; text: string }
    >;
};

export type NovaStreamEvent = {
    type: string;
    sequence?: number;
    data?: JsonObject;
    delta?: string;
    errorText?: string;
    toolCallId?: string;
    toolName?: string;
    input?: JsonObject;
    output?: unknown;
    elapsedMs?: number;
};

export type ApprovalRequest = {
    requestId: string;
    command: string;
    description: string;
    toolName: string;
    rememberable: boolean;
    family: string;
    target: string;
    scriptScoped: boolean;
    dangerous: boolean;
    workspace: string;
};

export type StreamStatus = {
    status: "active" | "detached" | "done" | string;
    last_seq: number;
};

export type PendingPrompts = {
    approvals?: ApprovalRequest[];
    ask?: unknown[];
};

export type SessionEventFrame =
    | { type: "snapshot"; active: string[]; tasks: NovaBackgroundTask[] }
    | { type: "state"; session_id: string; state: string }
    | { type: "task"; task: NovaBackgroundTask }
    | { type: "title"; session_id: string; title: string };

export type ContextUsage = {
    used: number;
    limit: number;
    percent: number;
};
