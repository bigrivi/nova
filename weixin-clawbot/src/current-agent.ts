/**
 * Which agent each conversation is talking to.
 *
 * WeChat allows one ClawBot per account, so the agent cannot be inferred from
 * which bot received the message -- the user picks it with `/agent`. Each agent
 * keeps its own session store and outbox, so switching is the same as opening a
 * separate conversation with that agent, and switching back resumes it.
 *
 * Persisted so a restart does not silently drop the user back into the default.
 */

import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import * as log from "./log.js";

/** On-disk shape of the per-conversation current-agent file. */
interface CurrentFile {
    readonly version: 1;
    /** conversationId -> the agent that conversation is talking to. */
    readonly current: Record<string, string>;
}

export class CurrentAgentStore {
    private readonly current = new Map<string, string>();

    constructor(private readonly path: string) {}

    /** Read the file, tolerating absence and corruption. */
    async load(): Promise<void> {
        try {
            const parsed: unknown = JSON.parse(await readFile(this.path, "utf8"));
            if (typeof parsed !== "object" || parsed === null) {
                return;
            }
            const current = (parsed as CurrentFile).current;
            if (typeof current !== "object" || current === null) {
                return;
            }
            for (const [conversationId, agentKey] of Object.entries(current)) {
                if (typeof agentKey === "string" && agentKey) {
                    this.current.set(conversationId, agentKey);
                }
            }
            log.info(`current agents loaded: ${this.current.size}`);
        } catch {
            // A missing file is the normal first-run case.
        }
    }

    /** The agent this conversation selected, if any. */
    get(conversationId: string): string | undefined {
        return this.current.get(conversationId);
    }

    /** Record the choice and persist it atomically. */
    async set(conversationId: string, agentKey: string): Promise<void> {
        this.current.set(conversationId, agentKey);
        const payload: CurrentFile = {
            version: 1,
            current: Object.fromEntries(this.current),
        };
        await mkdir(dirname(this.path), { recursive: true });
        const temporary = `${this.path}.tmp`;
        await writeFile(temporary, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
        await rename(temporary, this.path);
    }
}
