/** Opening a conversation restores its route and agent, and writes nothing. */
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { getSessionRoute } from "../api/nova-api.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { openSession } from "./open-session.ts";

type Call = { url: string; init?: RequestInit };

const originalFetch = globalThis.fetch;
let calls: Call[] = [];

function json(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
    });
}

function stubFetch(routeStatus: number = 200): void {
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, init });
        if (url.endsWith("/messages")) {
            return json({ items: [] });
        }
        if (url.endsWith("/route")) {
            return routeStatus === 200
                ? json({
                      provider: "recorded-provider",
                      model: "recorded-model",
                      reasoning_effort: "high",
                  })
                : json({ detail: "not found" }, routeStatus);
        }
        if (url.includes("/api/agents/")) {
            return json({
                key: "coder",
                name: "Coder",
                model: "ignored",
                provider: "ignored",
            });
        }
        return json({}, 404);
    }) as typeof fetch;
}

function writesTo(path: string): Call[] {
    return calls.filter(
        (call) =>
            call.url.includes(path) &&
            (call.init?.method === "PATCH" ||
                call.init?.method === "PUT" ||
                call.init?.method === "POST"),
    );
}

beforeEach(() => {
    calls = [];
    useChatStore.setState({
        messages: [],
        sessionId: null,
        isStreaming: false,
        provider: "",
        model: "",
        reasoningEffort: "",
        agentKey: "main",
        agentName: "main",
    });
});

afterEach(() => {
    globalThis.fetch = originalFetch;
});

describe("openSession", () => {
    test("restores the recorded route and the conversation's agent", async () => {
        stubFetch();

        await openSession("s1", "coder");

        const state = useChatStore.getState();
        expect(state.sessionId).toBe("s1");
        expect(state.agentKey).toBe("coder");
        expect(state.agentName).toBe("Coder");
        expect(state.provider).toBe("recorded-provider");
        expect(state.model).toBe("recorded-model");
        expect(state.reasoningEffort).toBe("high");
    });

    test("writes nothing back to the catalog or the session row", async () => {
        stubFetch();

        await openSession("s1", "coder");

        expect(writesTo("/api/agents")).toEqual([]);
        expect(writesTo("/route")).toEqual([]);
    });

    test("a conversation without a recorded route keeps the current pick", async () => {
        stubFetch(404);
        useChatStore.setState({ provider: "keep", model: "keep-model" });

        await openSession("s1");

        const state = useChatStore.getState();
        expect(state.sessionId).toBe("s1");
        expect(state.provider).toBe("keep");
        expect(state.model).toBe("keep-model");
    });
});

describe("getSessionRoute", () => {
    test("returns null when the session has no route", async () => {
        stubFetch(404);
        expect(await getSessionRoute("s1")).toBeNull();
    });

    test("returns the recorded route", async () => {
        stubFetch();
        expect(await getSessionRoute("s1")).toEqual({
            provider: "recorded-provider",
            model: "recorded-model",
            reasoning_effort: "high",
        });
    });
});
