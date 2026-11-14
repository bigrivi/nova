/** Python backend process lifecycle: reuse the backend that recorded itself,
 *  or start the shared one and use the address it announces on stdout.
 *
 *  A backend is started only when no recorded one is alive and answering, so a
 *  second launch joins the first instead of leaving another server behind.
 *  Neither check is an HTTP request: asking a loopback address "are you there?"
 *  is exactly the request an environment proxy turns into a 502, and a client
 *  that reads that answer as "no backend" starts a duplicate on every launch.
 *  A file, a pipe and a TCP connect cannot be proxied.
 */

import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { connect } from "node:net";
import { join, resolve } from "node:path";
import type { Readable } from "node:stream";
import { setTimeout as sleep } from "node:timers/promises";
import { setApiBase } from "./api/client.ts";
import { backendPort, novaHome } from "./api/port.ts";
import { WORKSPACE_DIR } from "./workspace.ts";

/** "../.." because this file lives in tui/src/ */
const PROJECT_ROOT = process.env.NOVA_PROJECT_ROOT
    ? resolve(process.env.NOVA_PROJECT_ROOT)
    : resolve(import.meta.dir, "..", "..");
const VENV_CANDIDATES = [
    join(PROJECT_ROOT, ".venv", "bin", "python3"),
];
/** The built web UI, so the shared backend serves it to a browser too. */
const FRONTEND_DIST = join(PROJECT_ROOT, "frontend", "dist");

const REGISTRATION = "server.json";
const ANNOUNCE_TIMEOUT_MS = 20_000;
const STOP_GRACE_MS = 2_000;

let child: ChildProcess | null = null;

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

export type Registration = { url: string; pid: number };

/** The backend another process recorded, or null when the record is unusable. */
export function readRegistration(home = novaHome()): Registration | null {
    try {
        const raw = readFileSync(join(home, REGISTRATION), "utf-8");
        return parseRegistration(JSON.parse(raw));
    } catch {
        // No record, or one written by an older version: start a backend.
        return null;
    }
}

/** Read a record's fields, rejecting anything that is not a usable address. */
export function parseRegistration(payload: unknown): Registration | null {
    const record = payload as { url?: unknown; pid?: unknown } | null;
    const pid = Number(record?.pid);
    if (typeof record?.url !== "string" || !Number.isInteger(pid) || pid <= 0) {
        return null;
    }
    return { url: record.url, pid };
}

/** Whether a process still exists. Signal zero only asks the kernel. */
function isAlive(pid: number): boolean {
    try {
        process.kill(pid, 0);
        return true;
    } catch {
        return false;
    }
}

/** Whether something accepts connections at this address.
 *
 *  A bare TCP connect, not a request: `fetch` to a loopback address goes
 *  through `http_proxy` when the environment names one, and the proxy answers
 *  502 for it. That answer means "no backend" only to a client that has
 *  already given up, and it made every launch start a second backend.
 */
export async function isListening(
    url: string,
    timeoutMs = 1_000,
): Promise<boolean> {
    let target: URL;
    try {
        target = new URL(url);
    } catch {
        return false;
    }
    const port = Number(target.port);
    if (!Number.isInteger(port) || port <= 0) {
        return false;
    }
    return await new Promise((resolve) => {
        const socket = connect({ host: target.hostname, port });
        const settle = (open: boolean): void => {
            socket.destroy();
            resolve(open);
        };
        socket.setTimeout(timeoutMs, () => settle(false));
        socket.once("connect", () => settle(true));
        socket.once("error", () => settle(false));
    });
}

/** The address the backend prints once it is serving, or null on timeout. */
export async function readAnnouncement(
    stdout: Readable | null,
    timeoutMs = ANNOUNCE_TIMEOUT_MS,
): Promise<string | null> {
    if (stdout === null) {
        return null;
    }
    return await new Promise((resolve) => {
        let buffer = "";
        let settled = false;
        const finish = (url: string | null): void => {
            if (settled) {
                return;
            }
            settled = true;
            clearTimeout(timer);
            resolve(url);
        };
        const timer = setTimeout(() => finish(null), timeoutMs);
        // Left attached after settling on purpose: it keeps the pipe drained so
        // the backend never blocks writing to a reader that stopped reading.
        stdout.setEncoding("utf8");
        stdout.on("data", (chunk: string) => {
            buffer += chunk;
            const end = buffer.indexOf("\n");
            if (end === -1) {
                return;
            }
            try {
                const payload = JSON.parse(buffer.slice(0, end)) as {
                    url?: unknown;
                };
                finish(typeof payload.url === "string" ? payload.url : null);
            } catch {
                finish(null);
            }
        });
        stdout.on("end", () => finish(null));
        stdout.on("error", () => finish(null));
    });
}

async function spawnBackend(): Promise<string | null> {
    const python = pickPython();
    // Only this one line goes to the terminal; everything else goes through
    // nova's own logging program into ~/.nova/logs/nova.log.
    console.log("Starting Nova backend...");
    // Detached so the backend survives the TUI's exit: this is what lets a
    // second TUI terminal reuse it instead of spawning its own, and lets the
    // user keep working after closing the client. Announcing the address is
    // what makes that true for the other surfaces too: one backend per
    // NOVA_HOME, joined by the web client and the desktop window as well.
    child = spawn(python, ["-m", "nova", "serve", "--announce"], {
        cwd: PROJECT_ROOT,
        detached: true,
        stdio: ["ignore", "pipe", "ignore"],
        env: {
            ...process.env,
            NOVA_WORKSPACE_DIR: WORKSPACE_DIR,
            ...(existsSync(join(FRONTEND_DIST, "index.html"))
                ? { NOVA_FRONTEND_DIST: FRONTEND_DIST }
                : {}),
        },
    });
    child.unref();
    child.on("exit", () => {
        child = null;
    });
    child.on("error", () => {
        child = null;
    });
    return await readAnnouncement(child.stdout);
}

/** Point the API client at a backend, reusing one when possible.
 *
 *  Never throws: a client that cannot learn the address still starts and
 *  reports the failure per request, instead of exiting over it.
 *
 *  shortcut: two clients launched in the same second both see no record and
 *  both start a backend. A lock file around the spawn is what closes that;
 *  until then the record only dedupes launches that do not overlap.
 */
export async function startBackend(): Promise<void> {
    const registered = readRegistration();
    if (
        registered !== null &&
        isAlive(registered.pid) &&
        (await isListening(registered.url))
    ) {
        setApiBase(registered.url);
        return;
    }

    const announced = await spawnBackend();
    if (announced !== null) {
        setApiBase(announced);
        return;
    }

    setApiBase(`http://127.0.0.1:${backendPort()}`);
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
