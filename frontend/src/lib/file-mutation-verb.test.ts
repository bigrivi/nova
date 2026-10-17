import { describe, expect, it } from "vitest";

import { mutationVerbKey } from "./file-mutation-verb";

describe("mutationVerbKey", () => {
    it("claims a write only once the call has settled successfully", () => {
        expect(
            mutationVerbKey("write", { hasResult: true, isError: false }),
        ).toBe("tools.wrote");
        expect(
            mutationVerbKey("edit", { hasResult: true, isError: false }),
        ).toBe("tools.edited");
    });

    it("does not claim a write while the call is still running", () => {
        // The approval window is the case this exists for: the card used to say
        // "Wrote <file>" while the prompt was still on screen and nothing had
        // been written.
        expect(
            mutationVerbKey("write", { hasResult: false, isError: false }),
        ).toBe("tools.writing");
        expect(
            mutationVerbKey("edit", { hasResult: false, isError: false }),
        ).toBe("tools.editing");
    });

    it("does not claim a write for a call that settled as an error", () => {
        // A rejected approval settles with an error result, and the tool never
        // ran -- so the past tense would be a claim about a write that did not
        // happen.
        expect(
            mutationVerbKey("write", { hasResult: true, isError: true }),
        ).toBe("tools.writing");
        expect(
            mutationVerbKey("edit", { hasResult: true, isError: true }),
        ).toBe("tools.editing");
    });

    it("reads any non-edit tool as a write", () => {
        expect(
            mutationVerbKey("WRITE", { hasResult: true, isError: false }),
        ).toBe("tools.wrote");
        expect(
            mutationVerbKey(" write ", { hasResult: true, isError: false }),
        ).toBe("tools.wrote");
    });
});
