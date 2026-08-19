/** Python backend process lifecycle management: spawn `python -m nova serve`, health check, exit cleanup */
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, openSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import { DEFAULT_API_BASE } from "./api/nova-api.ts";

const PROJECT_ROOT = "/Users/andy/Workspace/codes/ai/nova";
/** Prefer the user's daily venv (Python 3.12); fall back to the project .venv; finally the system python3 */
const VENV_CANDIDATES = [
    "/Users/andy/Workspace/codes/python/venvs/ai/bin/python3",
    `${PROJECT_ROOT}/.venv/bin/python3`,
];

const HEALTH_TIMEOUT_MS = 15_000;
const HEALTH_POLL_INTERVAL_MS = 300;
const STOP_GRACE_MS = 2_000;

let child: ChildProcess | null = null;

export function backendPort(): number {
    return Number(
        process.env.NOVA_BACKEND_PORT ?? new URL(DEFAULT_API_BASE).port,
    );
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

/** Backend log file: keep uvicorn access logs from polluting the TUI terminal rendering */
function backendLogPath(): string {
    const home = process.env.NOVA_HOME || join(homedir(), ".nova");
    const dir = join(home, "logs");
    try {
        mkdirSync(dir, { recursive: true });
    } catch {
        // Fall back to the current directory if the log directory is unavailable
        return "nova-tui-backend.log";
    }
    return join(dir, "nova-tui-backend.log");
}

/** Start the Python backend and wait for it to be healthy. Reuse an already-running instance if the health check passes. */
export async function startBackend(): Promise<void> {
    const port = backendPort();
    const baseUrl = `http://127.0.0.1:${port}`;

    // If the port is already in use and healthy, an external backend instance exists; reuse it
    try {
        const res = await fetch(`${baseUrl}/health`);
        if (res.ok) {
            console.log(`[tui] Reusing existing Nova backend at ${baseUrl}`);
            return;
        }
    } catch {
        // continue to spawn
    }

    const python = pickPython();
    const logPath = backendLogPath();
    console.log(
        `[tui] Starting Nova backend (${python} -m nova serve) on port ${port} (logs: ${logPath})`,
    );
    const logFd = openSync(logPath, "a");
    child = spawn(python, ["-m", "nova", "serve"], {
        cwd: PROJECT_ROOT,
        // Redirect stdout/stderr to the log file to keep the terminal clean
        stdio: ["ignore", logFd, logFd],
        env: { ...process.env, NOVA_BACKEND_PORT: String(port) },
    });

    child.on("exit", (code) => {
        if (child && !child.killed) {
            console.log(
                `[tui] Backend exited with code ${code} (logs: ${logPath})`,
            );
        }
        child = null;
    });
    child.on("error", (err) => {
        console.error(`[tui] Failed to spawn backend: ${err.message}`);
    });

    await waitForHealthy(baseUrl);
    console.log(`[tui] Backend ready at ${baseUrl}`);
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
