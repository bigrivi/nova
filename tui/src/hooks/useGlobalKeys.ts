/** Global keybindings, in priority order.
 *
 *  The order is the behaviour: the first match wins and nothing below it runs.
 */
import type { KeyEvent } from "@opentui/core";
import { useKeyboard, useTerminalDimensions } from "@opentui/react";
import { useMemo } from "react";

import { SIDEBAR_DOCK_MIN_WIDTH } from "../components/sidebar/layout.ts";
import {
    closeTab,
    cycleTabs,
    openDraftTab,
    reopenLastClosed,
    selectTabIndex,
} from "../lib/tab-actions.ts";
import { useApprovalStore } from "../stores/approval-store.ts";
import { useAskUserStore } from "../stores/ask-user-store.ts";
import { useExpandStore } from "../stores/expand-store.ts";
import { cycleMode } from "../stores/permission-store.ts";
import { useScreenStore } from "../stores/screen-store.ts";
import { useSidebarStore } from "../stores/sidebar-store.ts";
import { requestInterrupt } from "../stream/chat-stream.ts";

type GlobalKeyBinding = {
    match: (key: KeyEvent) => boolean;
    run: (key: KeyEvent) => void;
};

/** These belong to the session, so they stay live while a screen is open. */
const GLOBAL_BINDINGS: GlobalKeyBinding[] = [
    {
        match: (key) => key.ctrl && key.name === "tab",
        // Ctrl+Tab is checked first: ctrl+shift+tab must not fall through to
        // the permission-mode cycle below.
        run: (key) => cycleTabs(key.shift ? -1 : 1),
    },
    {
        match: (key) =>
            (key.meta || key.option) &&
            (key.name === "down" || key.name === "up"),
        run: (key) => cycleTabs(key.name === "down" ? 1 : -1),
    },
    {
        match: (key) => key.shift && key.name === "tab",
        run: () => cycleMode(),
    },
    {
        match: (key) => key.ctrl && key.name === "b",
        run: () => useSidebarStore.getState().toggle(),
    },
];

export function useGlobalKeys({ onExit }: { onExit: () => void }): void {
    const dimensions = useTerminalDimensions();
    // A docked panel leaves the transcript on screen, so escape keeps meaning
    // "interrupt the turn"; a fullscreen one covers it, so escape closes it.
    const docked = dimensions.width >= SIDEBAR_DOCK_MIN_WIDTH;
    /** These belong to the composer, so a screen takes them over. */
    const screenGuardedBindings = useMemo<GlobalKeyBinding[]>(
        () => [
            {
                match: (key) => key.ctrl && key.name === "w",
                run: () => closeTab(),
            },
            {
                match: (key) => key.ctrl && key.name === "t",
                // Ctrl+Shift+T only reaches us as distinct on terminals that
                // encode the modifier; /reopen covers the rest.
                run: (key) => {
                    if (key.shift) {
                        reopenLastClosed();
                    } else {
                        openDraftTab();
                    }
                },
            },
            {
                match: (key) => key.ctrl && /^[1-9]$/.test(key.name),
                run: (key) => selectTabIndex(Number(key.name) - 1),
            },
            {
                match: (key) => key.ctrl && key.name === "o",
                run: () => useExpandStore.getState().toggle(),
            },
            {
                match: (key) => key.ctrl && key.name === "c",
                run: () => onExit(),
            },
            {
                match: (key) => key.name === "escape",
                run: () => {
                    void requestInterrupt();
                },
            },
        ],
        [onExit],
    );

    useKeyboard((key) => {
        if (
            useAskUserStore.getState().active ||
            useApprovalStore.getState().pending
        ) {
            // Modal keyboard is handled by AskUserCard / ApprovalDialog
            return;
        }
        if (
            key.name === "escape" &&
            !docked &&
            useSidebarStore.getState().open
        ) {
            useSidebarStore.getState().setOpen(false);
            return;
        }
        for (const binding of GLOBAL_BINDINGS) {
            if (binding.match(key)) {
                binding.run(key);
                return;
            }
        }
        if (useScreenStore.getState().current) {
            // Screen keyboard is handled by each screen's useKeyboard
            return;
        }
        for (const binding of screenGuardedBindings) {
            if (binding.match(key)) {
                binding.run(key);
                return;
            }
        }
    });
}
