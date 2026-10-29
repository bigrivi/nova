import { afterEach, describe, expect, test } from "bun:test";
import { compactSession, forkSession } from "./session-actions.ts";

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

describe("compactSession", () => {
    test("posts to the session's compact route", async () => {
        mockFetch(() => jsonResponse({ compacted: true }));

        expect(await compactSession("s1")).toEqual({ compacted: true });
        expect(calls[0]?.url).toEndWith("/api/sessions/s1/compact");
        expect(calls[0]?.init?.method).toBe("POST");
    });

    test("passes a refusal through as an error", async () => {
        mockFetch(() =>
            jsonResponse({ detail: "Session s1 is running a turn" }, 409),
        );

        await expect(compactSession("s1")).rejects.toThrow("running a turn");
    });
});

describe("forkSession", () => {
    test("posts the cut point to the fork route", async () => {
        mockFetch(() =>
            jsonResponse({ session_id: "new", title: "origin (fork)", messages: 4 }),
        );

        const result = await forkSession("s1", "m2");

        expect(result.session_id).toBe("new");
        expect(calls[0]?.url).toEndWith("/api/sessions/s1/fork");
        expect(calls[0]?.init?.method).toBe("POST");
        expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
            message_id: "m2",
        });
    });

    test("omits the cut point when copying everything", async () => {
        mockFetch(() => jsonResponse({ session_id: "new", title: "t", messages: 1 }));

        await forkSession("s1");

        expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({});
    });
});
