/** Nova TUI entry: start the backend → create the renderer → render App → exit and clean up */
import { createCliRenderer } from "@opentui/core";
import { createRoot } from "@opentui/react";
import { join } from "node:path";
import { startBackend, stopBackend } from "./backend.ts";
import { App } from "./components/App.tsx";
import { registerExtraParsers } from "./tree-sitter.ts";

if (!process.env.OTUI_ASSET_ROOT) {
    process.env.OTUI_ASSET_ROOT = join(import.meta.dir, "..", "node_modules");
}

registerExtraParsers();

let exiting = false;

async function exitApp(): Promise<void> {
    if (exiting) {
        return;
    }
    exiting = true;
    try {
        renderer?.destroy();
    } catch {
        // ignore renderer shutdown errors
    }
    await stopBackend();
    process.exit(0);
}

let renderer: Awaited<ReturnType<typeof createCliRenderer>> | null = null;

async function main(): Promise<void> {
    if (process.env.NOVA_TUI_BACKEND) {
        await startBackend();
    }

    renderer = await createCliRenderer({ exitOnCtrlC: false });
    createRoot(renderer).render(<App onExit={() => void exitApp()} />);
    renderer.start();

    const shutdown = () => void exitApp();
    process.on("SIGINT", shutdown);
    process.on("SIGTERM", shutdown);
}

main().catch((err: unknown) => {
    console.error("[tui] Fatal:", err instanceof Error ? err.message : err);
    process.exit(1);
});
