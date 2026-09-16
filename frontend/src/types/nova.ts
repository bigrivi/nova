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
};

export type NovaModelRecord = {
    id: string;
    provider: string;
    provider_name: string;
    model: string;
    label: string;
    tools: boolean;
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

export type NovaThreadSummary = {
    id: string;
    title: string;
    status: "regular";
    workspace_dir: string | null;
    pinned: boolean;
    updated_at: number;
    project_id: string | null;
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
