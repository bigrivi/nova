import { describe, expect, test } from "bun:test";
import {
    buildEditDiff,
    extractDiff,
    parseToolDiff,
    looksLikeDiff,
} from "./diff.ts";

/** Count the lines a unified diff header promises, for the parser's invariant. */
function bodyCounts(diff: string): { old: number; added: number } {
    const lines = diff.split("\n");
    let old = 0;
    let added = 0;
    for (const line of lines) {
        if (line.startsWith("--- ") || line.startsWith("+++ ") || line.startsWith("@@")) {
            continue;
        }
        if (line.startsWith("-")) old += 1;
        else if (line.startsWith("+")) added += 1;
        else {
            old += 1;
            added += 1;
        }
    }
    return { old, added };
}

function headerCounts(diff: string): { old: number; added: number } {
    const match = /@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(diff);
    return {
        old: Number(match?.[2] ?? 1),
        added: Number(match?.[4] ?? 1),
    };
}

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

describe("extractDiff", () => {
    // The exact shape the edit tool returns; its last line is a blank context
    // line, so trimming trailing whitespace drops a line the header counts.
    const OUTPUT = [
        "Changes applied to gen_placement.py:",
        "",
        "--- a/gen_placement.py",
        "+++ b/gen_placement.py",
        "@@ -105,8 +105,15 @@",
        "     return result",
        " ",
        " ",
        "-def main():",
        "-    t0 = time.time()",
        '+    # read NGSL headwords (optional)',
        "+    ngsl = set()",
        '+    ngsl_path = Path("/tmp/ngsl_headwords.txt")',
        "+    if ngsl_path.exists():",
        "+        for line in ngsl_path.read_text().splitlines():",
        "+            w = line.strip().lower()",
        "+            if w and w.isalpha():",
        "+                ngsl.add(w)",
        '+    print("NGSL headwords:", len(ngsl), flush=True)',
        "     raw = top_n_list(\"en\", 30000)",
        "     print(\"raw\", len(raw))",
        " ",
        "",
    ].join("\n");

    test("drops the prose preamble", () => {
        const diff = extractDiff(OUTPUT);
        expect(diff.startsWith("--- a/gen_placement.py")).toBe(true);
        expect(diff).not.toContain("Changes applied");
    });

    test("keeps the trailing blank context line", () => {
        const diff = extractDiff(OUTPUT);
        const lines = diff.split("\n");
        expect(lines[lines.length - 1]).toBe(" ");
    });

    test("keeps the header and body counts in agreement", () => {
        const diff = extractDiff(OUTPUT);
        expect(headerCounts(diff)).toEqual(bodyCounts(diff));
        expect(headerCounts(diff)).toEqual({ old: 8, added: 15 });
    });

    test("trim() would have broken the same diff", () => {
        // Documents the regression: trimming removes the final " " line.
        const trimmed = OUTPUT.trim();
        expect(headerCounts(trimmed)).not.toEqual(bodyCounts(trimmed));
    });

    test("returns empty when there is no diff", () => {
        expect(extractDiff("nothing here")).toBe("");
    });
});

describe("extractDiff on a server-truncated write diff", () => {
    // Reproduces a stored `write` output: the backend appended its marker in
    // the middle of a hunk, so the last hunk's body is short.
    const TRUNCATED = [
        "File updated — /tmp/x.py:",
        "",
        "--- a/x.py",
        "+++ b/x.py",
        "@@ -1,3 +1,3 @@",
        " one",
        "-two",
        "+TWO",
        " three",
        "@@ -20,3 +20,3 @@",
        " twenty",
        "-twentyone",
        "+TWENTYONE",
        "",
        "[... 12 more lines ...]",
    ].join("\n");

    test("drops the marker and the cut trailing hunk", () => {
        const diff = extractDiff(TRUNCATED);
        expect(diff).not.toContain("more lines");
        expect(diff).not.toContain("@@ -20,3 +20,3 @@");
        expect(diff).toContain("@@ -1,3 +1,3 @@");
        expect(headerCounts(diff)).toEqual(bodyCounts(diff));
    });

    test("reports no diff when the only hunk was cut", () => {
        const cut = [
            "File updated — /tmp/x.py:",
            "",
            "--- a/x.py",
            "+++ b/x.py",
            "@@ -1,5 +1,5 @@",
            " one",
            "-two",
            "+TWO",
            "",
            "[... 9 more lines ...]",
        ].join("\n");
        // A header-only patch renders as an empty box, so it is not a diff;
        // the caller shows the truncation notice instead.
        expect(extractDiff(cut)).toBe("");
        expect(parseToolDiff(cut)).toEqual({ diff: "", truncated: true, hiddenLines: 9 });
    });
});

describe("extractDiff anchoring", () => {
    const DIFF = ["--- a/x.ts", "+++ b/x.ts", "@@ -1,1 +1,1 @@", "-old", "+new"].join("\n");

    test("finds a diff that follows prose", () => {
        expect(extractDiff(`Edited x.ts\n${DIFF}`)).toBe(DIFF);
    });

    test("ignores a bare separator in prose", () => {
        // "--- " used to be enough to start a diff and swallow the rest
        expect(extractDiff("result\n--- not a header\nmore prose")).toBe("");
    });

    test("ignores a --- line without a +++ line after it", () => {
        expect(extractDiff("--- a/x.ts\nno plus header")).toBe("");
    });
});
