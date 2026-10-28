import { RESULT_LIMITS } from "../format/text.ts";
import type { RenderCtx, ResultView, ToolRenderer } from "../types.ts";

type SimpleArgs = Record<string, unknown> | null;

interface SimpleConfig {
    name: string;
    running: string;
    done: string;
    error: string;
    argKeys: string[];
}

const CONFIGS: SimpleConfig[] = [
    { name: "browser_use", running: "Running", done: "Ran", error: "Failed", argKeys: ["action", "url", "query"] },
    { name: "save_memory", running: "Saving", done: "Saved", error: "Failed to save", argKeys: ["key"] },
    { name: "search_memory", running: "Searching", done: "Searched", error: "Failed to search", argKeys: ["query"] },
    { name: "delete_memory", running: "Deleting", done: "Deleted", error: "Failed to delete", argKeys: ["key", "memory_id"] },
    { name: "list_memories", running: "Listing", done: "Listed", error: "Failed to list", argKeys: ["scope"] },
    { name: "load_skill", running: "Loading", done: "Loaded", error: "Failed to load", argKeys: ["name", "slug", "skill"] },
    { name: "install_skill", running: "Installing", done: "Installed", error: "Failed to install", argKeys: ["slug", "name", "skill"] },
    { name: "delegate_to_agent", running: "Delegating", done: "Delegated", error: "Failed to delegate", argKeys: ["agent_key"] },
    { name: "list_skills", running: "Listing", done: "Listed", error: "Failed to list", argKeys: [] },
];

function pickArg(args: SimpleArgs, keys: string[]): string {
    if (!args) return "";
    for (const key of keys) {
        const value = args[key];
        if (typeof value === "string" && value.trim()) return value.trim().replace(/\s+/g, " ");
        if (value != null) return String(value);
    }
    return "";
}

function parseArgs(raw: Record<string, unknown> | null): SimpleArgs {
    return raw ?? {};
}

function genericResult(ctx: RenderCtx<SimpleArgs>): ResultView {
    const text = ctx.outputText.trim();
    const lines = text.split("\n").map((line) => line.trim()).filter((line) => line.length > 0);
    if (lines.length === 0) return { kind: "none" };
    return { kind: "lines", lines, hiddenAt: "bottom", limit: RESULT_LIMITS.generic };
}

export function simpleRenderer(config: SimpleConfig): ToolRenderer<SimpleArgs> {
    return {
        parseArgs,
        verbs: { running: config.running, done: config.done, error: config.error },
        subject: (args) => pickArg(args, config.argKeys) || config.name,
        result: (ctx) => genericResult(ctx),
        blockedTitle: (args) => {
            const subject = pickArg(args, config.argKeys) || config.name;
            return `Waiting for approval — ${config.name}(${subject})`;
        },
    };
}

export const SIMPLE_RENDERERS: Record<string, ToolRenderer<SimpleArgs>> = Object.fromEntries(
    CONFIGS.map((config) => [config.name, simpleRenderer(config)]),
);
