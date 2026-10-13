// @vitest-environment jsdom
//
// ThinkingIndicator, tested against the duplication it replaced.
//
// The retry notice used to render as a separate banner below the messages while
// the running-message dots stayed up: two dot animations with a gap between
// them. Now the retry line renders in the indicator slot itself, so this pins
// both halves: dots alone when idle, the retry line in the same slot when
// retrying.

import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useReasoningStore } from "../../stores/reasoning-store";
import { ThinkingIndicator } from "./reasoning";

vi.mock("react-i18next", () => ({
    useTranslation: () => ({
        t: (key: string, vars?: Record<string, unknown>) =>
            vars?.attempt != null ? `${key}:${vars.attempt}` : key,
    }),
}));

function dotClasses(container: HTMLElement): string[] {
    return [
        ...container.querySelectorAll('span[aria-hidden="true"] > span'),
    ].map((dot) => dot.className);
}

function retryLine(container: HTMLElement): HTMLElement | null {
    return container.querySelector("span.min-w-0");
}

beforeEach(() => {
    useReasoningStore.setState({ retry: null });
});

describe("ThinkingIndicator", () => {
    it("shows only the dots when idle", () => {
        const { container } = render(<ThinkingIndicator />);

        const dots = dotClasses(container);
        expect(dots).toHaveLength(3);
        expect(dots.every((c) => c.includes("bg-muted-foreground"))).toBe(true);
        expect(retryLine(container)).toBeNull();
    });

    it("shows the retry line in the same slot when retrying", () => {
        useReasoningStore.setState({
            retry: {
                attempt: 2,
                total: 6,
                reason: "Endpoint is unavailable.",
            },
        });
        const { container } = render(<ThinkingIndicator />);

        // Still one set of dots -- the retry reuses the slot, it does not add
        // a second animation next to it -- and the dots share the retry's
        // waiting color instead of staying grey next to amber text.
        const dots = dotClasses(container);
        expect(dots).toHaveLength(3);
        expect(dots.every((c) => c.includes("bg-[#A5750F]"))).toBe(true);
        const line = retryLine(container);
        expect(line?.textContent).toContain("retryDue");
        expect(line?.textContent).toContain("2");
        expect(line?.textContent).toContain("Endpoint is unavailable.");
    });

    it("omits the reason separator when the retry carries no reason", () => {
        useReasoningStore.setState({ retry: { attempt: 1, total: 6, reason: "" } });
        const { container } = render(<ThinkingIndicator />);

        expect(retryLine(container)?.textContent).not.toContain("· ·");
    });
});
