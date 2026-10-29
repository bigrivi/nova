import { afterEach, describe, expect, test } from "bun:test";
import {
    createAgent,
    deleteAgent,
    getSessionContext,
    interruptChat,
    listAgents,
    listCheckpoints,
    listModels,
    listProviders,
    listSessions,
    restoreCheckpoint,
    streamChat,
    updateAgent,
} from "./nova-api.ts";

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

describe("nova-api", () => {
    test("listModels unwraps items", async () => {
        mockFetch(() => jsonResponse({ items: [{ id: "m1" }] }));
        expect(await listModels()).toEqual([{ id: "m1" }] as never);
        expect(calls[0]?.url).toEndWith("/api/models");
    });

    test("listProviders unwraps items", async () => {
        mockFetch(() => jsonResponse({ items: [{ key: "p" }] }));
        expect(await listProviders()).toEqual([{ key: "p" }] as never);
    });

    test("listSessions encodes the workspace query", async () => {
        mockFetch(() => jsonResponse({ items: [] }));
        await listSessions({ workspaceDir: "/tmp/a b" });
        expect(calls[0]?.url).toContain(
            "/api/sessions?workspace_dir=%2Ftmp%2Fa%20b",
        );
    });

    test("listAgents unwraps items", async () => {
        mockFetch(() => jsonResponse({ items: [{ key: "main" }] }));
        expect(await listAgents()).toEqual([{ key: "main" }] as never);
    });

    test("createAgent posts JSON and returns the record", async () => {
        mockFetch(() => jsonResponse({ key: "plan", name: "Plan" }));
        const created = await createAgent({
            key: "plan",
            name: "Plan",
        } as never);
        expect(created).toEqual({ key: "plan", name: "Plan" } as never);
        expect(calls[0]?.init?.method).toBe("POST");
        expect(calls[0]?.init?.body).toBe(
            JSON.stringify({ key: "plan", name: "Plan" }),
        );
        const headers = calls[0]?.init?.headers as Record<string, string>;
        expect(headers["Content-Type"]).toBe("application/json");
    });

    test("updateAgent sends PATCH", async () => {
        mockFetch(() => jsonResponse({}));
        await updateAgent("main", { provider: "p", model: "m" });
        expect(calls[0]?.url).toEndWith("/api/agents/main");
        expect(calls[0]?.init?.method).toBe("PATCH");
        expect(calls[0]?.init?.body).toBe(
            JSON.stringify({ provider: "p", model: "m" }),
        );
    });

    test("deleteAgent sends DELETE", async () => {
        mockFetch(() => jsonResponse({}));
        await deleteAgent("plan");
        expect(calls[0]?.url).toEndWith("/api/agents/plan");
        expect(calls[0]?.init?.method).toBe("DELETE");
    });

    test("listCheckpoints unwraps items", async () => {
        mockFetch(() =>
            jsonResponse({ items: [{ checkpoint_id: "m1", files: 2 }] }),
        );

        expect(await listCheckpoints("s1")).toEqual([
            { checkpoint_id: "m1", files: 2 },
        ] as never);
        expect(calls[0]?.url).toEndWith("/api/sessions/s1/checkpoints");
    });

    test("restoreCheckpoint posts to the checkpoint route", async () => {
        mockFetch(() => jsonResponse({ restored: ["a"], dropped_messages: 3 }));

        const report = await restoreCheckpoint("s1", "m1");

        expect(report.dropped_messages).toBe(3);
        expect(calls[0]?.url).toEndWith(
            "/api/sessions/s1/checkpoints/m1/restore",
        );
        expect(calls[0]?.init?.method).toBe("POST");
    });

    test("getSessionContext parses the body", async () => {        mockFetch(() =>
            jsonResponse({ used: 1, limit: 2, percent: 50, message_count: 3 }),
        );
        expect(await getSessionContext("s1")).toEqual({
            used: 1,
            limit: 2,
            percent: 50,
            message_count: 3,
        } as never);
    });

    test("non-2xx raises the backend detail", async () => {
        mockFetch(() => jsonResponse({ detail: "boom" }, 400));
        await expect(listModels()).rejects.toThrow("boom");
    });

    test("non-2xx without JSON falls back to the status", async () => {
        mockFetch(() => new Response("", { status: 500 }));
        await expect(listModels()).rejects.toThrow("Request failed with status 500");
    });

    test("interruptChat returns true when the server confirms", async () => {
        mockFetch(() => jsonResponse({ session_id: "s1", interrupted: true }));
        expect(await interruptChat("s1")).toBe(true);
        expect(calls[0]?.url).toEndWith("/api/chat/interrupt");
        expect(calls[0]?.init?.method).toBe("POST");
    });

    test("interruptChat returns false when nothing was live", async () => {
        mockFetch(() => jsonResponse({ session_id: "s1", interrupted: false }));
        expect(await interruptChat("s1")).toBe(false);
    });

    test("interruptChat returns null on non-2xx", async () => {
        mockFetch(() => new Response("err", { status: 500 }));
        expect(await interruptChat("s1")).toBeNull();
    });

    test("interruptChat returns null on network error", async () => {
        globalThis.fetch = (() =>
            Promise.reject(new Error("down"))) as unknown as typeof fetch;
        expect(await interruptChat("s1")).toBeNull();
    });

    test("interruptChat returns null on non-JSON body", async () => {
        mockFetch(() => new Response("not json", { status: 200 }));
        expect(await interruptChat("s1")).toBeNull();
    });

    test("streamChat emits one event per SSE frame", async () => {
        const frames = [
            `data: ${JSON.stringify({ type: "text-delta", delta: "a" })}\n\n`,
            `data: ${JSON.stringify({ type: "text-delta", delta: "b" })}\n\n`,
            "data: [DONE]\n\n",
        ];
        const stream = new ReadableStream<Uint8Array>({
            start(controller) {
                const encoder = new TextEncoder();
                for (const frame of frames) {
                    controller.enqueue(encoder.encode(frame));
                }
                controller.close();
            },
        });
        mockFetch(() => new Response(stream, { status: 200 }));

        const received: unknown[] = [];
        await streamChat({
            message: "hi",
            agentKey: "plan",
            reasoningEffort: "high",
            permissionMode: "acceptEdits",
            onEvent: (event) => received.push(event),
        });

        expect(received).toEqual([
            { type: "text-delta", delta: "a" },
            { type: "text-delta", delta: "b" },
        ] as never);
        const body = JSON.parse(String(calls[0]?.init?.body)) as Record<
            string,
            unknown
        >;
        expect(body.agent_key).toBe("plan");
        expect(body.reasoning_effort).toBe("high");
        // The mode has to reach the backend per turn: the agent cache is keyed
        // on it, which is what makes Shift+Tab take effect without a restart.
        expect(body.permission_mode).toBe("acceptEdits");
        expect(body.message).toBe("hi");
    });
});
