import { describe, expect, test } from "bun:test";

import {
    buildTimelineItems,
    chainStats,
    contextRingRatio,
    contextRingWarns,
    formatDuration,
    formatTokenCount,
    parseAttachment,
    parseSubagentMessage,
    toolParamSummary,
    type TimelinePart,
} from "./presentation";
import { chatMetrics, themes } from "../theme/tokens";

function reasoning(ms?: number): TimelinePart {
    return { type: "reasoning", text: "thinking", elapsedMs: ms ?? null };
}

function tool(name = "read", extra: Partial<TimelinePart> = {}): TimelinePart {
    return { type: "tool-call", toolName: name, ...extra };
}

function text(value: string): TimelinePart {
    return { type: "text", text: value };
}

describe("timeline items", () => {
    test("reply text is its own row", () => {
        expect(buildTimelineItems([text("answer")])).toEqual([
            { kind: "text", index: 0 },
        ]);
    });

    test("reasoning and tools collapse into one chain before the answer", () => {
        const parts = [reasoning(1200), tool("read"), text("answer")];
        expect(buildTimelineItems(parts)).toEqual([
            {
                kind: "chain",
                indices: [0, 1],
                toolCount: 1,
                elapsedMs: 1200,
            },
            { kind: "text", index: 2 },
        ]);
    });

    test("a tool call without thinking is a standalone card", () => {
        const parts = [tool("shell"), text("done")];
        expect(buildTimelineItems(parts)).toEqual([
            { kind: "tool", index: 0 },
            { kind: "text", index: 1 },
        ]);
    });

    test("a standalone tool splits the chain", () => {
        const parts = [
            reasoning(500),
            tool("browser_use", { standalone: true }),
            reasoning(700),
            text("answer"),
        ];
        expect(buildTimelineItems(parts)).toEqual([
            { kind: "chain", indices: [0], toolCount: 0, elapsedMs: 500 },
            { kind: "tool", index: 1 },
            { kind: "chain", indices: [2], toolCount: 0, elapsedMs: 700 },
            { kind: "text", index: 3 },
        ]);
    });

    test("an MCP app tool is standalone even without a flag", () => {
        const parts = [
            reasoning(100),
            tool("mcp__ui", {
                mcp: { app: { resourceUri: "ui://server/view" } },
            }),
            text("answer"),
        ];
        expect(buildTimelineItems(parts)).toEqual([
            { kind: "chain", indices: [0], toolCount: 0, elapsedMs: 100 },
            { kind: "tool", index: 1 },
            { kind: "text", index: 2 },
        ]);
    });

    test("ask_user and todo_write never become timeline rows", () => {
        const parts = [reasoning(200), tool("ask_user"), text("answer")];
        expect(buildTimelineItems(parts)).toEqual([
            { kind: "chain", indices: [0], toolCount: 0, elapsedMs: 200 },
            { kind: "text", index: 2 },
        ]);
        expect(
            buildTimelineItems([tool("todo_write"), tool("ask_user")]),
        ).toEqual([]);
    });

    test("blank text inside thinking is a joiner, not a row", () => {
        const parts = [reasoning(100), text("   "), tool("grep")];
        expect(buildTimelineItems(parts)).toEqual([
            {
                kind: "chain",
                indices: [0, 2],
                toolCount: 1,
                elapsedMs: 100,
            },
        ]);
    });

    test("a second answer starts a new segment", () => {
        const parts = [
            reasoning(100),
            text("first"),
            tool("read"),
            text("second"),
        ];
        expect(buildTimelineItems(parts)).toEqual([
            { kind: "chain", indices: [0], toolCount: 0, elapsedMs: 100 },
            { kind: "text", index: 1 },
            { kind: "tool", index: 2 },
            { kind: "text", index: 3 },
        ]);
    });
});

describe("chain stats", () => {
    test("sums elapsed reasoning and counts only visible tools", () => {
        const parts = [
            reasoning(1000),
            tool("read"),
            tool("ask_user"),
            reasoning(500),
        ];
        expect(chainStats(parts, [0, 1, 2, 3])).toEqual({
            toolCount: 1,
            elapsedMs: 1500,
        });
    });

    test("returns null elapsed when no reasoning carried a time", () => {
        expect(chainStats([tool("read")], [0])).toEqual({
            toolCount: 1,
            elapsedMs: null,
        });
    });
});

describe("server text headers", () => {
    test("parses an attachment envelope", () => {
        expect(
            parseAttachment(
                "<attachment name=notes.md>\nhello\n</attachment>\n\nwhat is this?",
            ),
        ).toEqual({ name: "notes.md", text: "what is this?" });
    });

    test("ignores ordinary user text", () => {
        expect(parseAttachment("hello")).toBeNull();
    });

    test("parses sub-agent reports in both states", () => {
        expect(
            parseSubagentMessage("[subagent:research status=done]\n\nfound it"),
        ).toEqual({ target: "research", status: "done", body: "found it" });
        expect(
            parseSubagentMessage("[subagent:build status=error]\n\nfailed"),
        ).toEqual({ target: "build", status: "error", body: "failed" });
    });

    test("rejects an empty target and ordinary text", () => {
        expect(parseSubagentMessage("[subagent:  status=done]\nbody")).toBeNull();
        expect(parseSubagentMessage("hello")).toBeNull();
    });
});

describe("tool summary", () => {
    test("prefers the known path/query keys", () => {
        expect(
            toolParamSummary(
                JSON.stringify({ path: "/tmp/a", command: "ls", prompt: "x" }),
            ),
        ).toBe("/tmp/a");
    });

    test("falls back to the first string value", () => {
        expect(
            toolParamSummary(JSON.stringify({ other: 1, note: "hello" })),
        ).toBe("hello");
    });

    test("returns raw text for invalid JSON and null for empty", () => {
        expect(toolParamSummary("not json")).toBe("not json");
        expect(toolParamSummary("   ")).toBeNull();
    });
});

describe("composer numbers", () => {
    test("formats token counts", () => {
        expect(formatTokenCount(999)).toBe("999");
        expect(formatTokenCount(1500)).toBe("1.5K");
        expect(formatTokenCount(1_200_000)).toBe("1.2M");
    });

    test("clamps the ring ratio and warns at 85 percent", () => {
        expect(contextRingRatio(50, 100)).toBe(0.5);
        expect(contextRingRatio(200, 100)).toBe(1);
        expect(contextRingRatio(10, 0)).toBe(0);
        expect(contextRingWarns(84.9)).toBe(false);
        expect(contextRingWarns(85)).toBe(true);
    });

    test("formats reasoning duration", () => {
        expect(formatDuration(850)).toBe("850ms");
        expect(formatDuration(1200)).toBe("1.2s");
        expect(formatDuration(65_000)).toBe("1m 5s");
    });
});

describe("presentation tokens", () => {
    test("both themes define the same keys", () => {
        expect(Object.keys(themes.dark).sort()).toEqual(
            Object.keys(themes.light).sort(),
        );
    });

    test("colours are populated and dark drops the lift shadow", () => {
        for (const theme of Object.values(themes)) {
            for (const [key, value] of Object.entries(theme)) {
                if (typeof value === "string") {
                    expect(`${key}:${value.trim().length}`).not.toBe(`${key}:0`);
                }
            }
        }
        expect(themes.light.composerShadow).not.toBeNull();
        expect(themes.dark.composerShadow).toBeNull();
    });

    test("layout metrics are positive", () => {
        for (const value of Object.values(chatMetrics)) {
            expect(value).toBeGreaterThan(0);
        }
    });
});
