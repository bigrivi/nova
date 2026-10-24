/** Theme preference persistence: a tiny JSON file under $NOVA_HOME.
 *
 * Kept out of the React context so the read/write contract is testable and the
 * provider only owns state, not disk access.
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { themes } from "./index.ts";

export type ThemePreference = string; // theme name or "system"

const DEFAULT_PREFERENCE = "system";

/** $NOVA_HOME/tui-theme.json, resolved at call time so tests can redirect it. */
export function preferencePath(): string {
    return join(
        process.env.NOVA_HOME || join(homedir(), ".nova"),
        "tui-theme.json",
    );
}

function isKnown(value: unknown): value is ThemePreference {
    return value === "system" || (typeof value === "string" && value in themes);
}

/** Read the saved preference, falling back to `system`. */
export function readPreference(): ThemePreference {
    try {
        const raw = readFileSync(preferencePath(), "utf-8");
        const value = JSON.parse(raw)?.preference;
        if (isKnown(value)) return value;
    } catch {
        // Missing or malformed file: use the default.
    }
    return DEFAULT_PREFERENCE;
}

/** Persist the preference, ignoring filesystem failures. */
export function writePreference(preference: ThemePreference): void {
    try {
        mkdirSync(join(process.env.NOVA_HOME || join(homedir(), ".nova")), {
            recursive: true,
        });
        writeFileSync(preferencePath(), JSON.stringify({ preference }));
    } catch {
        // A failed write must not break the UI.
    }
}
