/** Where Nova keeps its state, and the port a backend would use if it bound
 *  the configured one.
 *
 * A backend started here is asked for port zero and announces the port it got,
 * so this is only the fallback for a backend whose address could not be
 * learned. Reading the port in two places is how the client ended up asking
 * 8765 while the server listened on 8794, and every screen answered "Unable to
 * connect".
 *
 * This lives apart from both callers: the API client needs it and the backend
 * supervisor needs it, and one importing the other would be a cycle.
 */

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

/** The port Nova uses when the configuration names none. */
export const DEFAULT_API_PORT = 51789;

/** The state directory: `$NOVA_HOME`, or `~/.nova`. */
export function novaHome(): string {
    return process.env.NOVA_HOME || join(homedir(), ".nova");
}

/** The port from `server.port` in the configuration, or the default. */
export function backendPort(): number {
    try {
        const raw = readFileSync(join(novaHome(), "config.json"), "utf-8");
        const port = (JSON.parse(raw) as { server?: { port?: unknown } })?.server?.port;
        const n = typeof port === "string" ? Number(port.trim()) : Number(port);
        if (Number.isInteger(n) && n >= 1 && n <= 65535) {
            return n;
        }
    } catch {
        // No configuration, or one that names no port: the default below.
    }
    return DEFAULT_API_PORT;
}
