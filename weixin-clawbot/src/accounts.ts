/**
 * The one WeChat bot this bridge serves.
 *
 * WeChat allows a single ClawBot per account, and scanning a second QR replaces
 * the first -- the superseded bot's token is rejected with `errcode -14` the
 * moment the new one binds. So there is exactly one account to remember, and the
 * agent is chosen in-band with `/agent` (see `current-agent.ts`) rather than by
 * which bot received the message.
 *
 * The SDK's own index is not trusted: `registerWeixinAccountId` rewrites
 * `accounts.json` to a single-element array, and `isLoggedIn()` plus a bare
 * `start()` read only that. It is written back here purely so other tooling sees
 * the account. Nothing in this module deletes an account -- rebinding must never
 * cost a working bot, and `logout()` would wipe every one of them.
 */

import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import * as log from "./log.js";

/** On-disk shape of the bridge's own account file. */
interface AccountFile {
  readonly version: 1;
  /** The `ilink_bot_id` of the bound bot. */
  readonly accountId: string;
}

/** What a read of the account file found. */
export type BoundAccount =
  | { readonly kind: "bound"; readonly accountId: string }
  /**
   * A file from the earlier per-agent design, which recorded a bot per Nova
   * agent. That is not a shape this bridge can honour, and guessing which of the
   * entries WeChat still considers live would be worse than asking for a rescan.
   */
  | { readonly kind: "legacy" }
  | { readonly kind: "unbound" };

/** State directory the SDK reads, mirroring its own resolution order. */
function stateDir(): string {
  return (
    process.env.OPENCLAW_STATE_DIR?.trim() ||
    process.env.CLAWDBOT_STATE_DIR?.trim() ||
    join(homedir(), ".openclaw")
  );
}

/** The SDK's account index, which it rewrites to a single entry per login. */
function indexPath(): string {
  return join(stateDir(), "openclaw-weixin", "accounts.json");
}

/**
 * Read the bound account, telling a stale file apart from a missing one.
 *
 * `legacyPath` is the earlier per-agent file. It is checked only when the current
 * one says nothing, so an upgrade that has not re-bound yet is recognised rather
 * than silently ignored -- the fallback to the SDK's index would otherwise appear
 * to work, right up until it picked a bot WeChat had already replaced.
 */
export async function readBoundAccount(
  path: string,
  legacyPath?: string,
): Promise<BoundAccount> {
  const current = await readAccountFile(path);
  if (current.kind !== "unbound") {
    return current;
  }
  if (legacyPath === undefined) {
    return current;
  }
  return (await readAccountFile(legacyPath)).kind === "legacy"
    ? { kind: "legacy" }
    : current;
}

/** Classify one account file's contents. */
async function readAccountFile(path: string): Promise<BoundAccount> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(await readFile(path, "utf8"));
  } catch {
    return { kind: "unbound" };
  }
  if (typeof parsed !== "object" || parsed === null) {
    return { kind: "unbound" };
  }
  const record = parsed as Record<string, unknown>;
  if (typeof record["bindings"] === "object" && record["bindings"] !== null) {
    return { kind: "legacy" };
  }
  const accountId = record["accountId"];
  return typeof accountId === "string" && accountId.trim() !== ""
    ? { kind: "bound", accountId }
    : { kind: "unbound" };
}

/** Record the bound account atomically, then put it back in the SDK index. */
export async function writeBoundAccount(
  path: string,
  accountId: string,
): Promise<void> {
  const payload: AccountFile = { version: 1, accountId };
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.tmp`;
  await writeFile(temporary, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  await rename(temporary, path);
  log.info(`bound bot ${accountId}`);

  await syncIndex(accountId);
}

/**
 * Write the SDK index so it lists exactly the bound account.
 *
 * Best-effort: the bridge passes the account id to `start()` explicitly and never
 * reads the index, so a failure costs discoverability, not function.
 */
async function syncIndex(accountId: string): Promise<void> {
  const path = indexPath();
  try {
    let existing: readonly string[] = [];
    try {
      const parsed: unknown = JSON.parse(await readFile(path, "utf8"));
      if (Array.isArray(parsed)) {
        existing = parsed.filter(
          (id): id is string => typeof id === "string" && id.trim() !== "",
        );
      }
    } catch {
      // A missing or unreadable index is the normal first-run case.
    }
    if (existing.length === 1 && existing[0] === accountId) {
      return;
    }
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, `${JSON.stringify([accountId], null, 2)}\n`, "utf8");
    log.info("SDK index now lists the bound account");
  } catch (cause) {
    log.warn("could not update the SDK index:", String(cause));
  }
}
