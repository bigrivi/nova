import { describe, expect, it } from "vitest";

import { shouldSendOnKeyDown } from "./ui-prefs";

function key(
    overrides: Partial<{
        key: string;
        shiftKey: boolean;
        metaKey: boolean;
        ctrlKey: boolean;
        isComposing: boolean;
    }> = {},
) {
    return {
        key: "Enter",
        shiftKey: false,
        metaKey: false,
        ctrlKey: false,
        ...overrides,
        nativeEvent: {
            isComposing: overrides.isComposing ?? false,
        },
    };
}

describe("shouldSendOnKeyDown", () => {
    it("sends on plain Enter in enter mode", () => {
        expect(shouldSendOnKeyDown(key(), "enter")).toBe(true);
    });

    it("does not send on Shift+Enter in enter mode", () => {
        expect(shouldSendOnKeyDown(key({ shiftKey: true }), "enter")).toBe(
            false,
        );
    });

    it("only sends on mod+Enter in mod-enter mode", () => {
        expect(shouldSendOnKeyDown(key(), "mod-enter")).toBe(false);
        expect(shouldSendOnKeyDown(key({ metaKey: true }), "mod-enter")).toBe(
            true,
        );
        expect(shouldSendOnKeyDown(key({ ctrlKey: true }), "mod-enter")).toBe(
            true,
        );
        expect(
            shouldSendOnKeyDown(
                key({ metaKey: true, shiftKey: true }),
                "mod-enter",
            ),
        ).toBe(false);
    });

    it("never sends while an IME composition is active", () => {
        expect(
            shouldSendOnKeyDown(key({ isComposing: true }), "enter"),
        ).toBe(false);
        expect(
            shouldSendOnKeyDown(
                key({ metaKey: true, isComposing: true }),
                "mod-enter",
            ),
        ).toBe(false);
    });

    it("ignores non-Enter keys", () => {
        expect(shouldSendOnKeyDown(key({ key: "a" }), "enter")).toBe(false);
    });
});
