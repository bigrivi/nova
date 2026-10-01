/**
 * Bind the WeChat bot this bridge serves, then exit.
 *
 * WeChat allows one ClawBot per account: scanning a second QR replaces the first,
 * and the superseded bot's token is rejected from that moment on. So this binds
 * one account and takes no agent argument -- the agent is chosen in-band with
 * `/agent` once the bridge is running.
 *
 * Binding never deletes an existing account. The SDK's `logout()` wipes every
 * stored account, which is the wrong tool for replacing one.
 *
 * Usage:
 *   npm run login         bind a bot
 *   npm run login --list  show what is bound
 */

import { login } from "weixin-agent-sdk";
import { readBoundAccount, writeBoundAccount } from "./accounts.js";
import { loadConfig } from "./config.js";
import { error, info, setLogLevel } from "./log.js";

async function main(): Promise<void> {
  setLogLevel(process.env.NOVA_BRIDGE_LOG_LEVEL ?? "info");
  const path = loadConfig().accountPath;

  if (process.argv.includes("--list")) {
    const bound = await readBoundAccount(path);
    if (bound.kind === "unbound") {
      info("no bot is bound yet; run `npm run login` first");
      return;
    }
    if (bound.kind === "legacy") {
      info(
        `${path} is from an older layout that recorded a bot per agent, which ` +
          "WeChat does not allow. Run `npm run login` to rebind.",
      );
      return;
    }
    info(bound.accountId);
    return;
  }

  const bound = await readBoundAccount(path);
  if (bound.kind === "bound") {
    info(
      `a bot is already bound (${bound.accountId}). Scanning again replaces it: ` +
        "WeChat keeps one ClawBot per account.",
    );
  }
  if (bound.kind === "legacy") {
    info(
      "replacing a binding file from the older per-agent layout, which WeChat " +
        "does not allow",
    );
  }

  info("scan the QR code with WeChat to bind the bot");
  const accountId = await login({
    log: (message: string) => info("login", message),
  });

  await writeBoundAccount(path, accountId);
  info("now run `npm start` to serve messages");
}

try {
  await main();
} catch (cause) {
  error(`login failed: ${String(cause)}`);
  process.exitCode = 1;
}
