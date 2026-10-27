/** Status dot: one glyph in every state, so the label never shifts. Running
 *  pulses the accent colour instead of swapping characters. */
import { RGBA } from "@opentui/core";
import { useEffect, useState } from "react";
import { useTheme } from "../../context/theme.tsx";
import type { AgentStatus } from "../../lib/status.ts";

const PULSE_MS = 500;
const DIM_ALPHA = 0.35;

export function StatusGlyph({ status }: { status: AgentStatus }) {
    const theme = useTheme();
    const [pulse, setPulse] = useState(false);

    useEffect(() => {
        if (status !== "running") {
            setPulse(false);
            return;
        }
        const timer = setInterval(() => setPulse((value) => !value), PULSE_MS);
        return () => clearInterval(timer);
    }, [status]);

    const accent = RGBA.fromHex(theme.primary.base);
    const runningFg = pulse
        ? accent
        : RGBA.fromValues(accent.r, accent.g, accent.b, DIM_ALPHA);

    const color =
        status === "running"
            ? runningFg
            : status === "waiting"
              ? theme.feedback.running
              : status === "error"
                ? theme.feedback.error
                : theme.text.muted;

    return <text flexShrink={0} fg={color}>●</text>;
}
