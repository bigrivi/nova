/** Nova backend API types (ported from frontend/src/types/nova.ts, without the assistant-ui dependency) */

export type ReadonlyJSONValue =
    string | number | boolean | null | ReadonlyJSONObject | ReadonlyJSONValue[];

export interface ReadonlyJSONObject {
    readonly [key: string]: ReadonlyJSONValue;
}

export type NovaJsonObject = ReadonlyJSONObject;
export type NovaJsonValue = ReadonlyJSONValue;

export type NovaSessionSummary = {
    id: string;
    title: string | null;
    updated_at: number;
    agent_key: string;
    /** Set on a copy: the session it was forked from. */
    forked_from?: string | null;
    fork_point_message_id?: string | null;
};

export type NovaProjectRecord = {
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
    tool_call_id: string | null;
    tool_calls: NovaJsonObject[];
    time_created: number;
    images?: string[] | null;
    /** Text to render in the transcript; `content` is what the model read. */
    display_text?: string | null;
    reasoning_content?: string | null;
    reasoning_elapsed_ms?: number | null;
    group_id?: string | null;
    error?: string | null;
    /** Server-set marker for messages the user did not type (e.g. subagent). */
    variant?: string | null;
};

export type NovaModelRecord = {
    id: string;
    provider: string;
    provider_name: string;
    model: string;
    label: string;
    tools: boolean;
    /** Reasoning levels this model offers; empty means none. */
    efforts: string[];
};

/** A tool the server advertised that the agent cannot call, and why. */
export type NovaMcpSkippedTool = { tool: string; reason: string };

/** Branch and changed files of a session workspace. */
export type NovaGitStatus = {
    branch: string;
    ahead: number;
    behind: number;
    files: { path: string; status: string; staged: boolean }[];
};

/** A unified diff, already truncated by the backend when it is huge. */
export type NovaGitDiff = {
    diff: string;
    truncated: boolean;
};

/** The files a commit would include, plus the message the model proposed. */
export type NovaCommitPlan = {
    files: { path: string; status: string; staged: boolean }[];
    message: string;
    truncated: boolean;
};

export type NovaCommitResult = {
    commit: string;
    message: string;
    files: number;
};

export type NovaReviewResult = {
    review: string;
    truncated: boolean;
};

/** One configured MCP server. Credential values are never sent, only their keys. */
export type NovaMcpServer = {
    name: string;
    transport: string;
    command: string;
    args: string[];
    url: string;
    env_keys: string[];
    header_keys: string[];
    /** Null until a toolset was built: "not loaded yet" is not "offers nothing". */
    loaded_tools: string[] | null;
    skipped_tools: NovaMcpSkippedTool[] | null;
    error: string | null;
};

/** One stored memory. */
export type NovaMemory = {
    id: string;
    key: string;
    scope: string;
    memory_type: string;
    summary: string;
    content: string;
    tags: string[];
    session_id: string | null;
    created_at: number;
    updated_at: number;
};

/** One background task owned by a session. */
export type NovaTask = {
    task_id: string;
    kind: string;
    session_id: string;
    label: string;
    status: string;
    background: boolean;
    created_at_ms: number;
    started_at_ms: number | null;
    finished_at_ms: number | null;
    timeout_seconds: number | null;
    exit_code: number | null;
    output_bytes: number;
    output_truncated: boolean;
    result: string;
    error: string | null;
    progress: number | null;
    progress_message: string | null;
    last_activity_at_ms: number | null;
    /** Only the list endpoint fills this (a 1200-char tail). */
    output_preview?: string;
    metadata: Record<string, unknown>;
};

/** One turn whose files can be put back. */
export type NovaCheckpoint = {
    checkpoint_id: string;
    label: string;
    created_at: number;
    files: number;
    skipped: number;
};

export type NovaRestoreReport = {
    restored: string[];
    deleted: string[];
    skipped: { path: string; reason: string }[];
    dropped_messages: number;
    chat_truncated: boolean;
};

/** The permission policy configured on the backend (read-only). */export type NovaPermissionPolicy = {
    mode: string;
    path: string;
    /** False when no permissions file exists yet (built-in defaults apply). */
    configured: boolean;
    block_reads_outside_workspace: boolean;
    shell_allow: string[];
    shell_ask: { description: string; match: string }[];
    shell_disable: string[];
    tools: { name: string; effect: string }[];
};

export type NovaProviderRecord = {    key: string;
    name: string;
    type: string;
};

export type NovaAgentRecord = {
    key: string;
    name: string;
    description: string;
    model: string;
    provider: string;
    provider_name?: string;
    model_name?: string;
    tools: string | null;
    workspace_dir: string | null;
    mode?: "primary" | "subagent";
    kind?: "main" | "sub";
    /** Agents this one may be delegated to by; absent on older payloads. */
    parents?: string[];
    created_at: number;
    updated_at: number;
};

export type NovaAgentCreateRequest = {
    key: string;
    name: string;
    description?: string;
    model?: string;
    provider?: string;
    tools?: string[];
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
    data?: NovaJsonObject;
    delta?: string;
    errorText?: string;
    toolCallId?: string;
    toolName?: string;
    input?: NovaJsonObject;
    output?: NovaJsonValue;
    elapsedMs?: number;
};
