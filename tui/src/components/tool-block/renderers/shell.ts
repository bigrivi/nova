import { backtick, RESULT_LIMITS, sanitizeInline, tailLines, cleanLines } from "../format/text.ts";
import type { RenderCtx, ResultView, ToolRenderer } from "../types.ts";

type ShellArgs = { command?: string; script_path?: string };

function parseArgs(raw: Record<string, unknown> | null): ShellArgs | null {
    if (raw === null) return {};
    return raw;
}

function subject(args: ShellArgs): string {
    if (typeof args.command === "string" && args.command.trim()) {
        const firstLine = args.command.split(/\r?\n/)[0] ?? "";
        const collapsed = sanitizeInline(firstLine);
        return args.command.includes("\n") ? `${collapsed}…` : collapsed;
    }
    if (typeof args.script_path === "string" && args.script_path.trim()) {
        return sanitizeInline(args.script_path);
    }
    return "inline code";
}

function exitCode(ctx: RenderCtx<ShellArgs>): number | undefined {
    const source = `${ctx.error ?? ""}\n${ctx.outputText}`;
    const match = source.match(/exited with code (\d+)/i);
    return match ? Number(match[1]) : undefined;
}

function result(ctx: RenderCtx<ShellArgs>): ResultView {
    const lines = cleanLines(ctx.outputText);
    if (ctx.status === "running") {
        const tail = tailLines(ctx.outputText, 2);
        return tail.length > 0
            ? { kind: "lines", lines: tail, hiddenAt: "bottom", limit: RESULT_LIMITS.shellOk }
            : { kind: "none" };
    }
    if (lines.length === 0) return { kind: "none" };
    if (lines.length <= RESULT_LIMITS.shellOk) {
        return { kind: "lines", lines, hiddenAt: "bottom", limit: RESULT_LIMITS.shellOk };
    }
    return {
        kind: "lines",
        lines: tailLines(ctx.outputText, RESULT_LIMITS.expandedMax),
        hiddenAt: "top",
        limit: RESULT_LIMITS.shellOk,
    };
}

export const shellRenderer: ToolRenderer<ShellArgs> = {
    parseArgs,
    verbs: { running: "Running", done: "Ran", error: "Failed to run" },
    subject,
    meta: (ctx) => {
        const code = exitCode(ctx);
        return code !== undefined && code !== 0 ? `exit ${code}` : undefined;
    },
    result,
    blockedTitle: (args) => `Waiting for approval — Run ${backtick(subject(args))}`,
};

export const codeRunRenderer: ToolRenderer<ShellArgs> = {
    ...shellRenderer,
    verbs: { running: "Running", done: "Ran", error: "Failed to run" },
    subject: (args) =>
        typeof args.script_path === "string" && args.script_path.trim()
            ? args.script_path.trim()
            : "inline code",
};
