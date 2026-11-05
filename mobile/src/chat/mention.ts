/** `@subagent` tokens in the composer, ported from the web mention helper. */
import type { NovaAgent } from "../api/types";

export type Mention = {
    query: string;
    start: number;
};

/** The live `@` token under the caret, or null for an email-like `a@b`. */
export function detectMention(text: string, caret: number): Mention | null {
    const start = text.lastIndexOf("@", caret - 1);
    if (start === -1 || caret <= start) {
        return null;
    }
    if (start > 0 && !/\s/.test(text[start - 1]!)) {
        return null;
    }
    const query = text.slice(start + 1, caret);
    if (/\s/.test(query)) {
        return null;
    }
    return { query, start };
}

/** Replace the mention with `@key` plus one trailing space. */
export function applyMention(
    text: string,
    mention: Mention,
    key: string,
): { text: string; caret: number } {
    const end = mention.start + 1 + mention.query.length;
    const token = /^\s/.test(text.slice(end)) ? `@${key}` : `@${key} `;
    return {
        text: `${text.slice(0, mention.start)}${token}${text.slice(end)}`,
        caret: mention.start + token.length,
    };
}

function isSubagent(agent: NovaAgent): boolean {
    return agent.mode != null ? agent.mode === "subagent" : agent.kind === "sub";
}

/** Direct sub-agents of the active main agent. */
export function selectableSubagents(
    agents: readonly NovaAgent[],
    mainAgentKey: string | null,
): NovaAgent[] {
    if (!mainAgentKey) {
        return [];
    }
    return agents.filter(
        (agent) =>
            isSubagent(agent) && (agent.parents ?? []).includes(mainAgentKey),
    );
}

/** Case-insensitive match on name, key or description; blank keeps all. */
export function filterSubagentsByQuery(
    agents: readonly NovaAgent[],
    query: string,
): NovaAgent[] {
    const needle = query.trim().toLowerCase();
    if (!needle) {
        return [...agents];
    }
    return agents.filter((agent) =>
        [agent.name, agent.key, agent.description ?? ""].some((field) =>
            field.toLowerCase().includes(needle),
        ),
    );
}
