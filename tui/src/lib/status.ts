/** Derive the status bar's single status value from the stores that know it. */
export type AgentStatus = "idle" | "running" | "waiting" | "error";

export type StatusInput = {
    isStreaming: boolean;
    /** A shell/tool approval dialog is open. */
    hasApproval: boolean;
    /** An ask_user form is open. */
    hasQuestion: boolean;
    /** Status of the most recent assistant message, if there is one. */
    lastAssistantStatus?: "streaming" | "done" | "error";
};

/**
 * One status for the dot, in priority order: waiting on the user, then work in
 * flight, then the last turn's failure, then idle.
 */
export function deriveAgentStatus(input: StatusInput): AgentStatus {
    if (input.hasApproval || input.hasQuestion) return "waiting";
    if (input.isStreaming) return "running";
    if (input.lastAssistantStatus === "error") return "error";
    return "idle";
}

export type StatusMessage = {
    role: string;
    status: "streaming" | "done" | "error";
};

/** Status of the most recent assistant message, if any. */
export function lastAssistantStatus(
    messages: readonly StatusMessage[],
): StatusMessage["status"] | undefined {
    for (let index = messages.length - 1; index >= 0; index--) {
        const message = messages[index]!;
        if (message.role === "assistant") return message.status;
    }
    return undefined;
}
