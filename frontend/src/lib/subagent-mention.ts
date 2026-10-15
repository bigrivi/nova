import type { NovaAgent } from "../types/nova";

/** A live `@` token under the caret: the substring after `@`, and its index. */
export type Mention = {
    query: string;
    start: number;
};

/**
 * The `@` mention the caret currently sits in, or null.
 *
 * The `@` must start the text or follow whitespace, and the text between it and
 * the caret must have no whitespace — so `a@b` is an email, not a mention.
 */
export function detectMention(text: string, caret: number): Mention | null {
    const start = text.lastIndexOf("@", caret - 1);
    if (start === -1 || caret <= start) {
        return null;
    }
    if (start > 0 && !/\s/.test(text[start - 1])) {
        return null;
    }
    const query = text.slice(start + 1, caret);
    if (/\s/.test(query)) {
        return null;
    }
    return { query, start };
}

/** Replace `mention` up to the caret with `@key` plus a trailing space. */
export function applyMention(
    text: string,
    mention: Mention,
    key: string,
): { text: string; caret: number } {
    const end = mention.start + 1 + mention.query.length;
    // Keep an existing separator instead of doubling the trailing space.
    const token = /^\s/.test(text.slice(end)) ? `@${key}` : `@${key} `;
    return {
        text: `${text.slice(0, mention.start)}${token}${text.slice(end)}`,
        caret: mention.start + token.length,
    };
}

function isSubagent(agent: NovaAgent): boolean {
    return agent.mode != null ? agent.mode === "subagent" : agent.kind === "sub";
}

/** Direct sub-agents of the active main agent; empty when there is none. */
export function selectableSubagents(
    agents: NovaAgent[],
    mainAgentKey: string | null,
): NovaAgent[] {
    if (!mainAgentKey) {
        return [];
    }
    return agents.filter(
        (agent) => isSubagent(agent) && agent.parents.includes(mainAgentKey),
    );
}

/** Case-insensitive match on name, key or description; blank query keeps all. */
export function filterSubagentsByQuery(
    list: NovaAgent[],
    query: string,
): NovaAgent[] {
    const needle = query.trim().toLowerCase();
    if (!needle) {
        return list;
    }
    return list.filter((agent) =>
        [agent.name, agent.key, agent.description ?? ""].some((field) =>
            field.toLowerCase().includes(needle),
        ),
    );
}
