import { describe, expect, it } from "vitest";

import { mutationVerbKey } from "./file-mutation-verb";

const running = { hasResult: false, isError: false, hasInput: true };

describe("mutationVerbKey", () => {
    it("claims a write only once the call has settled successfully", () => {
        expect(
            mutationVerbKey("write", { ...running, hasResult: true }),
        ).toBe("tools.wrote");
        expect(
            mutationVerbKey("edit", { ...running, hasResult: true }),
        ).toBe("tools.edited");
    });

    it("does not claim a write while the call is still running", () => {
        // The approval window is the case this exists for: the card used to say
        // "Wrote <file>" while the prompt was still on screen and nothing had
        // been written.
        expect(mutationVerbKey("write", running)).toBe("tools.writing");
        expect(mutationVerbKey("edit", running)).toBe("tools.editing");
    });

    it("says it is preparing a write before any arguments arrive", () => {
        expect(
            mutationVerbKey("write", { ...running, hasInput: false }),
        ).toBe("tools.preparingWrite");
        // Edit keeps its existing verb; only write gets the preparing header.
        expect(
            mutationVerbKey("edit", { ...running, hasInput: false }),
        ).toBe("tools.editing");
    });

    it("does not claim a write for a call that settled as an error", () => {
        // A rejected approval settles with an error result, and the tool never
        // ran -- so the past tense would be a claim about a write that did not
        // happen.
        expect(
            mutationVerbKey("write", { ...running, hasResult: true, isError: true }),
        ).toBe("tools.writing");
        expect(
            mutationVerbKey("edit", { ...running, hasResult: true, isError: true }),
        ).toBe("tools.editing");
    });

    it("reads any non-edit tool as a write", () => {
        expect(
            mutationVerbKey("WRITE", { ...running, hasResult: true }),
        ).toBe("tools.wrote");
        expect(
            mutationVerbKey(" write ", { ...running, hasResult: true }),
        ).toBe("tools.wrote");
    });
});
