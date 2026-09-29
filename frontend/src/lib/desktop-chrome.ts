import { useEffect, useState } from "react";

interface PywebviewWindow {
    pywebview?: {
        platform?: string;
    };
}

/** True only inside the macOS desktop build with hidden-titlebar chrome. */
export function isMacHiddenTitlebarWindow(
    target: Window = window,
): boolean {
    const candidate = target as unknown as PywebviewWindow;
    return candidate.pywebview?.platform === "cocoa";
}

/**
 * React hook reporting macOS hidden-titlebar mode. False everywhere else
 * (browser dev, Windows, Linux), so those layouts stay pixel-identical.
 */
export function useMacHiddenTitlebar(): boolean {
    const [enabled, setEnabled] = useState(() =>
        isMacHiddenTitlebarWindow(),
    );

    useEffect(() => {
        if (enabled) return;
        const onReady = () => {
            if (isMacHiddenTitlebarWindow()) setEnabled(true);
        };
        window.addEventListener("pywebviewready", onReady);
        return () => window.removeEventListener("pywebviewready", onReady);
    }, [enabled]);

    return enabled;
}
