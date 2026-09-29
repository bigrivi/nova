import { useEffect, useState } from "react";

/**
 * Small composer/display preferences. Same pattern as `theme.ts`: a
 * localStorage-backed value with a reactive hook, no backend involved.
 */

export type SendShortcut = "enter" | "mod-enter";

const SEND_SHORTCUT_KEY = "nova.ui.send-shortcut";
const CODE_WRAP_KEY = "nova.ui.code-wrap";
const CODE_WRAP_CLASS = "code-wrap";
const CONTEXT_RING_KEY = "nova.ui.context-ring";

function isSendShortcut(value: unknown): value is SendShortcut {
    return value === "enter" || value === "mod-enter";
}

/** Which keystroke sends the composer. Defaults to plain Enter. */
export function readSendShortcut(): SendShortcut {
    try {
        const raw = localStorage.getItem(SEND_SHORTCUT_KEY);
        if (isSendShortcut(raw)) return raw;
    } catch {
        /* Storage unavailable: fall through to the default. */
    }
    return "enter";
}

function writeSendShortcut(value: SendShortcut): void {
    try {
        localStorage.setItem(SEND_SHORTCUT_KEY, value);
    } catch {
        /* Ignore write failures; the in-memory choice still applies. */
    }
}

/** Reactive send-shortcut mode for the settings control. */
export function useSendShortcut(): {
    value: SendShortcut;
    setValue: (value: SendShortcut) => void;
} {
    const [value, setValueState] = useState<SendShortcut>(() => readSendShortcut());
    return {
        value,
        setValue: (next: SendShortcut) => {
            writeSendShortcut(next);
            setValueState(next);
        },
    };
}

/**
 * Decide whether a composer keydown should submit, given the configured
 * shortcut. Never submits while an IME composition is active.
 */
export function shouldSendOnKeyDown(
    event: {
        key: string;
        shiftKey: boolean;
        metaKey: boolean;
        ctrlKey: boolean;
        nativeEvent?: { isComposing?: boolean };
    },
    mode: SendShortcut,
): boolean {
    if (event.key !== "Enter") return false;
    if (event.nativeEvent?.isComposing) return false;
    const mod = event.metaKey || event.ctrlKey;
    if (mode === "mod-enter") {
        return mod && !event.shiftKey;
    }
    return !event.shiftKey;
}

/** Whether markdown code blocks wrap long lines. Defaults to off. */
export function readCodeWrap(): boolean {
    try {
        return localStorage.getItem(CODE_WRAP_KEY) === "1";
    } catch {
        return false;
    }
}

/** Persist the choice and flip the document class immediately. */
export function applyCodeWrap(enabled: boolean): void {
    try {
        localStorage.setItem(CODE_WRAP_KEY, enabled ? "1" : "0");
    } catch {
        /* Ignore write failures; the in-memory choice still applies. */
    }
    document.documentElement.classList.toggle(CODE_WRAP_CLASS, enabled);
}

/** Reactive code-wrap flag for the settings control. */
export function useCodeWrap(): {
    enabled: boolean;
    setEnabled: (enabled: boolean) => void;
} {
    const [enabled, setEnabledState] = useState<boolean>(() => readCodeWrap());

    useEffect(() => {
        applyCodeWrap(enabled);
    }, [enabled]);

    return { enabled, setEnabled: setEnabledState };
}

// Module-level visibility for the composer context ring, so the settings
// toggle and the composer stay in sync without prop drilling.
let contextRingVisible =
    typeof window === "undefined" ? true : readContextRing();
const contextRingSubscribers = new Set<(visible: boolean) => void>();

function readContextRing(): boolean {
    try {
        const raw = localStorage.getItem(CONTEXT_RING_KEY);
        if (raw === null) return true;
        return raw === "1";
    } catch {
        return true;
    }
}

/** Persist the choice and broadcast it to every subscriber. */
export function setContextRingVisible(visible: boolean): void {
    try {
        localStorage.setItem(CONTEXT_RING_KEY, visible ? "1" : "0");
    } catch {
        /* Ignore write failures; the in-memory choice still applies. */
    }
    contextRingVisible = visible;
    for (const notify of contextRingSubscribers) {
        notify(visible);
    }
}

/** Reactive ring visibility for the settings control and the composer. */
export function useContextRingVisible(): {
    visible: boolean;
    setVisible: (visible: boolean) => void;
} {
    const [visible, setVisibleState] = useState<boolean>(contextRingVisible);

    useEffect(() => {
        contextRingSubscribers.add(setVisibleState);
        return () => {
            contextRingSubscribers.delete(setVisibleState);
        };
    }, []);

    return {
        visible,
        setVisible: (next: boolean) => {
            setContextRingVisible(next);
        },
    };
}
