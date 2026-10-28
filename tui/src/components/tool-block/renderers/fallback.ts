import { RESULT_LIMITS } from "../format/text.ts";
import type { ResultView, ToolRenderer } from "../types.ts";

export function createFallbackRenderer(toolName: string): ToolRenderer<Record<string, unknown> | null> {
    const pickArg = (args: Record<string, unknown> | null): string => {
        if (!args) return "";
        for (const value of Object.values(args)) {
            if (typeof value === "string" && value.trim()) return value.trim().replace(/\s+/g, " ");
            if (value != null) return String(value);
        }
        return "";
    };

    return {
        parseArgs: (raw) => raw,
        verbs: { running: "Running", done: "Ran", error: "Failed" },
        subject: (args) => pickArg(args) || toolName,
        result: (ctx): ResultView => {
            const text = ctx.outputText.trim();
            let parsed: unknown = null;
            try {
                parsed = JSON.parse(text);
            } catch {
                parsed = null;
            }
            const lines =
                parsed !== null
                    ? JSON.stringify(parsed, null, 2).split("\n")
                    : text.split("\n").map((line) => line.trim()).filter(Boolean);
            if (lines.length === 0) return { kind: "none" };
            return { kind: "lines", lines, hiddenAt: "bottom", limit: RESULT_LIMITS.generic };
        },
        blockedTitle: (args) => {
            const subject = pickArg(args) || toolName;
            return `Waiting for approval — ${toolName}(${subject})`;
        },
    };
}
