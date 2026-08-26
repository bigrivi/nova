/** Tool call block: status glyph + verb-tense label, output lines below.
 *
 * Visual language (see ~/Documents/ai/nova/tool-call-mockup.md):
 * - Color lives only in the status glyph; label text stays foreground.
 * - The label is a verb-tense sentence per tool per state
 *   ("Running `npm test`" -> "Ran `npm test`"), not a fixed name(args) form.
 * - Multi-line results render one line each under a "  ⎿ " prefix.
 */

import { useEffect, useState } from "react";
import type { ToolCallPart as ToolCallPartData } from "../stores/chat-store.ts";
import { theme } from "../theme.ts";

const DIFF_TOOLS = new Set(["edit", "write", "write_files", "code_run"]);

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const SPINNER_TICK_MS = 80;

type DisplayStatus = "running" | "done" | "error";

const GLYPH: Record<Exclude<DisplayStatus, "running">, string> = {
    done: "✓",
    error: "✗",
};

const GLYPH_COLOR: Record<DisplayStatus, string> = {
    running: theme.running,
    done: theme.success,
    error: theme.error,
};

function looksLikeDiff(text: string): boolean {
    return /^(---|\+\+\+|@@)/m.test(text);
}

function truncate(text: string, max = 60): string {
    const single = text.replace(/\s+/g, " ").trim();
    return single.length > max ? `${single.slice(0, max)}…` : single;
}

function backtick(value: string): string {
    return `\`${value}\``;
}

// ── Argument summaries ─────────────────────────────────────────────

function summarizeArgs(
    toolName: string,
    args: Record<string, unknown> | null,
): string {
    if (!args) return "";
    const pick = (keys: string[]): string => {
        for (const k of keys) {
            const v = args[k];
            if (typeof v === "string" && v.trim()) return truncate(v.trim());
            if (v != null) return truncate(String(v));
        }
        return "";
    };
    const count = (keys: string[]): string => {
        for (const k of keys) {
            const v = args[k];
            if (Array.isArray(v)) return v.length ? `${v.length} items` : "";
            if (typeof v === "object" && v != null) {
                const values = Object.values(v);
                return values.length ? `${values.length} items` : "";
            }
        }
        return "";
    };

    switch (toolName) {
        case "read":
        case "read_image":
        case "edit":
        case "write":
            return pick(["filePath", "path"]);
        case "shell":
            return pick(["command"]);
        case "code_run":
            return pick(["script_path"]) || "inline";
        case "glob":
        case "grep":
            return pick(["pattern"]);
        case "web_search":
            return pick(["query"]);
        case "web_fetch":
            return pick(["url"]);
        case "browser_use":
            return pick(["action"]);
        case "save_memory":
            return pick(["key"]);
        case "search_memory":
            return pick(["query"]);
        case "delete_memory":
            return pick(["key", "memory_id"]);
        case "list_memories":
            return pick(["scope"]);
        case "load_skill":
        case "install_skill":
            return pick(["slug", "name", "skill"]);
        case "delegate_to_agent":
            return pick(["agent_key"]);
        case "todo_write":
            return count(["todos"]);
        default:
            return "";
    }
}

// ── Result summaries ───────────────────────────────────────────────

const STATUS_MARKERS: Array<[string, keyof StatusCounts]> = [
    ["[completed]", "completed"],
    ["[in_progress]", "in_progress"],
    ["[pending]", "pending"],
    ["[cancelled]", "cancelled"],
];

type StatusCounts = {
    completed: number;
    in_progress: number;
    pending: number;
    cancelled: number;
};

function countStatuses(text: string): StatusCounts | null {
    const counts: StatusCounts = {
        completed: 0,
        in_progress: 0,
        pending: 0,
        cancelled: 0,
    };
    let matched = 0;
    for (const line of text.split("\n")) {
        for (const [marker, status] of STATUS_MARKERS) {
            if (line.includes(marker)) {
                counts[status] += 1;
                matched += 1;
                break;
            }
        }
    }
    return matched > 0 ? counts : null;
}

function summarizeOutput(toolName: string, output: string): string {
    const text = output.trim();
    if (!text) return "";
    const lines = text.split("\n").filter((l) => l.trim());

    if (DIFF_TOOLS.has(toolName) && looksLikeDiff(text)) {
        return "";
    }

    switch (toolName) {
        case "read":
            return `Read ${lines.length} lines`;
        case "write":
        case "edit":
            return "Done";
        case "shell":
        case "code_run":
            return lines.length === 1
                ? truncate(lines[0]!, 80)
                : `${lines.length} lines`;
        case "glob":
        case "grep":
            return `Found ${lines.length} matches`;
        case "web_search":
            return lines.length === 1
                ? truncate(lines[0]!, 80)
                : `${lines.length} lines`;
        case "todo_write": {
            const counts = countStatuses(text);
            if (!counts)
                return lines.length === 1 ? truncate(lines[0]!, 80) : "Done";
            return (
                `🕒 ${counts.in_progress} · ⚪ ${counts.pending} · ✅ ${counts.completed}` +
                (counts.cancelled ? ` · ❌ ${counts.cancelled}` : "")
            );
        }
        case "save_memory":
        case "delete_memory":
        case "load_skill":
        case "install_skill":
            return lines.length === 1 ? truncate(lines[0]!, 80) : "Done";
        default:
            return truncate(text, 80);
    }
}

