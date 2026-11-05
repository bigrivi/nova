import { describe, expect, test } from "bun:test";

import type { NovaAgent } from "../api/types";
import {
    applyMention,
    detectMention,
    filterSubagentsByQuery,
    selectableSubagents,
} from "./mention";

function agent(
    key: string,
    parents: string[],
    mode: "primary" | "subagent" = "subagent",
): NovaAgent {
    return {
        key,
        name: key.replace(/-/g, " "),
        description: "",
        model: "m",
        provider: "p",
        parents,
        kind: mode === "subagent" ? "sub" : "main",
        mode,
    };
}

describe("mentions", () => {
    test("detects a mention after whitespace only", () => {
        expect(detectMention("@re", 3)).toEqual({ query: "re", start: 0 });
        expect(detectMention("hi @re", 6)).toEqual({
            query: "re",
            start: 3,
        });
        expect(detectMention("a@b", 3)).toBeNull();
        expect(detectMention("hi @re more", 11)).toBeNull();
    });

    test("replaces the mention and keeps one trailing space", () => {
        const mention = detectMention("hi @re", 6)!;
        expect(applyMention("hi @re", mention, "research")).toEqual({
            text: "hi @research ",
            caret: 13,
        });
        expect(
            applyMention("hi @re next", mention, "research").text,
        ).toBe("hi @research next");
    });

    test("only direct subagents of the active main agent are selectable", () => {
        const agents = [
            agent("research", ["main"]),
            agent("other", ["main"]),
            agent("nested", ["research"]),
            agent("main", [], "primary"),
        ];
        expect(
            selectableSubagents(agents, "main").map((item) => item.key),
        ).toEqual(["research", "other"]);
        expect(selectableSubagents(agents, null)).toEqual([]);
    });

    test("filters by key, name or description", () => {
        const agents = [
            agent("research", ["main"]),
            agent("builder", ["main"]),
        ];
        expect(
            filterSubagentsByQuery(agents, "build").map((item) => item.key),
        ).toEqual(["builder"]);
        expect(filterSubagentsByQuery(agents, " ")).toHaveLength(2);
    });
});
