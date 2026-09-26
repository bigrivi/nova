import { describe, expect, it } from "vitest";

import type { NovaSessionSummary, NovaThreadSummary } from "../types/nova";
import {
    renameThreadTitle,
    toThreadSummary,
    toThreadTitle,
    upsertThread,
} from "./thread-summary";

function session(overrides: Partial<NovaSessionSummary> = {}): NovaSessionSummary {
    return {
        id: "s-1",
        title: "Session one",
        workspace_dir: null,
        pinned: false,
        updated_at: 1000,
        project_id: null,
        agent_key: "main",
        ...overrides,
    } as NovaSessionSummary;
}

function thread(id: string): NovaThreadSummary {
    return {
        id,
        title: id,
        status: "regular",
        workspace_dir: null,
        pinned: false,
        updated_at: 0,
        project_id: null,
        agent_key: "main",
    };
}

describe("toThreadTitle", () => {
    it("returns the trimmed title", () => {
        expect(toThreadTitle(session({ title: "  Hello  " }))).toBe("Hello");
    });

    it("falls back to a non-empty label for blank titles", () => {
        expect(toThreadTitle(session({ title: "" }))).toBeTruthy();
        expect(toThreadTitle(session({ title: "   " }))).toBeTruthy();
    });
});

describe("toThreadSummary", () => {
    it("projects a session onto a normalized thread summary", () => {
        const summary = toThreadSummary(
            session({
                id: "s-9",
                title: "Work",
                workspace_dir: "/tmp",
                pinned: true,
                updated_at: 42,
                project_id: "p-1",
                agent_key: "coder",
            }),
        );
        expect(summary).toEqual({
            id: "s-9",
            title: "Work",
            status: "regular",
            workspace_dir: "/tmp",
            pinned: true,
            updated_at: 42,
            project_id: "p-1",
            agent_key: "coder",
        });
    });

    it("defaults nullable fields and agent key", () => {
        const summary = toThreadSummary(
            session({ workspace_dir: undefined, pinned: undefined, project_id: undefined, agent_key: "" }),
        );
        expect(summary.workspace_dir).toBeNull();
        expect(summary.pinned).toBe(false);
        expect(summary.project_id).toBeNull();
        expect(summary.agent_key).toBe("main");
    });
});

describe("renameThreadTitle", () => {
    it("renames in place without reordering the list", () => {
        const threads = [thread("a"), thread("b"), thread("c")];
        const next = renameThreadTitle(threads, "b", "New name");
        expect(next.map((t) => t.id)).toEqual(["a", "b", "c"]);
        expect(next[1].title).toBe("New name");
        expect(threads[1].title).toBe("b");
    });

    it("returns the same array when nothing changes", () => {
        const threads = [thread("a")];
        expect(renameThreadTitle(threads, "a", "a")).toBe(threads);
        expect(renameThreadTitle(threads, "missing", "x")).toBe(threads);
    });
});

describe("upsertThread", () => {
    it("moves an existing thread to the head without duplicating", () => {
        const threads = [thread("a"), thread("b"), thread("c")];
        const next = upsertThread(threads, { ...thread("b"), title: "B2" });
        expect(next.map((t) => t.id)).toEqual(["b", "a", "c"]);
        expect(next[0].title).toBe("B2");
    });

    it("prepends a brand-new thread", () => {
        const threads = [thread("a")];
        const next = upsertThread(threads, thread("z"));
        expect(next.map((t) => t.id)).toEqual(["z", "a"]);
    });
});
