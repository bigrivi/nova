import { describe, expect, test } from "bun:test";

import { contrastRatio, luminance } from "./contrast.ts";

describe("contrastRatio", () => {
    test("is 21 for black on white and 1 for a colour on itself", () => {
        expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 0);
        expect(contrastRatio("#58a6ff", "#58a6ff")).toBeCloseTo(1, 5);
    });
});

describe("luminance", () => {
    test("bounds black at 0 and white at 1", () => {
        expect(luminance("#000000")).toBeCloseTo(0, 5);
        expect(luminance("#ffffff")).toBeCloseTo(1, 5);
    });
});
