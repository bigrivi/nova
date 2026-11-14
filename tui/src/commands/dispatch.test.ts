import { describe, expect, test } from "bun:test";

import { dispatchCommand } from "./dispatch.ts";
import { useScreenStore, type Screen } from "../stores/screen-store.ts";
import { useTabStore } from "../stores/tab-store.ts";
import { useToastStore } from "../stores/toast-store.ts";

function makeCtx() {
    const state = { exited: 0 };
    return { state, ctx: { onExit: () => { state.exited += 1; } } };
}

const SCREEN_COMMANDS: [string, Screen["kind"]][] = [
    ["sessions", "sessions"],
    ["connect", "connect-provider"],
    ["models", "models"],
    ["agents", "agents"],
    ["create-agent", "create-agent"],
    ["delete-agent", "delete-agent"],
    ["themes", "theme"],
    ["permissions", "permissions"],
    ["rewind", "rewind"],
    ["edit", "edit"],
    ["tasks", "tasks"],
    ["schedules", "schedules"],
    ["diff", "diff"],
    ["review", "review"],
    ["commit", "commit"],
    ["mcp", "mcp"],
    ["memory", "memory"],
];

describe("dispatchCommand", () => {
    test("opens the screen a command asks for", () => {
        for (const [id, kind] of SCREEN_COMMANDS) {
            dispatchCommand(id, "", { onExit: () => {} });
            expect(useScreenStore.getState().current?.kind).toBe(kind);
        }
    });

    test("ignores an unknown id without a toast", () => {
        useScreenStore.setState({ current: null });
        useToastStore.getState().hide();
        const { state, ctx } = makeCtx();
        dispatchCommand("install-skill", "", ctx);
        expect(useScreenStore.getState().current).toBeNull();
        expect(useToastStore.getState().message).toBeNull();
        expect(state.exited).toBe(0);
    });

    test("exits on quit and exit", () => {
        const { state, ctx } = makeCtx();
        dispatchCommand("quit", "", ctx);
        dispatchCommand("exit", "", ctx);
        expect(state.exited).toBe(2);
    });

    test("warns when there is no closed tab to reopen", () => {
        useTabStore.setState({ closed: [] });
        const { ctx } = makeCtx();
        dispatchCommand("reopen", "", ctx);
        expect(useToastStore.getState().message).toBe(
            "No closed tab to reopen",
        );
    });
});
