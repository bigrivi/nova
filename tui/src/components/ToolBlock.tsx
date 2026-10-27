/** Tool call block: status glyph + verb-tense label, output lines below. */
import { useMemo } from "react";
import { useTheme } from "../context/theme.tsx";
import type { ToolCallPart as ToolCallPartData } from "../stores/chat-store.ts";
import { useExpandStore } from "../stores/expand-store.ts";
import { Spinner } from "./tool-block/Spinner.tsx";
import { errorResult } from "./tool-block/format/text.ts";
import { ResultBlock } from "./tool-block/parts/ResultBlock.tsx";
import { getRenderer } from "./tool-block/registry.ts";
import { createFallbackRenderer } from "./tool-block/renderers/fallback.ts";
import type { ToolStatus } from "./tool-block/types.ts";

const GLYPH: Record<Exclude<ToolStatus, "running">, string> = {
    blocked: "?",
    done: "✓",
    error: "✗",
};

export function ToolBlock({ part }: { part: ToolCallPartData }) {
    const { toolName, status, args, outputText, error } = part;
    const expanded = useExpandStore((state) => state.expanded);

    const renderer = getRenderer(toolName);
    const theme = useTheme();
    const parsedArgs = renderer.parseArgs(args);
    const activeRenderer = parsedArgs === null ? createFallbackRenderer(toolName) : renderer;
    const ctxArgs = parsedArgs ?? args ?? {};

    const GLYPH_COLOR: Record<ToolStatus, string> = {
        running: theme.feedback.running,
        blocked: theme.primary.base,
        done: theme.feedback.success,
        error: theme.feedback.error,
    };

    const ctx = {
        part,
        args: ctxArgs,
        status,
        outputText,
        error,
        width: 0,
        expanded,
    };

    const title = useMemo(() => {
        if (status === "blocked" && activeRenderer.blockedTitle) {
            return activeRenderer.blockedTitle(ctxArgs);
        }
        const verb =
            status === "running"
                ? activeRenderer.verbs.running
                : status === "blocked"
                  ? "Waiting for approval"
                  : status === "error"
                    ? activeRenderer.verbs.error
                    : activeRenderer.verbs.done;
        const meta = activeRenderer.meta?.(ctx);
        const subject = activeRenderer.subject(ctxArgs);
        const base = [verb, subject].filter(Boolean).join(" ");
        return meta ? `${base} · ${meta}` : base;
    }, [status, activeRenderer, ctxArgs, ctx]);

    const resultView = useMemo(() => {
        if (status === "error") return errorResult(ctx);
        return activeRenderer.result?.(ctx) ?? { kind: "none" as const };
    }, [status, activeRenderer, ctx]);

    const glyph =
        status === "running" ? null : GLYPH[status as Exclude<ToolStatus, "running">];

    return (
        <box flexDirection="column" marginTop={1}>
            <box flexDirection="row" gap={1}>
                {status === "running" ? (
                    <box flexShrink={0} ><Spinner/></box>
                ) : (
                    <text fg={GLYPH_COLOR[status]} content={`${glyph}`} flexShrink={0} />
                )}
                <text fg={theme.text.base} content={title} flexShrink={1} minWidth={0} wrapMode="word" />
            </box>
            <ResultBlock view={resultView} expanded={expanded} />
        </box>
    );
}
