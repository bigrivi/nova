/**
 * One turn at a time, across every agent in the process.
 *
 * The agents share one workspace -- `NOVA_WORKSPACE_DIR` is a single setting and
 * Nova's shell and file tools resolve against it -- so two agents running at once
 * would be two agents racing on the same files. The gate is therefore
 * process-wide rather than per agent.
 *
 * It is also what makes outbox attribution safe: only one turn can be producing
 * files at a time, so a file belongs unambiguously to whoever is running.
 */

/** Outcome of asking for the turn slot. */
export type GateResult =
  | { readonly acquired: true; readonly controller: AbortController }
  | { readonly acquired: false; readonly mine: boolean; readonly holder: string };

/** Why a key is unique: the same WeChat user reaches several agents by bot. */
export function turnKey(namespace: string, conversationId: string): string {
  return `${namespace}/${conversationId}`;
}

export class TurnGate {
  private current: { key: string; controller: AbortController } | null = null;

  /**
   * Take the slot, or report who holds it.
   *
   * `mine` distinguishes "you already have a turn running" from "someone else
   * does", because the two need different advice.
   */
  acquire(key: string): GateResult {
    if (this.current === null) {
      const controller = new AbortController();
      this.current = { key, controller };
      return { acquired: true, controller };
    }
    if (this.current.key === key) {
      // Re-entrant: hand back the same controller so /stop still reaches it.
      return { acquired: false, mine: true, holder: key };
    }
    return { acquired: false, mine: false, holder: this.current.key };
  }

  /** Release the slot, but only for the key that holds it. */
  release(key: string): void {
    if (this.current !== null && this.current.key === key) {
      this.current = null;
    }
  }

  /** The key currently holding the slot, if any. */
  holder(): string | null {
    return this.current?.key ?? null;
  }

  /** Abort the holder, whoever it is. Used at shutdown. */
  abortAll(): void {
    this.current?.controller.abort();
    this.current = null;
  }
}