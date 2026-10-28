import type { ToolCallPart as ToolCallPartData } from "../../stores/chat-store.ts";

export type ToolStatus = ToolCallPartData["status"];

export interface RenderCtx<A> {
    part: ToolCallPartData;
    args: A;
    status: ToolStatus;
    outputText: string;
    error?: string;
    width: number;
    expanded: boolean;
}

export type ResultView =
    | { kind: "none" }
    | { kind: "lines"; lines: string[]; hiddenAt: "top" | "bottom"; limit?: number }
    | { kind: "diff"; diff: string; synthesized: boolean; truncated?: boolean; hiddenLines?: number };

export interface ToolRenderer<A = unknown> {
    parseArgs(raw: Record<string, unknown> | null): A | null;
    verbs: { running: string; done: string; error: string };
    subject(args: A): string;
    meta?(ctx: RenderCtx<A>): string | undefined;
    result?(ctx: RenderCtx<A>): ResultView;
    blockedTitle?(args: A): string;
}
