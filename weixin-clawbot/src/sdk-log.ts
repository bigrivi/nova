/**
 * Reading the SDK's log stream for conditions the operator must act on.
 *
 * The SDK reports an expired session as `errcode -14` and then pauses the account
 * for an hour, but the recovery it suggests is `npx weixin-acp login` -- a
 * command belonging to the ACP wrapper, not to this bridge. Following it would
 * send the operator somewhere that does not exist for them.
 */

import { error, info } from "./log.js";

/**
 * Matches the SDK's wording for an expired session.
 *
 * Both separators appear in its output: the human-facing line says
 * `errcode -14` while a failure line uses `errcode=-14`.
 */
const EXPIRED_SESSION = /errcode\s*[=-]\s*-14|session expired/;

/** What the operator should actually run. */
export const REBIND_HINT =
  "run `npm run login` to bind a new bot, then restart the bridge";

/** Whether an SDK log line means the stored WeChat session is no longer valid. */
export function isExpiredSession(message: string): boolean {
  return EXPIRED_SESSION.test(message);
}

/**
 * Route one SDK log line, escalating the ones that need intervention.
 *
 * The hour-long pause is in-memory only, so restarting always clears it --
 * worth saying, because the SDK's own wording implies waiting an hour.
 */
export function reportSdkMessage(message: string): void {
  if (!isExpiredSession(message)) {
    info("sdk", message);
    return;
  }
  error("the WeChat binding has expired; this bot will not receive messages");
  error(`  ${REBIND_HINT}`);
  error("  the one-hour pause is in-memory, so restarting clears it at once");
}