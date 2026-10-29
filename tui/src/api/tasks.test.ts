import { afterEach, describe, expect, test } from "bun:test";
import { cancelTask, getTaskLogs, listTasks } from "./tasks.ts";

type Call = { url: string; init?: RequestInit };

const originalFetch = globalThis.fetch;
let calls: Call[] = [];

function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
    });
}

function mockFetch(handler: (call: Call) => Response): void {
    globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
        const call = { url: String(input), init };
        calls.push(call);
        return Promise.resolve(handler(call));
    }) as typeof fetch;
}

afterEach(() => {
    globalThis.fetch = originalFetch;
    calls = [];
});

describe("tasks api", () => {
    test("listTasks scopes the query to the session", async () => {
        mockFetch(() => jsonResponse({ items: [{ task_id: "t1" }] }));

        expect(await listTasks("s 1")).toEqual([{ task_id: "t1" }] as never);
        expect(calls[0]?.url).toEndWith("/api/tasks?session_id=s%201");
    });

    test("getTaskLogs returns the output tail", async () => {
        mockFetch(() => jsonResponse({ task_id: "t1", output: "line" }));

        expect(await getTaskLogs("t1", "s1")).toBe("line");
        expect(calls[0]?.url).toEndWith("/api/tasks/t1/logs?session_id=s1");
    });

    test("cancelTask posts the session in the body", async () => {
        mockFetch(() => jsonResponse({ task_id: "t1", status: "cancelled" }));

        await cancelTask("t1", "s1");

        expect(calls[0]?.url).toEndWith("/api/tasks/t1/cancel");
        expect(calls[0]?.init?.method).toBe("POST");
        expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
            session_id: "s1",
        });
    });

    test("surfaces the backend's error text", async () => {
        mockFetch(() =>
            jsonResponse({ detail: "Background task not found" }, 404),
        );

        await expect(cancelTask("t1", "s1")).rejects.toThrow(
            "Background task not found",
        );
    });
});
