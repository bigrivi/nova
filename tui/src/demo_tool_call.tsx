#!/usr/bin/env bun
/**
 * Demo: every tool-call rendering state in the TUI, one scrollable page.
 *
 * Mirrors nova/cli/demo/demo_tool_call.py (Textual) for the React/opentui
 * version: the same tool categories and fixtures rendered through ToolBlock,
 * plus the running spinner, error states, diff rendering and a thinking
 * indicator, so all visual states can be reviewed side by side.
 *
 * Keys: q quit / Esc quit
 *
 * Run: bun run src/demo_tool_call.tsx
 */
import { createCliRenderer } from "@opentui/core";
import { createRoot, useKeyboard } from "@opentui/react";
import { join } from "node:path";
import { ThinkingSpinner } from "./components/parts/ThinkingSpinner.tsx";
import { theme } from "./theme.ts";
import { ToolBlock } from "./components/ToolBlock.tsx";
import type { ToolCallPart as ToolCallPartData } from "./stores/chat-store.ts";

if (!process.env.OTUI_ASSET_ROOT) {
    process.env.OTUI_ASSET_ROOT = join(import.meta.dir, "..", "node_modules");
}

function part(
    overrides: Partial<ToolCallPartData> & {
        toolName: string;
        args?: Record<string, unknown>;
    },
): ToolCallPartData {
    return {
        type: "tool-call",
        toolCallId: `demo-${overrides.toolName}-${Math.random().toString(36).slice(2)}`,
        argsText: JSON.stringify(overrides.args ?? {}),
        outputText: "",
        status: "done",
        ...overrides,
    } as ToolCallPartData;
}

const CATEGORIES: Array<{
    label: string;
    entries: ToolCallPartData[];
}> = [
    {
        label: "Code & File",
        entries: [
            part({
                toolName: "shell",
                args: { command: "ls -la", description: "List files" },
                outputText:
                    "total 42\n-rw-r--r--  1 user staff 123 Jan 1 00:00 main.py\n-rw-r--r--  1 user staff 456 Jan 1 00:00 utils.py",
            }),
            part({
                toolName: "shell",
                args: { command: "cat nonexistent.txt", description: "Read missing file" },
                status: "error",
                error: "cat: nonexistent.txt: No such file or directory",
            }),
            part({
                toolName: "code_run",
                args: { code: "print('hello')", description: "Print greeting" },
                outputText: "hello",
            }),
            part({
                toolName: "code_run",
                args: { code: "1/0", description: "Division by zero" },
                status: "error",
                error: 'ZeroDivisionError: division by zero',
            }),
            part({
                toolName: "read",
                args: { filePath: "src/main.py", limit: 50 },
                outputText: Array.from({ length: 50 }, (_, i) => `line ${i + 1}`).join("\n"),
            }),
            part({
                toolName: "edit",
                args: { filePath: "src/main.py", oldString: "old code", newString: "new code" },
                outputText: [
                    "--- a/main.py",
                    "+++ b/main.py",
                    "@@ -1,3 +1,3 @@",
                    '-"""Application entry point."""',
                    '+"""Application entry point with logging."""',
                    "+import logging",
                    "+logger = logging.getLogger(__name__)",
                ].join("\n"),
            }),
            part({
                toolName: "write",
                args: { filePath: "src/new.py", content: "print('hi')" },
                outputText: "Created src/new.py",
            }),
            part({
                toolName: "write_files",
                args: { files: ["a.py", "b.py"] },
                outputText: "Created a.py\nCreated b.py",
            }),
        ],
    },
    {
        label: "Search",
        entries: [
            part({
                toolName: "glob",
                args: { pattern: "*.py", path: "src/" },
                outputText: "src/main.py\nsrc/utils.py",
            }),
            part({
                toolName: "grep",
                args: { pattern: "def main", include: "*.py" },
                outputText: "src/main.py:4:def main():",
            }),
            part({
                toolName: "web_search",
                args: { query: "python async tutorial", description: "Search async tutorials" },
                outputText:
                    "Title: asyncio — Python docs\nURL: https://docs.python.org/3/library/asyncio.html\n---\nTitle: Async Guide\nURL: https://example.com/guide",
            }),
            part({
                toolName: "web_fetch",
                args: { url: "https://example.com" },
                outputText: "# Page Title\n\nContent here...",
            }),
        ],
    },
    {
        label: "Memory",
        entries: [
            part({
                toolName: "save_memory",
                args: { key: "user_name", content: "Alice", scope: "user" },
            }),
            part({
                toolName: "search_memory",
                args: { query: "preferences", scope: "all", limit: 5 },
                outputText: "mem_001: user name: Alice\nmem_002: prefers dark mode",
            }),
            part({ toolName: "delete_memory", args: { key: "mem_123" } }),
            part({
                toolName: "list_memories",
                args: { scope: "all", limit: 20 },
                outputText: "mem_001: user name: Alice\nmem_002: prefers dark mode",
            }),
        ],
    },
    {
        label: "Skills",
        entries: [
            part({ toolName: "list_skills", args: {}, outputText: "code-review\nrefactor" }),
            part({ toolName: "load_skill", args: { name: "code-review" }, outputText: "loaded" }),
            part({
                toolName: "install_skill",
                args: { slug: "team/review-skill" },
                outputText: "installed",
            }),
        ],
    },
    {
        label: "Browser",
        entries: [
            part({
                toolName: "browser_use",
                args: { action: "go_to_url", url: "https://docs.python.org" },
                outputText: "navigated",
            }),
            part({ toolName: "browser_use", args: { action: "click_element", index: 3 } }),
            part({
                toolName: "browser_use",
                args: { action: "input_text", index: 2, text: "async await" },
            }),
            part({
                toolName: "browser_use",
                args: { action: "web_search", query: "python async tutorial" },
            }),
            part({ toolName: "browser_use", args: { action: "scroll_down", scroll_amount: 300 } }),
            part({ toolName: "browser_use", args: { action: "scroll_up" } }),
            part({ toolName: "browser_use", args: { action: "go_back" } }),
            part({ toolName: "browser_use", args: { action: "wait", seconds: 2 } }),
            part({
                toolName: "browser_use",
                args: { action: "extract_content", goal: "main content" },
                outputText: "extracted 2 sections",
            }),
            part({ toolName: "browser_use", args: { action: "switch_tab", tab_id: 1 } }),
            part({ toolName: "browser_use", args: { action: "open_tab", url: "https://pypi.org" } }),
            part({ toolName: "browser_use", args: { action: "close_tab" } }),
            part({ toolName: "browser_use", args: { action: "send_keys", keys: "Ctrl+F" } }),
            part({ toolName: "browser_use", args: { action: "get_state" },
                outputText: "https://docs.python.org/3/\n[0] link: Python Docs\n[1] button: Search",
            }),
            part({ toolName: "browser_use", args: { action: "cleanup" } }),
        ],
    },
    {
        label: "Other",
        entries: [
            part({ toolName: "read_image", args: { filePath: "/path/to/screenshot.png" },
                outputText: "Read image 800x600" }),
            part({
                toolName: "todo_write",
                args: {
                    todos: [
                        { content: "Fix the login bug on the auth page", status: "in_progress", priority: "high" },
                        { content: "Write unit tests for auth flow", status: "pending", priority: "medium" },
                        { content: "Document the public API endpoints", status: "completed", priority: "low" },
                    ],
                },
                outputText:
                    "## Tasks\n1. 🕒 [in_progress] Fix the login bug on the auth page\n2. ⚪ [pending] Write unit tests for auth flow\n3. ✅ [completed] Document the public API endpoints",
            }),
            part({
                toolName: "delegate_to_agent",
                args: { agent_key: "code-review", task: "Review the PR", timeout: 300 },
                outputText: "Code review complete. Found 2 issues.",
            }),
        ],
    },
];

