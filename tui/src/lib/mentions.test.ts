import { describe, expect, test } from "bun:test";
import type { NovaAgentRecord } from "../api/types.ts";
import type { FileCandidate } from "./file-completion.ts";
import {
    buildMentionCandidates,
    filterSubagents,
    mentionText,
    selectableSubagents,
} from "./mentions.ts";

function agent(
    key: string,
    overrides: Partial<NovaAgentRecord> = {},
): NovaAgentRecord {
    return {
        key,
        name: key[0]!.toUpperCase() + key.slice(1),
        description: "",
        model: "m",
        provider: "p",
        tools: null,
        workspace_dir: null,
        created_at: 0,
        updated_at: 0,
        mode: "subagent",
        parents: ["main"],
        ...overrides,
    };
}

const PATHS: FileCandidate[] = [
    { insert: "src/", isDir: true },
    { insert: "src/lib/", isDir: true },
    { insert: "src/lib/attachments.ts", isDir: false },
    { insert: "package.json", isDir: false },
];

describe("selectableSubagents", () => {
    test("keeps sub-agents of the active agent, sorted by key", () => {
        const list = selectableSubagents(
            [
                agent("fixer"),
                agent("coder"),
                agent("main", { mode: "primary", children: undefined } as never),
                agent("other", { parents: ["someone-else"] }),
            ],
            "main",
        );
        expect(list.map((item) => item.key)).toEqual(["coder", "fixer"]);
    });

    test("offers every sub-agent when parents are missing", () => {
        const list = selectableSubagents(
            [agent("coder", { parents: undefined })],
            "main",
        );
        expect(list.map((item) => item.key)).toEqual(["coder"]);
    });
});

describe("filterSubagents", () => {
    test("matches key, name or description", () => {
        const list = [agent("coder"), agent("explorer", { name: "Explorer" })];
        expect(filterSubagents(list, "cod").map((a) => a.key)).toEqual(["coder"]);
        expect(filterSubagents(list, "EXPL").map((a) => a.key)).toEqual([
            "explorer",
        ]);
        expect(filterSubagents(list, "").length).toBe(2);
    });
});

describe("buildMentionCandidates", () => {
    const agents = [agent("coder"), agent("fixer")];

    test("puts agents before directories and files", () => {
        const rows = buildMentionCandidates(agents, PATHS, "");
        expect(rows.map((row) => row.kind)).toEqual([
            "agent",
            "agent",
            "dir",
            "dir",
            "file",
            "file",
        ]);
    });

    test("a path query offers no agents", () => {
        // What completeMentions("src/") would return, best match first.
        const inside = PATHS.filter(
            (entry) => entry.insert.startsWith("src/") && entry.insert !== "src/",
        );
        const rows = buildMentionCandidates(agents, inside, "src/");
        expect(rows.every((row) => row.kind !== "agent")).toBe(true);
        expect(rows[0]?.insert).toBe("src/lib/");
    });

    test("an agent matched only by its description ranks below files", () => {
        const chatty = [
            agent("oracle", { description: "architecture and risk review" }),
        ];
        const rows = buildMentionCandidates(chatty, PATHS, "risk");
        expect(rows.at(-1)?.kind).toBe("agent");
        expect(rows[0]?.kind).not.toBe("agent");
    });

    test("a strong name match still leads", () => {
        const rows = buildMentionCandidates(agents, PATHS, "fix");
        expect(rows[0]).toMatchObject({ kind: "agent", insert: "fixer" });
    });

    test("caps the list", () => {
        expect(buildMentionCandidates(agents, PATHS, "", 3)).toHaveLength(3);
    });
});

describe("mentionText", () => {
    test("agents and files end in a space, directories do not", () => {
        expect(
            mentionText({
                kind: "agent",
                insert: "coder",
                label: "",
                hint: "",
                value: "",
            }),
        ).toBe("@coder ");
        expect(
            mentionText({
                kind: "file",
                insert: "a.ts",
                label: "",
                hint: "",
                value: "",
            }),
        ).toBe("@a.ts ");
        expect(
            mentionText({
                kind: "dir",
                insert: "src/",
                label: "",
                hint: "",
                value: "",
            }),
        ).toBe("@src/");
    });
});
