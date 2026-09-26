import { describe, expect, it } from "vitest";

import type { NovaProject, NovaThreadSummary } from "@/types/nova";

import {
    dateBucket,
    groupThreads,
    nextThreadAfterDelete,
    orderedThreads,
} from "./sidebar-model";

const NOW = new Date("2026-09-26T12:00:00");
const DAY = 86_400_000;

function thread(overrides: Partial<NovaThreadSummary>): NovaThreadSummary {
    return {
        id: "t1",
        title: "Thread",
        status: "regular",
        updated_at: NOW.getTime(),
        agent_key: "main",
        workspace_dir: null,
        pinned: false,
        project_id: null,
        ...overrides,
    };
}

function project(overrides: Partial<NovaProject>): NovaProject {
    return {
        id: "p1",
        name: "Alpha",
        path: "/code/alpha",
        created_at: NOW.getTime(),
        updated_at: NOW.getTime(),
        ...overrides,
    };
}

describe("dateBucket", () => {
    it("splits by calendar day, not by elapsed hours", () => {
        const lateYesterday = new Date("2026-09-25T23:30:00").getTime();

        expect(dateBucket(NOW.getTime(), NOW)).toBe("today");
        expect(dateBucket(lateYesterday, NOW)).toBe("yesterday");
        expect(dateBucket(lateYesterday - 3 * DAY, NOW)).toBe("last7Days");
        expect(dateBucket(lateYesterday - 30 * DAY, NOW)).toBe("older");
    });
});

describe("groupThreads", () => {
    it("keeps a pinned chat out of its project and counts it instead", () => {
        const groups = groupThreads(
            [
                thread({ id: "a", project_id: "p1" }),
                thread({ id: "b", project_id: "p1", pinned: true }),
            ],
            [project({ id: "p1" })],
            NOW,
        );

        expect(groups.pinned.map((item) => item.id)).toEqual(["b"]);
        expect(groups.projects[0].threads.map((item) => item.id)).toEqual(["a"]);
        expect(groups.projects[0].pinnedCount).toBe(1);
    });

    it("lists a project with no sessions so it can host a new one", () => {
        const groups = groupThreads([], [project({ id: "empty" })], NOW);

        expect(groups.projects).toHaveLength(1);
        expect(groups.projects[0].threads).toEqual([]);
    });

    it("disambiguates same-named projects by their parent directory", () => {
        const groups = groupThreads(
            [],
            [
                project({ id: "p1", name: "web", path: "/code/alpha/web" }),
                project({ id: "p2", name: "web", path: "/code/beta/web" }),
            ],
            NOW,
        );

        expect(groups.projects.map((item) => item.qualifier)).toEqual([
            "alpha",
            "beta",
        ]);
    });

    it("leaves the qualifier empty when the name is unique", () => {
        const groups = groupThreads(
            [],
            [project({ id: "p1", name: "web", path: "/code/alpha/web" })],
            NOW,
        );

        expect(groups.projects[0].qualifier).toBeNull();
    });

    it("files a thread with an unknown project under chats, not nowhere", () => {
        const groups = groupThreads(
            [thread({ id: "a", project_id: "gone" })],
            [],
            NOW,
        );

        expect(groups.chats.today.map((item) => item.id)).toEqual(["a"]);
    });

    it("orders projects by their latest session", () => {
        const groups = groupThreads(
            [
                thread({ id: "old", project_id: "p1", updated_at: NOW.getTime() - 5 * DAY }),
                thread({ id: "new", project_id: "p2", updated_at: NOW.getTime() - DAY }),
            ],
            [project({ id: "p1" }), project({ id: "p2" })],
            NOW,
        );

        expect(groups.projects.map((item) => item.id)).toEqual(["p2", "p1"]);
    });
});

describe("orderedThreads", () => {
    it("lists every thread exactly once across the sections", () => {
        const groups = groupThreads(
            [
                thread({ id: "pinned", pinned: true }),
                thread({ id: "in-project", project_id: "p1" }),
                thread({ id: "loose" }),
            ],
            [project({ id: "p1" })],
            NOW,
        );

        expect(orderedThreads(groups).map((item) => item.id)).toEqual([
            "pinned",
            "in-project",
            "loose",
        ]);
    });
});

describe("nextThreadAfterDelete", () => {
    const rows = [thread({ id: "a" }), thread({ id: "b" }), thread({ id: "c" })];

    it("prefers the following row", () => {
        expect(nextThreadAfterDelete(rows, "a")).toBe("b");
    });

    it("falls back to the previous row at the end", () => {
        expect(nextThreadAfterDelete(rows, "c")).toBe("b");
    });

    it("returns null for a row that is not in the list", () => {
        expect(nextThreadAfterDelete(rows, "missing")).toBeNull();
    });
});
