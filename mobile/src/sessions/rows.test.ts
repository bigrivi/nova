import { describe, expect, test } from "bun:test";

import type { NovaProject, NovaSessionSummary } from "../api/types";
import { buildSessionRows } from "./rows";

const NOW = Date.now();

function session(
    id: string,
    overrides: Partial<NovaSessionSummary> = {},
): NovaSessionSummary {
    return {
        id,
        title: id,
        updated_at: NOW - 60_000,
        agent_key: "main",
        workspace_dir: null,
        pinned: false,
        project_id: null,
        ...overrides,
    };
}

function project(id: string, overrides: Partial<NovaProject> = {}): NovaProject {
    return {
        id,
        name: id,
        path: null,
        created_at: NOW,
        updated_at: NOW,
        ...overrides,
    };
}

describe("session rows", () => {
    test("pinned rows precede projects and date buckets", () => {
        const rows = buildSessionRows({
            items: [
                session("pinned", { pinned: true }),
                session("today"),
                session("old", { updated_at: NOW - 30 * 86_400_000 }),
            ],
            projects: [],
            expanded: new Set(),
            query: "",
        });

        expect(rows[0]).toMatchObject({ kind: "header", title: "Pinned" });
        expect(rows[1]).toMatchObject({ kind: "session", session: { id: "pinned" } });
        expect(rows.some((row) => row.kind === "project")).toBe(false);
        expect(
            rows.filter((row) => row.kind === "header").map((row) => row.title),
        ).toEqual(["Pinned", "Projects", "Chats", "Today", "Older"]);
    });

    test("projects expand, and empty projects say so when open", () => {
        const projects = [project("full"), project("empty")];
        const items = [session("inside", { project_id: "full" })];

        const collapsed = buildSessionRows({
            items,
            projects,
            expanded: new Set(),
            query: "",
        });
        expect(
            collapsed.some(
                (row) => row.kind === "session" && row.session.id === "inside",
            ),
        ).toBe(false);

        const open = buildSessionRows({
            items,
            projects,
            expanded: new Set(["full", "empty"]),
            query: "",
        });
        expect(
            open.some(
                (row) => row.kind === "session" && row.session.id === "inside",
            ),
        ).toBe(true);
        expect(
            open.some(
                (row) => row.kind === "project-empty" && row.project.id === "empty",
            ),
        ).toBe(true);
    });

    test("a search query flattens the list and reports the count", () => {
        const rows = buildSessionRows({
            items: [
                session("alpha", { title: "Alpha notes" }),
                session("beta", { title: "Beta notes" }),
                session("pinned", { title: "Alpha pinned", pinned: true }),
            ],
            projects: [project("p")],
            expanded: new Set(["p"]),
            query: "alpha",
        });

        expect(rows[0]).toMatchObject({
            kind: "header",
            title: "2 results",
        });
        expect(
            rows.slice(1).map((row) =>
                row.kind === "session" ? row.session.id : null,
            ),
        ).toEqual(["alpha", "pinned"]);
        expect(rows.some((row) => row.kind === "project")).toBe(false);
    });

    test("an unmatched search shows the empty row", () => {
        const rows = buildSessionRows({
            items: [session("alpha", { title: "Alpha" })],
            projects: [],
            expanded: new Set(),
            query: "zzz",
        });

        expect(rows).toEqual([
            {
                key: "empty-search",
                kind: "empty",
                title: "No matches",
                body: 'No conversation title contains "zzz".',
            },
        ]);
    });

    test("no ungrouped conversations still renders the chats empty row", () => {
        const rows = buildSessionRows({
            items: [session("pinned", { pinned: true })],
            projects: [],
            expanded: new Set(),
            query: "",
        });

        expect(rows.at(-1)).toMatchObject({
            kind: "empty",
            title: "No conversations yet",
        });
    });
});
