/**
 * Persistent `<agentKey>/<conversationId> -> sessionId` bindings.
 *
 * A WeChat conversation is long-lived and addressable, so its Nova session must
 * survive bridge restarts. The mapping is written on every new binding, which
 * happens at most once per conversation, and read on every turn.
 *
 * Both halves of the key are load-bearing: one agent serves every sender, so the
 * conversation half keeps senders apart, and every sender reaches every agent
 * under the same `conversationId`, so the agent half keeps two personas from
 * reading each other's history.
 */

import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import * as log from "./log.js";

/** On-disk state file shape. */
interface StoreFile {
  readonly version: 1;
  readonly bindings: Record<string, string>;
}

export class SessionStore {
  private readonly byConversation = new Map<string, string>();
  private loaded = false;

  constructor(private readonly statePath: string) {}

  /** Read the state file, tolerating absence and malformed content. */
  async load(): Promise<void> {
    this.loaded = true;
    let raw: string;
    try {
      raw = await readFile(this.statePath, "utf8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        log.warn("session state unreadable, starting empty", String(error));
      }
      return;
    }
    try {
      const parsed: unknown = JSON.parse(raw);
      if (typeof parsed !== "object" || parsed === null) {
        log.warn("session state malformed, starting empty");
        return;
      }
      const bindings = (parsed as StoreFile).bindings;
      if (typeof bindings !== "object" || bindings === null) {
        return;
      }
      for (const [conversationId, sessionId] of Object.entries(bindings)) {
        if (typeof sessionId === "string" && sessionId) {
          this.index(conversationId, sessionId);
        }
      }
      log.info(`session state loaded: ${this.byConversation.size} binding(s)`);
    } catch (error) {
      log.warn("session state is not valid JSON, starting empty", String(error));
    }
  }

  /** Record a binding. */
  private index(conversationId: string, sessionId: string): void {
    this.byConversation.set(conversationId, sessionId);
  }

  /** The Nova session bound to `conversationId`, if any. */
  sessionFor(conversationId: string): string | undefined {
    return this.byConversation.get(conversationId);
  }

  /** Learn a conversation's session id and persist the binding. */
  async bind(conversationId: string, sessionId: string): Promise<void> {
    if (!this.loaded) {
      throw new Error("SessionStore.load() must run before bind()");
    }
    const existing = this.byConversation.get(conversationId);
    if (existing === sessionId) {
      return;
    }
    this.index(conversationId, sessionId);
    await this.persist();
  }

  /** Drop a conversation's binding, leaving Nova's session itself intact. */
  async forget(conversationId: string): Promise<void> {
    if (!this.byConversation.delete(conversationId)) {
      return;
    }
    await this.persist();
  }

  /** Write the state file atomically so a crash cannot truncate it. */
  private async persist(): Promise<void> {
    const payload: StoreFile = {
      version: 1,
      bindings: Object.fromEntries(this.byConversation),
    };
    await mkdir(dirname(this.statePath), { recursive: true });
    const temporary = `${this.statePath}.tmp`;
    await writeFile(temporary, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
    await rename(temporary, this.statePath);
    log.debug("session state persisted", `${this.byConversation.size} binding(s)`);
  }
}