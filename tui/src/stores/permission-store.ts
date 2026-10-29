/** Permission mode for the session: which question a risky call asks.
 *
 *  The mode travels with each turn (`permission_mode` on the request), so the
 *  backend rebuilds the agent for the chosen mode instead of restarting. It is
 *  not persisted: a fresh launch returns to whatever `permissions.json` says.
 */
import { create } from "zustand";
import type { NovaPermissionPolicy } from "../api/types.ts";

export type PermissionMode = "ask" | "acceptEdits" | "dontAsk";

/** Cycle order for Shift+Tab, most careful first. */
export const MODES: PermissionMode[] = ["ask", "acceptEdits", "dontAsk"];

export const MODE_LABEL: Record<PermissionMode, string> = {
    ask: "ask",
    acceptEdits: "auto-edit",
    dontAsk: "no prompts",
};

/** One line explaining what the mode does, shown in the permissions panel. */
export const MODE_SUMMARY: Record<PermissionMode, string> = {
    ask: "every command a rule flags waits for you",
    acceptEdits: "edits inside the workspace go through; commands still ask",
    dontAsk: "a flagged command is refused instead of asked",
};

export function normalizeMode(value: string | null | undefined): PermissionMode {
    return value === "acceptEdits" || value === "dontAsk" ? value : "ask";
}

/** The next mode in the Shift+Tab cycle. */
export function nextMode(current: PermissionMode): PermissionMode {
    const index = MODES.indexOf(current);
    return MODES[(index + 1) % MODES.length] ?? "ask";
}

/**
 * Advance the mode once per keypress.
 *
 * Both the global keyboard handler and the composer see the same Shift+Tab (the
 * composer has to see it to stop the textarea inserting a tab), so without this
 * guard one press would skip a mode.
 */
let lastCycleAt = 0;
export function cycleMode(): void {
    const now = Date.now();
    if (now - lastCycleAt < 80) return;
    lastCycleAt = now;
    const store = usePermissionStore.getState();
    store.setMode(nextMode(store.mode));
}

/** Reset the cycle guard. Tests only. */
export function resetCycleGuard(): void {
    lastCycleAt = 0;
}

type PermissionState = {
    mode: PermissionMode;
    policy: NovaPermissionPolicy | null;
    setMode: (mode: PermissionMode) => void;
    setPolicy: (policy: NovaPermissionPolicy) => void;
};

export const usePermissionStore = create<PermissionState>((set) => ({
    mode: "ask",
    policy: null,
    setMode: (mode) => set({ mode }),
    // The policy's own mode is the starting point, not a replacement for a
    // choice the user already made in this session.
    setPolicy: (policy) => set({ policy }),
}));
