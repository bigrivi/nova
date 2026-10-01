/**
 * Persistent `conversationId -> sessionId` bindings.
 *
 * A WeChat conversation is long-lived and addressable, so its Nova session must
 * survive bridge restarts. The mapping is written on every new binding, which
 * happens at most once per conversation, and read on every turn.
 */

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import * as log from "./log.js";

/** On-disk state file shape. */
interface StoreFile {
  readonly version: 1;
  readonly bindings: Record<string, string>;
}

/**
 * Two-way map between WeChat conversations and Nova sessions.
 *
 * One session may back several conversations (a user restarting from `/clear`
 * before the old session is dropped), so the reverse index is rebuilt on load
 * rather than stored.
 */
export class SessionStore {
  private readonly byConversation = new Map<string, string>();
  private readonly bySession = new Map<string, string>();
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

  /** Record a binding in both directions. */
  private index(conversationId: string, sessionId: string): void {
    this.byConversation.set(conversationId, sessionId);
    this.bySession.set(sessionId, conversationId);
  }

  /** The Nova session bound to `conversationId`, if any. */
  sessionFor(conversationId: string): string | undefined {
    return this.byConversation.get(conversationId);
  }

  /**
   * The conversation bound to `sessionId`.
   *
   * Nova mints the real session id on the first turn, so the bridge learns it
   * from the stream rather than choosing it. This is how an incoming message is
   * routed to the right conversation when sessions are reused.
   */
  conversationFor(sessionId: string): string | undefined {
    return this.bySession.get(sessionId);
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
    const sessionId = this.byConversation.get(conversationId);
    if (sessionId !== undefined) {
      this.bySession.delete(sessionId);
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
    const { rename } = await import("node:fs/promises");
    await rename(temporary, this.statePath);
    log.debug("session state persisted", `${this.byConversation.size} binding(s)`);
  }
}