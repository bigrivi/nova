import { describe, expect, it } from "vitest";

import type { NovaAgent } from "../types/nova";
import {
    applyMention,
    detectMention,
    filterSubagentsByQuery,
    selectableSubagents,
} from "./subagent-mention";

function agent(
    key: string,
    overrides: Partial<NovaAgent> = {},
): NovaAgent {
    return {
        key,
        name: key,
        description: "",
        model: "m",
        provider: "p",
        parents: [],
        created_at: 0,
        updated_at: 0,
        kind: "main",
        mode: "primary",
        editable_fields: [],
        ...overrides,
    };
}

describe("detectMention", () => {
    it("opens an empty mention right after `@` at the start", () => {
        expect(detectMention("@", 1)).toEqual({ query: "", start: 0 });
    });

    it("opens a mention after whitespace", () => {
        expect(detectMention("hello @", 7)).toEqual({ query: "", start: 6 });
        expect(detectMention("hello @co", 9)).toEqual({ query: "co", start: 6 });
    });

    it("ignores an email-like `a@b`", () => {
        expect(detectMention("a@b", 3)).toBeNull();
    });

    it("closes once the query has whitespace", () => {
        expect(detectMention("hello @co there", 15)).toBeNull();
    });

    it("returns null when there is no `@` or the caret is before it", () => {
        expect(detectMention("hello", 5)).toBeNull();
        expect(detectMention("@abc", 0)).toBeNull();
    });
});

describe("applyMention", () => {
    it("replaces the typed token with `@key` and a trailing space", () => {
        const mention = detectMention("hi @co", 6);
        expect(mention).not.toBeNull();
        expect(applyMention("hi @co", mention!, "coder")).toEqual({
            text: "hi @coder ",
            caret: 10,
        });
    });

    it("keeps the existing separator when one is already present", () => {
        const mention = detectMention("hi @co there", 6);
        expect(mention).not.toBeNull();
        expect(applyMention("hi @co there", mention!, "coder")).toEqual({
            text: "hi @coder there",
            caret: 9,
        });
    });

    it("replaces only the token when text follows", () => {
        const mention = detectMention("@co|x", 3);
        expect(mention).not.toBeNull();
        expect(applyMention("@co|x", mention!, "coder")).toEqual({
            text: "@coder |x",
            caret: 7,
        });
    });
});

describe("selectableSubagents", () => {
    it("keeps only the active main agent's direct children", () => {
        const agents = [
            agent("nova"),
            agent("coder", { kind: "sub", mode: "subagent", parents: ["nova"] }),
            agent("writer", {
                kind: "sub",
                mode: "subagent",
                parents: ["other"],
            }),
        ];
        expect(selectableSubagents(agents, "nova").map((a) => a.key)).toEqual([
            "coder",
        ]);
    });

    it("falls back to kind when mode is absent", () => {
        const agents = [
            agent("legacy", {
                kind: "sub",
                mode: undefined,
                parents: ["nova"],
            }),
        ];
        expect(selectableSubagents(agents, "nova")).toHaveLength(1);
    });

    it("returns nothing without an active main agent", () => {
        const agents = [
            agent("coder", { kind: "sub", mode: "subagent", parents: ["nova"] }),
        ];
        expect(selectableSubagents(agents, null)).toEqual([]);
    });
});

describe("filterSubagentsByQuery", () => {
    const list = [
        agent("coder", { name: "Coder", description: "writes code" }),
        agent("writer", { name: "Writer", description: "docs" }),
    ];

    it("matches on name, key or description, case-insensitively", () => {
        expect(filterSubagentsByQuery(list, "COD").map((a) => a.key)).toEqual([
            "coder",
        ]);
        expect(filterSubagentsByQuery(list, "docs").map((a) => a.key)).toEqual([
            "writer",
        ]);
    });

    it("keeps everything for a blank query", () => {
        expect(filterSubagentsByQuery(list, "  ")).toHaveLength(2);
    });

    it("returns no matches when nothing fits", () => {
        expect(filterSubagentsByQuery(list, "nope")).toEqual([]);
    });
});
