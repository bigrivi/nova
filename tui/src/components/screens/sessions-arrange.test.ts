import { describe, expect, test } from "bun:test";
import {
    arrangeSessions,
    pendingMark,
    type SessionListEntry,
} from "./SessionsScreen.tsx";

function session(
    id: string,
    overrides: Partial<SessionListEntry> = {},
): SessionListEntry {
    return {
        id,
        title: id,
        updated_at: 1_000,
        agent_key: "main",
        forked_from: null,
        ...overrides,
    };
}

describe("arrangeSessions", () => {
    test("keeps a plain list unchanged", () => {
        const rows = arrangeSessions([session("b"), session("a")]);
        expect(rows.map((row) => row.id)).toEqual(["b", "a"]);
        expect(rows.every((row) => row.group === undefined)).toBe(true);
    });

    test("nests a fork under its origin with a header", () => {
        const rows = arrangeSessions([
            session("origin", { title: "fix login" }),
            session("copy", { title: "fix login (fork)", forked_from: "origin" }),
        ]);

        expect(rows.map((row) => row.id)).toEqual(["origin", "copy"]);
        expect(rows[1]?.group).toBe("from fix login");
        expect(rows[1]?.isFork).toBe(true);
    });

    test("does not repeat a fork at the top level", () => {
        const rows = arrangeSessions([
            session("copy", { forked_from: "origin" }),
            session("origin"),
        ]);

        expect(rows.filter((row) => row.id === "copy")).toHaveLength(1);
    });

    test("lists a fork whose origin is outside this folder, without a header", () => {
        const rows = arrangeSessions([session("copy", { forked_from: "elsewhere" })]);

        // Hiding a session because its parent was filtered out would be worse
        // than showing it flat.
        expect(rows).toHaveLength(1);
        expect(rows[0]?.id).toBe("copy");
        expect(rows[0]?.group).toBeUndefined();
    });

    test("groups several forks under one origin", () => {
        const rows = arrangeSessions([
            session("origin"),
            session("copy-a", { forked_from: "origin" }),
            session("copy-b", { forked_from: "origin" }),
            session("other"),
        ]);

        expect(rows.map((row) => [row.id, row.group ?? null])).toEqual([
            ["origin", null],
            ["copy-a", "from origin"],
            ["copy-b", "from origin"],
            ["other", null],
        ]);
    });

    test("a pending session sorts first, ties keep server order", () => {
        const rows = arrangeSessions([
            session("old", { updated_at: 2_000 }),
            session("waiting", { updated_at: 1_000, pending: "approval" }),
            session("question", { updated_at: 500, pending: "question" }),
            session("newest", { updated_at: 3_000 }),
        ]);

        expect(rows.map((row) => row.id)).toEqual([
            "waiting",
            "question",
            "newest",
            "old",
        ]);
        expect(rows[0]?.pending).toBe("approval");
        expect(pendingMark("approval")).toBe("! ");
        expect(pendingMark("question")).toBe("? ");
        expect(pendingMark(null)).toBe("");
    });
});
