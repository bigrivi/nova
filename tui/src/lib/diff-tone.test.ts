import { describe, expect, test } from "bun:test";
import { diffLineTone } from "./diff-tone.ts";
import type { Theme } from "../themes/types.ts";

const theme = {
    text: { base: "base", muted: "muted", faint: "faint" },
    primary: { muted: "primary-muted" },
    diff: { addedSign: "added", removedSign: "removed" },
} as unknown as Theme;

describe("diffLineTone", () => {
    test("colours added and removed lines", () => {
        expect(diffLineTone("+added", theme)).toBe("added");
        expect(diffLineTone("-removed", theme)).toBe("removed");
    });

    test("keeps file headers muted and hunks accented", () => {
        expect(diffLineTone("+++ b/file", theme)).toBe("muted");
        expect(diffLineTone("--- a/file", theme)).toBe("muted");
        expect(diffLineTone("@@ -1 +1 @@", theme)).toBe("primary-muted");
    });

    test("leaves context lines at the body colour", () => {
        expect(diffLineTone(" unchanged", theme)).toBe("base");
    });
});
