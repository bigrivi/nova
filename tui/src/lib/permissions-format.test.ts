import { describe, expect, test } from "bun:test";
import { joinLimited, policyLines } from "./permissions-format.ts";
import type { NovaPermissionPolicy } from "../api/types.ts";

const POLICY: NovaPermissionPolicy = {
    mode: "ask",
    path: "/home/u/.nova/permissions.json",
    configured: true,
    block_reads_outside_workspace: false,
    shell_allow: ["git status *"],
    shell_ask: [{ description: "pushing", match: "git push *" }],
    shell_disable: [],
    tools: [{ name: "write", effect: "ask" }],
};

describe("joinLimited", () => {
    test("counts the remainder instead of listing it", () => {
        expect(joinLimited(["a", "b", "c", "d", "e"])).toBe("a, b, c, d +1 more");
    });

    test("says none for an empty list", () => {
        expect(joinLimited([])).toBe("none");
    });
});

describe("policyLines", () => {
    test("explains the mode in the first line", () => {
        expect(policyLines(POLICY, "dontAsk")[0]).toContain("no prompts");
        expect(policyLines(POLICY, "dontAsk")[0]).toContain("refused");
    });

    test("names the config file", () => {
        expect(policyLines(POLICY, "ask").join("\n")).toContain(
            "/home/u/.nova/permissions.json",
        );
    });

    test("says defaults apply when the file is absent", () => {
        const lines = policyLines({ ...POLICY, configured: false }, "ask");
        expect(lines.join("\n")).toContain("built-in defaults apply");
    });

    test("lists rules and tool effects", () => {
        const text = policyLines(POLICY, "ask").join("\n");
        expect(text).toContain("git status *");
        expect(text).toContain("pushing");
        expect(text).toContain("write=ask");
    });

    test("shows a placeholder before the policy loads", () => {
        const lines = policyLines(null, "ask");
        expect(lines[1]).toContain("loading");
    });
});
