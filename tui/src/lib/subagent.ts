/** Parse the header the backend writes for a server-injected sub-agent report. */
export type SubagentStatus = "done" | "error";

export type SubagentNotice = {
    target: string;
    status: SubagentStatus;
};

const HEADER = /^\[subagent:(.+?)\s+status=(done|error)\]\s*\n?/;

/**
 * Read the sub-agent header, ignoring the body.
 *
 * This only parses; whether a message *is* a sub-agent notice is decided by the
 * server-set `variant`, so text a user pasted cannot be mistaken for one.
 */
export function parseSubagentNotice(text: string): SubagentNotice | null {
    const match = HEADER.exec(text);
    if (!match) return null;
    const target = match[1]?.trim() ?? "";
    if (!target) return null;
    return { target, status: match[2] === "error" ? "error" : "done" };
}
