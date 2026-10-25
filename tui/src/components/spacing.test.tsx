/** Spacing contract: every node owns exactly one blank row above itself.
 *
 * Rendered through the real layout engine rather than asserted on JSX, so a
 * stray marginBottom stacking with the next node's marginTop shows up as a
 * double gap. Markdown part bodies are not painted by the test renderer, so the
 * assertions read the `●` bullets and plain-text rows (tool, reasoning, notice,
 * error) rather than body copy.
 */
import { beforeAll, describe, expect, mock, test } from "bun:test";
import { darkTheme } from "../themes/index.ts";
import type { TuiMessage } from "../stores/chat-store.ts";

mock.module("../context/theme.tsx", () => ({ useTheme: () => darkTheme }));

// The spacing contract is about boxes, not prose: a plain text node keeps the
// frame readable and avoids pulling real syntax highlighting into the test.
mock.module("./parts/MarkdownPart.tsx", () => ({
    MarkdownPart: ({ text }: { text: string }) => <text content={text} />,
    buildSyntaxStyles: () => ({}),
}));

const { testRender } = await import("@opentui/react/test-utils");
const { AssistantMessage } = await import("./AssistantMessage.tsx");
const { SubagentNotice } = await import("./SubagentNotice.tsx");
const { UserMessage } = await import("./UserMessage.tsx");

const WIDTH = 80;
const HEIGHT = 50;

function user(text: string, id: string): TuiMessage {
    return {
        id,
        role: "user",
        parts: [{ type: "text", text }],
        status: "done",
    };
}

function assistant(id: string, parts: TuiMessage["parts"], error?: string): TuiMessage {
    return {
        id,
        role: "assistant",
        parts,
        status: "done",
        ...(error ? { error } : {}),
    };
}

function shellTool(id: string, output: string): TuiMessage["parts"][number] {
    return {
        type: "tool-call",
        toolCallId: id,
        toolName: "shell",
        argsText: '{"command":"true"}',
        args: { command: "true" },
        outputText: output,
        status: "done",
    };
}

function indexOf(lines: string[], marker: string): number {
    const index = lines.findIndex((line) => line.includes(marker));
    if (index < 0) throw new Error(`marker not found in frame: ${marker}`);
    return index;
}

/** Blank rows directly above the row containing *marker*. */
function blanksAbove(lines: string[], marker: string): number {
    let count = 0;
    for (let i = indexOf(lines, marker) - 1; (lines[i] ?? "").trim() === "" && i >= 0; i--) {
        count++;
    }
    return count;
}

/** Blank rows directly below the row containing *marker*. */
function blanksBelow(lines: string[], marker: string): number {
    let count = 0;
    for (let i = indexOf(lines, marker) + 1; (lines[i] ?? "").trim() === "" && i < lines.length; i++) {
        count++;
    }
    return count;
}

/** Longest run of blank rows between the first and last content row. */
function longestBlankRun(lines: string[]): number {
    const first = lines.findIndex((line) => line.trim() !== "");
    const last = lines.reduce((acc, line, i) => (line.trim() ? i : acc), -1);
    let longest = 0;
    let run = 0;
    for (let i = Math.max(first, 0); i <= last; i++) {
        if ((lines[i] ?? "").trim() === "") {
            run++;
            longest = Math.max(longest, run);
        } else {
            run = 0;
        }
    }
    return longest;
}

// One of each node boundary: user bubble → assistant, text → tool → text,
// text → reasoning, text → error, assistant → subagent notice → user bubble.
const fixture: TuiMessage[] = [
    user("USER-MARK", "u1"),
    assistant("a1", [
        { type: "text", text: "TEXT-ONE" },
        shellTool("t1", "TOOL-OUT"),
        { type: "text", text: "TEXT-TWO" },
    ]),
    assistant(
        "a2",
        [
            { type: "reasoning", text: "REASON-OUT", elapsedMs: 1200, completed: true },
            { type: "text", text: "TEXT-THREE" },
        ],
        "ERR-MARK",
    ),
    { ...user("[subagent:explorer status=done]\nbody", "n1"), variant: "subagent" },
    user("USER-TWO", "u2"),
];

let lines: string[] = [];
let setup: Awaited<ReturnType<typeof testRender>>;

beforeAll(async () => {
    setup = await testRender(
        <box flexDirection="column" width={WIDTH}>
            {fixture.map((message) =>
                message.role === "user" ? (
                    message.variant === "subagent" ? (
                        <SubagentNotice key={message.id} message={message} />
                    ) : (
                        <UserMessage key={message.id} message={message} />
                    )
                ) : (
                    <AssistantMessage key={message.id} message={message} />
                ),
            )}
        </box>,
        { width: WIDTH, height: HEIGHT },
    );
    await setup.flush();
    lines = setup.captureCharFrame().split("\n");
});

// No explicit teardown: unmounting through renderer.destroy() fires React
// updates outside act() and buries the result in warnings; the process exits
// with the test run.


describe("message spacing", () => {
    test("text before a tool block leaves one blank row", () => {
        expect(blanksAbove(lines, "✓ Ran")).toBe(1);
    });

    test("text after a tool block leaves one blank row", () => {
        expect(blanksBelow(lines, "TOOL-OUT")).toBe(1);
    });

    test("reasoning keeps one blank row above it", () => {
        expect(blanksAbove(lines, "Thought")).toBe(1);
    });

    test("the reasoning body keeps one blank row under its label", () => {
        expect(blanksAbove(lines, "REASON-OUT")).toBe(1);
    });

    test("an error line keeps one blank row above it", () => {
        expect(blanksAbove(lines, "ERR-MARK")).toBe(1);
    });

    test("a subagent notice keeps one blank row above and below it", () => {
        expect(blanksAbove(lines, "Subagent")).toBe(1);
        expect(blanksBelow(lines, "Subagent")).toBe(2); // notice margin + bubble padding
    });

    test("no two nodes stack their margins into a double gap", () => {
        // A user bubble adds one row of its own padding, so 2 is the ceiling;
        // 3 or more means two margins met.
        expect(longestBlankRun(lines)).toBeLessThanOrEqual(2);
    });
});
