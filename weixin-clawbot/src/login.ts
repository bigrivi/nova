/**
 * Scan-and-store only: binds a WeChat account to this machine and exits.
 *
 * Useful on its own so the QR prompt does not have to share a terminal with the
 * message loop, and to rebind a different account (the SDK stores one account
 * per state directory, so a new scan replaces the previous one).
 */

import { isLoggedIn, login, logout } from "weixin-agent-sdk";
import { error, info, setLogLevel } from "./log.js";

async function main(): Promise<void> {
  setLogLevel(process.env.NOVA_BRIDGE_LOG_LEVEL ?? "info");

  if (isLoggedIn() && process.env.NOVA_BRIDGE_FORCE_LOGIN !== "1") {
    info("an account is already stored; set NOVA_BRIDGE_FORCE_LOGIN=1 to rebind");
    return;
  }
  if (isLoggedIn()) {
    info("clearing the stored account");
    logout({ log: (message: string) => info("logout", message) });
  }

  info("scan the QR code with WeChat to bind this machine");
  const accountId = await login({
    log: (message: string) => info("login", message),
  });
  info(`bound account ${accountId}`);
  info("now run `npm start` to serve messages");
}

try {
  await main();
} catch (cause) {
  error(`login failed: ${String(cause)}`);
  process.exitCode = 1;
}