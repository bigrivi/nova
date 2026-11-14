/** Slash command dispatch: id -> action. Adding a command means adding one
 *  entry here; App.tsx does not need to change. */
import type { ComposerCommandHandler } from "../components/Composer.tsx";
import { loadModels } from "../lib/catalog.ts";
import { compactOpenSession } from "../lib/compact-session.ts";
import { errorText } from "../lib/errors.ts";
import { forkOpenSession } from "../lib/fork-session.ts";
import { closeTab, openDraftTab, reopenLastClosed } from "../lib/tab-actions.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { useCtxStore } from "../stores/ctx-store.ts";
import { useScreenStore, type Screen } from "../stores/screen-store.ts";
import { useSidebarStore } from "../stores/sidebar-store.ts";
import { useToastStore } from "../stores/toast-store.ts";
import { regenerateLastAnswer } from "../stream/chat-stream.ts";

/** Arguments that followed the command id on the composer line */
export type Args = Parameters<ComposerCommandHandler>[1];

export interface CommandContext {
    onExit: () => void;
}

export type CommandHandler = (ctx: CommandContext, args: Args) => void;

/** A handler that opens the given screen */
function openScreen(screen: Screen): CommandHandler {
    return () => {
        useScreenStore.getState().open(screen);
    };
}

/** A handler that runs an async task and reports its outcome as a toast */
function runWithToast(
    failLabel: string,
    task: () => Promise<string>,
): CommandHandler {
    return () => {
        void task()
            .then((message) => {
                useToastStore.getState().show(message, 3000);
            })
            .catch((err: unknown) => {
                useToastStore
                    .getState()
                    .show(
                        `${failLabel} failed: ${errorText(err)}`,
                        4000,
                    );
            });
    };
}

/** Variants needs the model list first: a model without reasoning efforts
 *  has nothing to show, so the screen opens only once that is ruled out. */
function openVariants(): void {
    const current = useChatStore.getState();
    void loadModels()
        .then((models) => {
            const match = models.find(
                (m) =>
                    m.provider === current.provider &&
                    m.model === current.model,
            );
            if (!match || match.efforts.length === 0) {
                useToastStore
                    .getState()
                    .show(
                        "this model has no reasoning effort levels configured",
                        3000,
                    );
                return;
            }
            useScreenStore.getState().open({ kind: "variants" });
        })
        .catch(() => {
            useScreenStore.getState().open({ kind: "variants" });
        });
}

// A Map, not an object: ids like "constructor" must not resolve to a
// prototype member.
const COMMAND_TABLE = new Map<string, CommandHandler>([
    ["new", () => openDraftTab()],
    ["close", () => closeTab()],
    [
        "reopen",
        () => {
            if (!reopenLastClosed()) {
                useToastStore
                    .getState()
                    .show("No closed tab to reopen", 3000);
            }
        },
    ],
    [
        "clear",
        () => {
            useChatStore.getState().clearMessages();
            useCtxStore.getState().clear();
        },
    ],
    ["quit", (ctx) => ctx.onExit()],
    ["exit", (ctx) => ctx.onExit()],
    ["sessions", openScreen({ kind: "sessions" })],
    ["sidebar", () => useSidebarStore.getState().toggle()],
    ["connect", openScreen({ kind: "connect-provider" })],
    ["models", openScreen({ kind: "models" })],
    ["agents", openScreen({ kind: "agents" })],
    ["create-agent", openScreen({ kind: "create-agent" })],
    ["delete-agent", openScreen({ kind: "delete-agent" })],
    ["variants", () => openVariants()],
    ["themes", openScreen({ kind: "theme" })],
    ["permissions", openScreen({ kind: "permissions" })],
    ["rewind", openScreen({ kind: "rewind" })],
    ["edit", openScreen({ kind: "edit" })],
    ["stats", openScreen({ kind: "stats" })],
    ["tasks", openScreen({ kind: "tasks" })],
    ["schedules", openScreen({ kind: "schedules" })],
    ["diff", openScreen({ kind: "diff" })],
    ["review", openScreen({ kind: "review" })],
    ["commit", openScreen({ kind: "commit" })],
    ["mcp", openScreen({ kind: "mcp" })],
    ["memory", openScreen({ kind: "memory" })],
    ["fork", runWithToast("Fork", forkOpenSession)],
    [
        "regenerate",
        () => {
            void regenerateLastAnswer();
        },
    ],
    ["compact", runWithToast("Compact", compactOpenSession)],
]);

/** Run the command behind an id; unknown ids are ignored on purpose
 *  (/install-skill and friends are not implemented yet). */
export function dispatchCommand(
    id: string,
    args: Args,
    ctx: CommandContext,
): void {
    COMMAND_TABLE.get(id)?.(ctx, args);
}
