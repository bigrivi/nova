import { afterEach, expect, test } from "bun:test";

import { useMenuStore } from "./menu-store.ts";

afterEach(() => {
    useMenuStore.getState().clear();
});

test("setAnchor keeps the anchor identity when nothing moved", () => {
    const before = useMenuStore.getState().anchor;
    useMenuStore
        .getState()
        .setAnchor({
            x: before.x,
            y: before.y,
            width: before.width,
            edgeY: before.edgeY,
        });
    expect(useMenuStore.getState().anchor).toBe(before);
});

test("setAnchor publishes an anchor that moved", () => {
    const before = useMenuStore.getState().anchor;
    useMenuStore.getState().setAnchor({ ...before, y: before.y + 1 });
    const after = useMenuStore.getState().anchor;
    expect(after).not.toBe(before);
    expect(after.y).toBe(before.y + 1);
});