// ── Verb-tense labels ──────────────────────────────────────────────

type LabelContext = {
    args: Record<string, unknown> | null;
};

/** Per-tool, per-state sentence. Falls back to the tool name alone. */
function labelFor(
    toolName: string,
    status: DisplayStatus,
    ctx: LabelContext,
): string {
    const pickArg = (...keys: string[]): string => {
        if (!ctx.args) return "";
        for (const key of keys) {
            const value = ctx.args[key];
            if (typeof value === "string" && value.trim())
                return value.trim().replace(/\s+/g, " ");
            if (value != null) return String(value);
        }
        return "";
    };

    switch (toolName) {
        case "shell": {
            const command = pickArg("command");
            if (!command) break;
            if (status === "running") return `Running ${backtick(command)}`;
            if (status === "error") return `\`${command}\` failed`;
            return `Ran ${backtick(command)}`;
        }
        case "code_run": {
            const script = pickArg("script_path") || "inline code";
            if (status === "running") return `Running ${script}`;
            if (status === "error") return `${script} failed`;
            return `Ran ${script}`;
        }
        case "read": {
            const filePath = pickArg("filePath", "path");
            if (!filePath) break;
            if (status === "running") return `Reading ${backtick(filePath)}`;
            return `Read ${backtick(filePath)}`;
        }
        case "read_image": {
            const filePath = pickArg("filePath");
            if (!filePath) break;
            if (status === "running") return `Reading ${backtick(filePath)}`;
            return `Read ${backtick(filePath)}`;
        }
        case "edit": {
            const filePath = pickArg("filePath");
            if (!filePath) break;
            if (status === "running") return `Editing ${backtick(filePath)}`;
            return `Edited ${backtick(filePath)}`;
        }
        case "write": {
            const filePath = pickArg("filePath", "path");
            if (!filePath) break;
            if (status === "running") return `Writing ${backtick(filePath)}`;
            return `Wrote ${backtick(filePath)}`;
        }
        case "glob": {
            const pattern = pickArg("pattern");
            if (!pattern) break;
            if (status === "running")
                return `Searching for ${backtick(pattern)}`;
            return `Searched for ${backtick(pattern)}`;
        }
        case "grep": {
            const pattern = pickArg("pattern");
            if (!pattern) break;
            if (status === "running")
                return `Searching for ${backtick(pattern)}`;
            return `Found matches for ${backtick(pattern)}`;
        }
        case "web_search": {
            const query = pickArg("query");
            if (!query) break;
            if (status === "running")
                return `Searching the web for ${backtick(query)}`;
            return `Searched the web for ${backtick(query)}`;
        }
        case "web_fetch": {
            const url = pickArg("url");
            if (!url) break;
            if (status === "running") return `Fetching ${backtick(url)}`;
            return `Fetched ${backtick(url)}`;
        }
        // These read fine with the generic name(args) form.
        case "browser_use":
        case "read_image":
        case "save_memory":
        case "search_memory":
        case "delete_memory":
        case "list_memories":
        case "load_skill":
        case "install_skill":
        case "delegate_to_agent":
        case "todo_write":
            break;
    }

    const summary = summarizeArgs(toolName, ctx.args);
    if (summary) {
        if (status === "running") return `${toolName}(${summary})…`;
        return `${toolName}(${summary})`;
    }
    return toolName;
}

// ── Component ──────────────────────────────────────────────────────

export function ToolBlock({ part }: { part: ToolCallPartData }) {
    const { toolName, status, args, outputText, error } = part;
    const displayStatus = status as DisplayStatus;
    const [frame, setFrame] = useState(0);
    useEffect(() => {
        if (status !== "running") return;
        const id = setInterval(
            () => setFrame((f) => (f + 1) % SPINNER_FRAMES.length),
            SPINNER_TICK_MS,
        );
        return () => clearInterval(id);
    }, [status]);

    const glyph =
        status === "running"
            ? SPINNER_FRAMES[frame]!
            : GLYPH[status as Exclude<ToolCallPartData["status"], "running">];

    const label = labelFor(toolName, displayStatus, { args });
    const result = summarizeOutput(toolName, outputText);

    const showDiff =
        status === "done" &&
        outputText &&
        DIFF_TOOLS.has(toolName) &&
        looksLikeDiff(outputText);

    const resultLines =
        status === "done" && result && !showDiff ? result.split("\n") : [];

    return (
        <box flexDirection="column" marginBottom={1}>
            <box flexDirection="row">
                <text
                    fg={GLYPH_COLOR[displayStatus]}
                    content={`${glyph} `}
                    flexShrink={0}
                />
                <text fg={theme.foreground} content={label} />
            </box>
            {status === "error" && error ? (
                <text fg={theme.muted} content={`  ⎿ ${truncate(error, 100)}`} />
            ) : null}
            {resultLines.map((line, index) => (
                <text key={index} fg={theme.muted} content={`  ⎿ ${line}`} />
            ))}
            {showDiff ? (
                <box paddingLeft={2} marginTop={1}>
                    <diff
                        diff={outputText}
                        view="unified"
                        showLineNumbers={false}
                    />
                </box>
            ) : null}
        </box>
    );
}
