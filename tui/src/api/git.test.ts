import { afterEach, describe, expect, test } from "bun:test";
import { commitChanges, planCommit, reviewChanges } from "./git.ts";

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

describe("git api", () => {
    test("planCommit asks for the plan of one session", async () => {
        mockFetch(() =>
            jsonResponse({
                files: [{ path: "a.txt", status: "M", staged: false }],
                message: "fix: a",
                truncated: false,
            }),
        );

        const plan = await planCommit("s1");

        expect(plan.message).toBe("fix: a");
        expect(calls[0]?.url).toEndWith("/api/git/commit-plan?session_id=s1");
    });

    test("commitChanges posts exactly the confirmed paths", async () => {
        mockFetch(() =>
            jsonResponse({ commit: "abc1234", message: "fix: a", files: 1 }),
        );

        const result = await commitChanges("s1", "fix: a", ["a.txt"]);

        expect(result.commit).toBe("abc1234");
        expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
            session_id: "s1",
            message: "fix: a",
            paths: ["a.txt"],
        });
    });

    test("commitChanges surfaces a refusal instead of pretending it worked", async () => {
        mockFetch(() => jsonResponse({ detail: "nothing to commit" }, 409));

        await expect(commitChanges("s1", "fix: a", ["a.txt"])).rejects.toThrow(
            "nothing to commit",
        );
    });

    test("reviewChanges returns the review text", async () => {
        mockFetch(() =>
            jsonResponse({ review: "a.txt:1 — bug — why", truncated: false }),
        );

        const result = await reviewChanges("s1");

        expect(result.review).toContain("bug");
        expect(calls[0]?.url).toEndWith("/api/git/review");
        expect(calls[0]?.init?.method).toBe("POST");
    });
});
