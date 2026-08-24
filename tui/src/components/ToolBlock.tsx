/** Tool call block (Claude Code style): single-line title + single-line result summary, no multi-line expansion */
import { useEffect, useState } from "react";
import type { ToolCallPart as ToolCallPartData } from "../stores/chat-store.ts";

const DIFF_TOOLS = new Set(["edit", "write", "write_files", "code_run"]);

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const SPINNER_TICK_MS = 80;

const STATUS_ICON: Record<
    Exclude<ToolCallPartData["status"], "running">,
    string
> = {
    done: "◉",
    error: "✗",
};

const STATUS_COLOR: Record<ToolCallPartData["status"], string> = {
    running: "#d29922",
    done: "#8b949e",
    error: "#e5534b",
};

function looksLikeDiff(text: string): boolean {
    return /^(---|\+\+\+|@@)/m.test(text);
}

const STATUS_MARKERS: Array<[string, keyof StatusCounts]> = [
    ["[completed]", "completed"],
    ["✅", "completed"],
    ["[in_progress]", "in_progress"],
    ["🕒", "in_progress"],
    ["[pending]", "pending"],
    ["⚪", "pending"],
    ["[cancelled]", "cancelled"],
    ["❌", "cancelled"],
];

type StatusCounts = {
    completed: number;
    in_progress: number;
    pending: number;
    cancelled: number;
};

/** Count task statuses from the backend's markdown todo listing. */
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

function truncate(text: string, max = 60): string {
    const single = text.replace(/\s+/g, " ").trim();
    return single.length > max ? `${single.slice(0, max)}…` : single;
}

/** Single-line argument summary: extract the key fields into a Claude Code-style (file.py) / (query) */
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

/** Single-line result summary (Claude Code style): line count / first-line truncation / error message */
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
            if (!counts) return lines.length === 1 ? truncate(lines[0]!, 80) : "Done";
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

export function ToolBlock({ part }: { part: ToolCallPartData }) {
    const { toolName, status, args, outputText, error } = part;
    const [frame, setFrame] = useState(0);
    useEffect(() => {
        if (status !== "running") return;
        const id = setInterval(
            () => setFrame((f) => (f + 1) % SPINNER_FRAMES.length),
            SPINNER_TICK_MS,
        );
        return () => clearInterval(id);
    }, [status]);
    const color = STATUS_COLOR[status];
    const icon =
        status === "running" ? SPINNER_FRAMES[frame]! : STATUS_ICON[status];
    const summary = summarizeArgs(toolName, args);
    const label = summary ? `${toolName}(${summary})` : toolName;
    const result = summarizeOutput(toolName, outputText);

    const showDiff =
        status === "done" &&
        outputText &&
        DIFF_TOOLS.has(toolName) &&
        looksLikeDiff(outputText);

    return (
        <box flexDirection="column" marginBottom={1}>
            <text fg={color} content={`${icon} ${label}`} />
            {status === "error" && error ? (
                <text fg="#e5534b" content={`  ⎿ ${truncate(error, 100)}`} />
            ) : null}
            {status === "done" && result ? (
                <text fg="#6e7681" content={`  ⎿ ${result}`} />
            ) : null}
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
