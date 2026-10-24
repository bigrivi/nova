import { describe, expect, test } from "bun:test";
import {
    buildEditDiff,
    looksLikeDiff,
} from "./diff.ts";

describe("format/diff", () => {
    test("looksLikeDiff accepts a hunk header", () => {
        expect(looksLikeDiff("@@ -1,2 +1,3 @@\n-a\n+b")).toBe(true);
    });

    test("looksLikeDiff accepts adjacent --- and +++", () => {
        expect(looksLikeDiff("--- a/x\n+++ b/x\n@@ -1,1 +1,1 @@\n-a\n+b")).toBe(true);
    });

    test("looksLikeDiff rejects a markdown separator", () => {
        expect(looksLikeDiff("---\nfoo\n---")).toBe(false);
    });

    test("buildEditDiff has matching hunk counts", () => {
        const diff = buildEditDiff("foo.ts", "a\nb\nc\n", "a\nX\nc\n");
        expect(diff).toContain("@@ -1,3 +1,3 @@");
        expect(diff).toContain("-b");
        expect(diff).toContain("+X");
    });

    test("buildEditDiff handles pure insertion", () => {
        const diff = buildEditDiff("foo.ts", "", "new\n");
        expect(diff).toContain("@@ -1,0 +1,1 @@");
        expect(diff).toContain("+new");
    });
});