const RUNNING_SAMPLES = [
    ...["shell", "read", "web_search"].map((name) =>
        part({
            toolName: name,
            args: { command: "sleep 2", filePath: "big.log", query: "state" },
            status: "running",
        }),
    ),
    part({
        toolName: "shell",
        args: { command: "rm -rf dist", description: "Clean build output" },
        status: "blocked",
        error: "Waiting for your approval",
    }),
];

function CategoryLabel({ children }: { children: string }) {
    return (
        <text fg={theme.accent} marginTop={1}>
            ▌{children}
        </text>
    );
}

function DemoApp() {
    useKeyboard((key) => {
        if (key.name === "q" || key.name === "escape") process.exit(0);
    });

    return (
        <box flexDirection="column" padding={1} flexGrow={1}>
            <text fg={theme.foreground}>
                Demo: tool call rendering — q to quit
            </text>
            <text fg={theme.muted}>
                Verb-tense labels · glyph-only coloring · per-tool sentences
            </text>
            <scrollbox flexGrow={1} scrollY viewportCulling>
            <CategoryLabel>Running (spinner)</CategoryLabel>
            <box flexDirection="column" paddingLeft={1}>
                {RUNNING_SAMPLES.map((p) => (
                    <ToolBlock key={p.toolCallId} part={p} />
                ))}
            </box>
            <CategoryLabel>Thinking indicator</CategoryLabel>
            <box paddingLeft={1}>
                <ThinkingSpinner />
            </box>
                {CATEGORIES.map(({ label, entries }) => (
                    <box key={label} flexDirection="column">
                        <CategoryLabel>{label}</CategoryLabel>
                        <box flexDirection="column" paddingLeft={1}>
                            {entries.map((entry) => (
                                <ToolBlock key={entry.toolCallId} part={entry} />
                            ))}
                        </box>
                    </box>
                ))}
            </scrollbox>
        </box>
    );
}

async function main(): Promise<void> {
    const renderer = await createCliRenderer({ exitOnCtrlC: false });
    createRoot(renderer).render(<DemoApp />);
    renderer.start();
    process.on("SIGINT", () => process.exit(0));
}

main().catch((err: unknown) => {
    console.error("[demo] Fatal:", err instanceof Error ? err.message : err);
    process.exit(1);
});
