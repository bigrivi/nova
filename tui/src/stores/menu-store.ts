/** The composer's suggestion menu, published for the root overlay to draw.
 *
 *  The menu has to be painted by the app's root, not by the composer: a menu
 *  nested inside the composer is drawn into the same rows as the transcript and
 *  the two interleave (menu rows missing, transcript rows showing through).
 *  The composer owns the state; the root owns the layer.
 */
import { create } from "zustand";
import type { CommandSpec } from "../commands.ts";

export type MenuAnchor = { x: number; y: number; width: number };

type MenuState = {
    items: CommandSpec[];
    selectedIndex: number;
    /** Rows the menu occupies, chrome included. */
    height: number;
    /** Where the composer sits on screen, measured from the renderable. */
    anchor: MenuAnchor;
    /** Which composer published this menu; only it may clear it. */
    owner: number;
    show: (
        items: CommandSpec[],
        selectedIndex: number,
        height: number,
        anchor: MenuAnchor,
        owner: number,
    ) => void;
    setAnchor: (anchor: MenuAnchor) => void;
    clear: (owner?: number) => void;
};

export const useMenuStore = create<MenuState>((set) => ({
    items: [],
    selectedIndex: 0,
    height: 0,
    anchor: { x: 0, y: 0, width: 0 },
    owner: 0,
    show: (items, selectedIndex, height, anchor, owner) =>
        set({ items, selectedIndex, height, anchor, owner }),
    setAnchor: (anchor) => set({ anchor }),
    // An unmounting composer from another screen (or another test) must not wipe
    // a menu someone else published.
    clear: (owner) =>
        set((state) => {
            if (owner !== undefined && state.owner !== owner) return state;
            return { items: [], selectedIndex: 0, height: 0, owner: 0 };
        }),
}));
