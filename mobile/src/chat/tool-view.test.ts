import { describe, expect, test } from "bun:test";

import type { ToolPart } from "../state/chat";
import {
    buildToolView,
    countDiffLines,
    parseToolInput,
    readBackgroundTaskId,
    readToolResult,
    splitMutationOutput,
} from "./tool-view";

function part(
    toolName: string,
    inputText = "",
    outputText = "",
    status: ToolPart["status"] = "done",
): ToolPart {
    return {
        type: "tool-call",
        toolCallId: "call_1",
        toolName,
        inputText,
        outputText,
        status,
    };
}

const EDIT_RESULT = JSON.stringify({
    content:
        "Changes applied to notes.md:\n\n--- notes.md\n+++ notes.md\n@@ -1,2 +1,3 @@\n context\n-old\n+new\n+extra\n",
});

describe("tool views", () => {
    test("edit renders a diff with a settled verb", () => {
        const view = buildToolView(
            part(
                "edit",
                JSON.stringify({ filePath: "/repo/docs/notes.md" }),
                EDIT_RESULT,
            ),
        );
        expect(view).toEqual({
            kind: "file-mutation",
            label: "Edited notes.md",
            path: "/repo/docs/notes.md",
            headline: "Changes applied to notes.md:",
            diff: "--- notes.md\n+++ notes.md\n@@ -1,2 +1,3 @@\n context\n-old\n+new\n+extra",
            plain: null,
        });
        if (view?.kind !== "file-mutation" || !view.diff) {
            throw new Error("expected a diff");
        }
        expect(countDiffLines(view.diff)).toEqual({ added: 2, removed: 1 });
    });

    test("a running edit keeps the progressive verb and shows no result", () => {
        const view = buildToolView(
            part(
                "edit",
                JSON.stringify({ filePath: "a/b.py" }),
                "",
                "running",
            ),
        );
        expect(view?.kind).toBe("file-mutation");
        if (view?.kind !== "file-mutation") {
            return;
        }
        expect(view.label).toBe("Editing b.py");
        expect(view.diff).toBeNull();
        expect(view.plain).toBeNull();
    });

    test("write without a diff falls back to plain text", () => {
        const view = buildToolView(
            part(
                "write",
                JSON.stringify({ filePath: "/repo/new.py" }),
                JSON.stringify({ content: "Created /repo/new.py (3 lines)" }),
            ),
        );
        if (view?.kind !== "file-mutation") {
            throw new Error("expected file mutation");
        }
        expect(view.label).toBe("Wrote new.py");
        expect(view.plain).toBe("Created /repo/new.py (3 lines)");
    });

    test("code_run reads code, description and a background task id", () => {
        const output = JSON.stringify({
            background_task: { task_id: "task_9", status: "running" },
            message: "Started.",
        });
        const view = buildToolView(
            part(
                "code_run",
                JSON.stringify({ code: "print(1)", description: "smoke" }),
                output,
                "running",
            ),
        );
        expect(view).toEqual({
            kind: "code-run",
            label: "code_run",
            summary: "smoke",
            code: "print(1)",
            description: "smoke",
            output: "Started.",
            backgroundTaskId: "task_9",
        });
    });

    test("delegate shows the target and collapses the task preview", () => {
        const view = buildToolView(
            part(
                "delegate_to_agent",
                JSON.stringify({ target: "research", task: "a\n\nb  c" }),
                JSON.stringify({
                    content: "Sub-agent 'research' started.",
                }),
            ),
        );
        expect(view).toEqual({
            kind: "delegate",
            label: "Delegated to research",
            task: "a b c",
            output: "Sub-agent 'research' started.",
        });
    });

    test("background task ids are readable from any tool result", () => {
        expect(
            readBackgroundTaskId(
                JSON.stringify({
                    background_task: { task_id: "task_9" },
                    message: "Started.",
                }),
            ),
        ).toBe("task_9");
        expect(readBackgroundTaskId('{"content":"plain"}')).toBeNull();
        expect(readBackgroundTaskId("")).toBeNull();
    });

    test("plain results and partial arguments are tolerated", () => {
        expect(readToolResult("done")).toEqual({ text: "done", raw: null });
        expect(parseToolInput('{"filePath": "/a')).toEqual({});
        expect(buildToolView(part("glob", "{}"))).toBeNull();
        expect(splitMutationOutput("no diff here")).toEqual({
            headline: "no diff here",
            diff: null,
        });
    });
});
