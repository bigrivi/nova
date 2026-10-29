/** Python backend process lifecycle management: spawn or reuse `python -m nova serve`, health check */
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { WORKSPACE_DIR } from "./workspace.ts";
import { setTimeout as sleep } from "node:timers/promises";
import { DEFAULT_API_BASE } from "./api/client.ts";

/** "../.." because this file lives in tui/src/ */
const PROJECT_ROOT = process.env.NOVA_PROJECT_ROOT
    ? resolve(process.env.NOVA_PROJECT_ROOT)
    : resolve(import.meta.dir, "..", "..");
const VENV_CANDIDATES = [
    join(PROJECT_ROOT, ".venv", "bin", "python3"),
];

const HEALTH_TIMEOUT_MS = 15_000;
const HEALTH_POLL_INTERVAL_MS = 300;
const STOP_GRACE_MS = 2_000;

let child: ChildProcess | null = null;

export function backendPort(): number {
    try {
        const home = process.env.NOVA_HOME || join(homedir(), ".nova");
        const raw = readFileSync(join(home, "config.json"), "utf-8");
        const port = (JSON.parse(raw) as { server?: { port?: unknown } })?.server?.port;
        const n = typeof port === "string" ? Number(port.trim()) : Number(port);
        if (Number.isInteger(n) && n >= 1 && n <= 65535) {
            return n;
        }
    } catch {
        // fall through to the default below
    }
    return Number(new URL(DEFAULT_API_BASE).port);
}

function pickPython(): string {
    // Explicit env var takes priority; otherwise probe the known venvs in order
    const explicit = process.env.NOVA_PYTHON;
    if (explicit) {
        return explicit;
    }
    for (const candidate of VENV_CANDIDATES) {
        if (existsSync(candidate)) {
            return candidate;
        }
    }
    return "python3";
}

async function waitForHealthy(baseUrl: string): Promise<void> {
    const deadline = Date.now() + HEALTH_TIMEOUT_MS;
    while (Date.now() < deadline) {
        try {
            const res = await fetch(`${baseUrl}/health`);
            if (res.ok) {
                return;
            }
        } catch {
            // backend not up yet
        }
        await sleep(HEALTH_POLL_INTERVAL_MS);
    }
    throw new Error(
        `Nova backend did not become healthy within ${HEALTH_TIMEOUT_MS}ms at ${baseUrl}`,
    );
}

/** Start the Python backend and wait for it to be healthy. Reuse an already-running instance if the health check passes. */
export async function startBackend(): Promise<void> {
    const port = backendPort();
    const baseUrl = `http://127.0.0.1:${port}`;

    // If the port is already in use and healthy, an external backend instance exists; reuse it
    try {
        const res = await fetch(`${baseUrl}/health`);
        if (res.ok) {
            return;
        }
    } catch {
        // continue to spawn
    }

    const python = pickPython();
    // Only this one line goes to the terminal; everything else goes through
    // nova's own logging program into ~/.nova/logs/nova.log.
    console.log(`Starting Nova backend on port ${port}...`);
    // Detached so the backend survives the TUI's exit: this is what lets a
    // second TUI terminal reuse it instead of spawning its own, and lets the
    // user keep working after closing the client. stdout/stderr are discarded
    // here; the backend writes its own logs to ~/.nova/logs/nova.log through
    // nova's logging program.
    child = spawn(python, ["-m", "nova", "serve"], {
        cwd: PROJECT_ROOT,
        detached: true,
        stdio: "ignore",
        env: {
            ...process.env,
            NOVA_WORKSPACE_DIR:
                WORKSPACE_DIR,
        },
    });
    child.unref();

    child.on("exit", () => {
        child = null;
    });
    child.on("error", () => {
        child = null;
    });

    try {
        await waitForHealthy(baseUrl);
    } catch (err) {
        // Race: another TUI terminal may have started the backend in the
        // meantime. If it is healthy now, reuse it instead of failing.
        try {
            const res = await fetch(`${baseUrl}/health`);
            if (res.ok) {
                if (child && child.exitCode === null) {
                    child.kill("SIGKILL");
                }
                child = null;
                return;
            }
        } catch {
            // fall through to the original error
        }
        // Spawned but never became healthy: don't leave an orphan behind.
        if (child && child.exitCode === null) {
            child.kill("SIGKILL");
        }
        child = null;
        throw err;
    }
}

/** Stop the backend child process (SIGTERM → SIGKILL after timeout). */
export async function stopBackend(): Promise<void> {
    const proc = child;
    if (!proc) {
        return;
    }
    child = null;
    if (proc.exitCode !== null) {
        return; // already exited
    }
    proc.kill("SIGTERM");
    const deadline = Date.now() + STOP_GRACE_MS;
    while (proc.exitCode === null && Date.now() < deadline) {
        await sleep(50);
    }
    if (proc.exitCode === null) {
        proc.kill("SIGKILL");
    }
}
