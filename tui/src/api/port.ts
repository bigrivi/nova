/** The port Nova's server listens on.
 *
 * The configuration the user wrote is the truth: a server started from it
 * binds that port, so the client has to talk to the same one. Reading the
 * port in two places is how the client ended up asking 8765 while the server
 * listened on 8794, and every screen answered "Unable to connect".
 *
 * This lives apart from both callers: the API client needs it and the backend
 * supervisor needs it, and one importing the other would be a cycle.
 */

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

/** The port Nova uses when the configuration names none. */
export const DEFAULT_API_PORT = 8765;

/** The port from `server.port` in the configuration, or the default. */
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
        // No configuration, or one that names no port: the default below.
    }
    return DEFAULT_API_PORT;
}
