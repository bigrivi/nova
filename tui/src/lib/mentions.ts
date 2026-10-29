/** `@` candidates: sub-agents first, then directories, then files.
 *
 *  Kept free of React and of the filesystem so the ordering can be asserted
 *  directly — "agents before files" is the rule a user notices first, and the
 *  one that is easiest to lose in a refactor.
 */
import type { NovaAgentRecord } from "../api/types.ts";
import type { FileCandidate } from "./file-completion.ts";

export type MentionKind = "agent" | "dir" | "file";

export type MentionCandidate = {
    kind: MentionKind;
    /** Text inserted after the `@`; agents get their key, paths keep their form. */
    insert: string;
    /** Row text. */
    label: string;
    /** Right-hand hint: what this candidate is. */
    hint: string;
    /** Stable identity for list keys. */
    value: string;
};

/** Sub-agents the active agent may delegate to. */
export function selectableSubagents(
    agents: NovaAgentRecord[],
    activeAgentKey: string,
): NovaAgentRecord[] {
    const subagents = agents.filter(
        (agent) => (agent.mode ?? "primary") === "subagent",
    );
    // `parents` is optional in an older payload; without it every sub-agent is
    // offered rather than none, because an empty menu is the worse failure.
    const withParents = subagents.filter(
        (agent) => !agent.parents || agent.parents.includes(activeAgentKey),
    );
    return withParents.sort((left, right) => left.key.localeCompare(right.key));
}

export type AgentMatch = {
    agent: NovaAgentRecord;
    /** 0 = key or name starts with the query, 1 = contains it, 2 = only the
     *  description does. The last group is weak enough to sit below files. */
    rank: number;
};

/** Case-insensitive match on name, key or description; a blank query keeps all. */
export function matchSubagents(
    agents: NovaAgentRecord[],
    query: string,
): AgentMatch[] {
    const needle = query.trim().toLowerCase();
    if (!needle) return agents.map((agent) => ({ agent, rank: 0 }));
    const matches: AgentMatch[] = [];
    for (const agent of agents) {
        const names = [agent.key.toLowerCase(), (agent.name ?? "").toLowerCase()];
        if (names.some((name) => name.startsWith(needle))) {
            matches.push({ agent, rank: 0 });
        } else if (names.some((name) => name.includes(needle))) {
            matches.push({ agent, rank: 1 });
        } else if ((agent.description ?? "").toLowerCase().includes(needle)) {
            matches.push({ agent, rank: 2 });
        }
    }
    return matches;
}

/** Compatibility helper: the agents, best match first. */
export function filterSubagents(
    agents: NovaAgentRecord[],
    query: string,
): NovaAgentRecord[] {
    return matchSubagents(agents, query)
        .sort((left, right) => left.rank - right.rank)
        .map((match) => match.agent);
}

/**
 * Agents first, then directories, then files.
 *
 * Two exceptions keep the file half reachable. A query containing `/` is a path,
 * so no agent is offered; and an agent matched only by its description ranks
 * below files, because long descriptions otherwise match every letter and push
 * `src/` off the menu.
 */
export function buildMentionCandidates(
    agents: NovaAgentRecord[],
    paths: FileCandidate[],
    query: string,
    limit = 20,
): MentionCandidate[] {
    const matches = query.includes("/") ? [] : matchSubagents(agents, query);
    const strong = matches.filter((match) => match.rank < 2);
    const weak = matches.filter((match) => match.rank === 2);
    const agentRows = strong.map(({ agent }) => ({
        kind: "agent" as const,
        insert: agent.key,
        label: `@${agent.key}  ${agent.name}`,
        hint: "agent",
        value: `agent:${agent.key}`,
    }));
    const weakAgentRows = weak.map(({ agent }) => ({
        kind: "agent" as const,
        insert: agent.key,
        label: `@${agent.key}  ${agent.name}`,
        hint: "agent",
        value: `agent:${agent.key}`,
    }));
    const dirRows = paths
        .filter((entry) => entry.isDir)
        .map((entry) => ({
            kind: "dir" as const,
            insert: entry.insert,
            label: `@${entry.insert}`,
            hint: "dir",
            value: `dir:${entry.insert}`,
        }));
    const fileRows = paths
        .filter((entry) => !entry.isDir)
        .map((entry) => ({
            kind: "file" as const,
            insert: entry.insert,
            label: `@${entry.insert}`,
            hint: "file",
            value: `file:${entry.insert}`,
        }));
    return [...agentRows, ...dirRows, ...fileRows, ...weakAgentRows].slice(
        0,
        limit,
    );
}

/** The replacement text for one candidate: agents never end in `/`. */
export function mentionText(candidate: MentionCandidate): string {
    return `@${candidate.insert}${candidate.kind === "dir" ? "" : " "}`;
}
