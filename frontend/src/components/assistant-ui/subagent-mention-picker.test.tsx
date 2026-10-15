// @vitest-environment jsdom
//
// Pins the picker's keyboard-navigation scroll. The composer moves the
// highlight with the arrow keys while the list is height-capped and scrolls, so
// the active row must be brought back into view — otherwise the selection walks
// off the visible area and the user cannot see what Enter will pick.

import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NovaAgent } from "../../types/nova";
import { SubagentMentionPicker } from "./subagent-mention-picker";

vi.mock("react-i18next", () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}));

function agent(key: string): NovaAgent {
    return {
        key,
        name: key,
        description: "",
        model: "m",
        provider: "p",
        parents: [],
        created_at: 0,
        updated_at: 0,
        kind: "sub",
        mode: "subagent",
        editable_fields: [],
    };
}

const scrollIntoView = vi.fn();

beforeEach(() => {
    scrollIntoView.mockReset();
    Element.prototype.scrollIntoView =
        scrollIntoView as unknown as Element["scrollIntoView"];
});

describe("SubagentMentionPicker", () => {
    it("scrolls the active option into view when the highlight moves", () => {
        const { rerender } = render(
            <SubagentMentionPicker
                agents={[agent("a"), agent("b"), agent("c")]}
                activeIndex={2}
                onActiveIndexChange={() => {}}
                onSelect={() => {}}
            />,
        );

        expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });

        scrollIntoView.mockClear();
        rerender(
            <SubagentMentionPicker
                agents={[agent("a"), agent("b"), agent("c")]}
                activeIndex={0}
                onActiveIndexChange={() => {}}
                onSelect={() => {}}
            />,
        );

        expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
    });
});
